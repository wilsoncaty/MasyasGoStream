"""Read container resource counters without substituting host capacity."""

import os
import re
import sys
import time
import tomllib
from pathlib import Path, PurePosixPath

import psutil

APP_DIR = Path(__file__).resolve().parent


def service_memory_limit(config=APP_DIR / "monitoring.toml"):
    """Workspace service limit, explicitly configured rather than inferred from RAM."""
    try:
        with Path(config).open("rb") as file:
            value = float(tomllib.load(file)["service"]["memory_limit_gb"])
        return int(value * 1_000_000_000) if 0 < value < 1_000_000 else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def memory_capacity(memory, service_limit):
    """Combine measured usage with the smaller visible container/service ceiling."""
    if memory is None:
        return None
    limit, source = memory["limit"], "Batas container"
    if memory["scope"] == "container" and service_limit is not None:
        if limit is None or service_limit <= limit:
            limit, source = service_limit, "Batas layanan Streamlit"
    return {**memory, "limit": limit, "source": source if limit is not None else "Batas tidak tersedia",
            "remaining": max(0, limit - memory["used"]) if limit is not None else None}


def disk_capacity(root=APP_DIR):
    """Filesystem holding uploads. Capacity may be shared; it is not an app quota."""
    upload_dir = root / "uploads"
    target = upload_dir if upload_dir.is_dir() else root
    try:
        disk = psutil.disk_usage(str(target))
        if disk.total <= 0:
            return None
        return {"total": disk.total, "used": disk.used, "free": disk.free,
                "reserved": max(0, disk.total - disk.used - disk.free)}
    except (OSError, psutil.Error):
        return None


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def number(path):
    try:
        return int(read_text(path))
    except (ValueError, TypeError):
        return None


def mount_unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def cgroup_locations(proc_root=Path("/proc")):
    """Resolve this process's memberships against its visible cgroup mounts."""
    groups = {}
    for line in (read_text(proc_root / "self/cgroup") or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3:
            for controller in parts[1].split(","):
                groups[controller] = PurePosixPath(parts[2])
    locations = {}
    for line in (read_text(proc_root / "self/mountinfo") or "").splitlines():
        try:
            before, after = line.split(" - ", 1)
            fields, filesystem = before.split(), after.split()
            kind = filesystem[0]
            if kind not in ("cgroup", "cgroup2"):
                continue
            mount_root = PurePosixPath(mount_unescape(fields[3]))
            mount = Path(mount_unescape(fields[4]))
            controllers = [""] if kind == "cgroup2" else filesystem[2].split(",")
            for controller in controllers:
                membership = groups.get(controller)
                if membership is None or ".." in membership.parts:
                    continue
                try:
                    relative = membership.relative_to(mount_root)
                except ValueError:
                    # A namespaced container may report '/' while mountinfo
                    # retains the host-side mount root.
                    if membership != PurePosixPath("/"):
                        continue
                    relative = PurePosixPath(".")
                leaf = mount.joinpath(*relative.parts)
                if membership == PurePosixPath("/") and mount_root == PurePosixPath("/"):
                    # On v2 the real host root has no memory.current. On v1,
                    # a root-only mount cannot reliably establish app scope.
                    if kind == "cgroup" or not (leaf / "memory.current").is_file():
                        continue
                if leaf.is_dir():
                    locations[controller or "v2"] = (leaf, mount)
        except (ValueError, IndexError):
            continue
    return locations


def ancestors(location):
    leaf, mount = location
    while True:
        yield leaf
        if leaf == mount:
            break
        leaf = leaf.parent


def finite_memory(value):
    # v1 uses a page-aligned LONG_MAX sentinel for unlimited memory.
    return value is not None and 0 < value < (1 << 60)


def quota_cores(path, version):
    try:
        if version == 2:
            quota, period = map(int, (read_text(path / "cpu.max") or "").split())
        else:
            quota, period = number(path / "cpu.cfs_quota_us"), number(path / "cpu.cfs_period_us")
        return quota / period if quota > 0 and period > 0 else None
    except (ValueError, TypeError):
        return None


def cpuset_count(value):
    if not value:
        return None
    try:
        count = 0
        for item in value.split(","):
            bounds = list(map(int, item.split("-")))
            if len(bounds) not in (1, 2) or min(bounds) < 0 or bounds[-1] < bounds[0]:
                return None
            count += bounds[-1] - bounds[0] + 1
        return count or None
    except ValueError:
        return None


def container_resources(locations=None):
    locations = cgroup_locations() if locations is None else locations
    result = {"memory": None, "cpu": None}
    v2 = locations.get("v2")
    memory_group = v2 or locations.get("memory")
    if memory_group:
        usage_name = "memory.current" if v2 else "memory.usage_in_bytes"
        limit_name = "memory.max" if v2 else "memory.limit_in_bytes"
        used = number(memory_group[0] / usage_name)
        limits = [number(path / limit_name) for path in ancestors(memory_group)]
        if not v2:
            stat = read_text(memory_group[0] / "memory.stat") or ""
            for line in stat.splitlines():
                if line.startswith("hierarchical_memory_limit "):
                    try:
                        limits.append(int(line.split()[1]))
                    except (IndexError, ValueError):
                        pass
        limits = [value for value in limits if finite_memory(value)]
        if used is not None and used >= 0:
            result["memory"] = {"used": used, "limit": min(limits) if limits else None, "scope": "container"}
    cpu_group = v2 or locations.get("cpuacct")
    if cpu_group:
        seconds = None
        if v2:
            for line in (read_text(cpu_group[0] / "cpu.stat") or "").splitlines():
                if line.startswith("usage_usec "):
                    try:
                        seconds = int(line.split()[1]) / 1_000_000
                    except (IndexError, ValueError):
                        pass
        else:
            nanos = number(cpu_group[0] / "cpuacct.usage")
            if nanos is not None:
                seconds = nanos / 1_000_000_000
        quota_group = v2 or locations.get("cpu")
        quotas = [quota_cores(path, 2 if v2 else 1) for path in ancestors(quota_group)] if quota_group else []
        quotas = [value for value in quotas if value is not None]
        limit = min(quotas) if quotas else None
        cpuset_group = v2 or locations.get("cpuset")
        if limit is not None and cpuset_group:
            for path in ancestors(cpuset_group):
                count = cpuset_count(read_text(path / ("cpuset.cpus.effective" if v2 else "cpuset.cpus")))
                if count is not None:
                    limit = min(limit, count)
        if seconds is not None and seconds >= 0:
            result["cpu"] = {"counters": {str(cpu_group[0]): seconds}, "limit": limit, "scope": "container"}
    return result


def process_resources():
    """Honest local fallback: aggregate this Python process and its children."""
    try:
        parent = psutil.Process()
        processes = [parent] + parent.children(recursive=True)
    except (psutil.Error, OSError):
        return {"memory": None, "cpu": None}
    rss, counters = 0, {}
    memory_ok = cpu_ok = True
    for process in processes:
        try:
            with process.oneshot():
                identity = f"{process.pid}:{process.create_time()}"
                times = process.cpu_times()
                counters[identity] = times.user + times.system
                rss += process.memory_info().rss
        except psutil.NoSuchProcess:
            continue
        except (psutil.Error, OSError):
            memory_ok = cpu_ok = False
    return {
        "memory": {"used": rss, "limit": None, "scope": "proses"} if memory_ok else None,
        "cpu": {"counters": counters, "limit": None, "scope": "proses"} if cpu_ok else None,
    }


def application_storage(root=APP_DIR):
    """Logical size of project/upload files; never claim filesystem size is quota."""
    total, errors = 0, []
    ignored = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
    for directory, folders, files in os.walk(root, onerror=errors.append, followlinks=False):
        folders[:] = [name for name in folders if name not in ignored and not Path(directory, name).is_symlink()]
        for name in files:
            path = Path(directory, name)
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError as error:
                errors.append(error)
    return None if errors else total


def network_sample():
    try:
        counters = psutil.net_io_counters(pernic=True)
        interfaces = {name: (counter.bytes_sent, counter.bytes_recv) for name, counter in counters.items()
                      if name.lower() != "lo" and "loopback" not in name.lower()}
        if not interfaces:
            return None
        namespace = os.readlink("/proc/self/ns/net") if sys.platform.startswith("linux") else "local"
        return {"time": time.monotonic(), "interfaces": interfaces, "identity": namespace,
                "scope": "Namespace jaringan aplikasi" if sys.platform.startswith("linux") else "Jaringan mesin lokal"}
    except (psutil.Error, OSError, NotImplementedError):
        return None
