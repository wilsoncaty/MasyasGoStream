"""Read-only telemetry, refreshed independently from streaming controls."""

import time
from html import escape

import psutil
import streamlit as st
from gostream_resources import (container_resources, process_resources, application_storage,
                                network_sample, disk_capacity, memory_capacity, service_memory_limit)


def count_streams():
    """Count this app's live RTMP FFmpeg children, not unrelated server jobs."""
    count = 0
    try:
        children = psutil.Process().children(recursive=True)
    except (psutil.Error, OSError):
        return None
    for child in children:
        try:
            if child.name().lower() not in ("ffmpeg", "ffmpeg.exe"):
                continue
            if child.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                continue
            # Inspect locally; never store or display command lines / stream keys.
            if any(arg.startswith(("rtmp://", "rtmps://")) for arg in child.cmdline()):
                count += 1
        except psutil.NoSuchProcess:
            continue
        except (psutil.Error, OSError):
            return None
    return count


@st.cache_data(ttl=2, show_spinner=False)
def server_sample():
    resources = container_resources()
    if resources["memory"] is None or resources["cpu"] is None:
        fallback = process_resources()
        for name in ("memory", "cpu"):
            if resources[name] is None:
                resources[name] = fallback[name]
    resources["memory"] = memory_capacity(resources["memory"], service_memory_limit())
    return {**resources, "streams": count_streams(), "time": time.monotonic(),
            "network": network_sample(), "storage": {"files": storage_sample(), "disk": disk_capacity()}}


@st.cache_data(ttl=15, show_spinner=False)
def storage_sample():
    return application_storage()


def network_rates(previous, current):
    """Actual sent/received bits per second; None means no valid interval."""
    if previous is None or current is None:
        return None
    elapsed = current["time"] - previous["time"]
    if elapsed <= 0 or current["identity"] != previous["identity"]:
        return None
    common = current["interfaces"].keys() & previous["interfaces"].keys()
    if not common:
        return None
    sent = received = 0
    for name in common:
        upload = current["interfaces"][name][0] - previous["interfaces"][name][0]
        download = current["interfaces"][name][1] - previous["interfaces"][name][1]
        if upload < 0 or download < 0:
            return None
        sent += upload
        received += download
    return sent * 8 / elapsed, received * 8 / elapsed


def cpu_rate(previous, current):
    """CPU seconds / wall seconds = cores used. Never normalize by host CPUs."""
    if not previous or not previous["cpu"] or not current["cpu"]:
        return None
    before, after = previous["cpu"], current["cpu"]
    elapsed = current["time"] - previous["time"]
    if elapsed <= 0 or before["scope"] != after["scope"]:
        return None
    common = before["counters"].keys() & after["counters"].keys()
    if not common:
        return None
    deltas = [after["counters"][key] - before["counters"][key] for key in common]
    if any(value < 0 for value in deltas):
        return None
    return sum(deltas) / elapsed


def format_rate(bits_per_second):
    for unit in ("bps", "Kbps", "Mbps", "Gbps"):
        if bits_per_second < 1000 or unit == "Gbps":
            return f"{bits_per_second:,.2f} {unit}"
        bits_per_second /= 1000


def format_memory(size):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:,.2f} {unit}"
        size /= 1024


def format_capacity(size):
    """Use decimal GB consistently with the service's 2.7 GB label."""
    return f"{size / 1_000_000_000:,.2f} GB"


def card(title, icon, value, detail, percent=None, remaining=None):
    bar = ""
    if percent is not None:
        percent = max(0, min(100, percent))
        bar = f'<div class="gs-stat-track" role="meter" aria-label="{escape(title)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent:.1f}"><span style="width:{percent:.1f}%"></span></div>'
    remaining_html = f'<div class="gs-stat-remaining">{escape(remaining)}</div>' if remaining is not None else ""
    return f'<div class="gs-stat-card"><div class="gs-stat-head"><span>{escape(title)}</span><span class="gs-stat-icon" aria-hidden="true">{icon}</span></div><div class="gs-stat-value">{value}</div>{bar}{remaining_html}<div class="gs-stat-detail">{escape(detail)}</div></div>'


@st.fragment(run_every="2s")
def render_monitor():
    sample = server_sample()
    previous = st.session_state.get("_gs_resource_sample")
    if previous and previous["time"] == sample["time"]:
        rates, cores = st.session_state.get("_gs_resource_rates", (None, None))
    else:
        rates = network_rates(previous["network"] if previous else None, sample["network"])
        cores = cpu_rate(previous, sample)
        st.session_state["_gs_resource_sample"] = sample
        st.session_state["_gs_resource_rates"] = (rates, cores)

    streams, cpu, memory = sample["streams"], sample["cpu"], sample["memory"]
    stream_card = card("Stream aktif", "◉", str(streams) if streams is not None else "—", "Proses FFmpeg siaran" if streams is not None else "Data tidak tersedia")
    cpu_value, cpu_detail, cpu_percent = "—", "Data tidak tersedia", None
    if cpu:
        cpu_detail = "Container" if cpu["scope"] == "container" else "Proses aplikasi + FFmpeg"
        if cpu["limit"] is not None:
            cpu_detail += f' · batas {cpu["limit"]:g} core'
            if cores is not None:
                cpu_percent = cores / cpu["limit"] * 100
                cpu_value = f'{cpu_percent:.1f}<small>%</small>'
        else:
            cpu_detail += " · batas tidak tersedia"
            if cores is not None:
                cpu_value = f'{cores:.2f}<small> core</small>'
        if cores is None:
            cpu_detail = "Mengukur… · " + cpu_detail
    cpu_card = card("CPU aplikasi", "▦", cpu_value, cpu_detail, cpu_percent)

    memory_value, memory_detail, memory_percent = "—", "Data tidak tersedia", None
    memory_remaining = None
    if memory:
        memory_value = format_capacity(memory["used"])
        memory_detail = "Container" if memory["scope"] == "container" else "RSS proses aplikasi + FFmpeg"
        if memory["limit"] is not None:
            memory_value += f'<small> / {format_capacity(memory["limit"])}</small>'
            memory_percent = memory["used"] / memory["limit"] * 100
            memory_detail = memory["source"] + " · terpakai / batas"
            memory_remaining = "Sisa terhadap batas: " + format_capacity(memory["remaining"])
            if memory_percent >= 100:
                memory_remaining = "Batas RAM tercapai · sisa 0 GB"
            elif memory_percent >= 90:
                memory_remaining += " · hampir penuh"
        else:
            memory_detail += " · batas tidak tersedia"
    memory_card = card("RAM aplikasi", "▤", memory_value, memory_detail, memory_percent, memory_remaining)

    storage = sample["storage"]
    disk, files = storage["disk"], storage["files"]
    file_detail = "File aplikasi: " + format_memory(files) if files is not None else "Ukuran file aplikasi tidak tersedia"
    if disk:
        storage_value = f'{format_capacity(disk["used"])}<small> / {format_capacity(disk["total"])}</small>'
        storage_remaining = "Sisa disk: " + format_capacity(disk["free"])
        if disk["free"] == 0:
            storage_remaining += " · penuh"
        elif disk["free"] / disk["total"] <= 0.1:
            storage_remaining += " · hampir penuh"
        storage_card = card("Disk penyimpanan", "▣", storage_value,
                            "Disk terdeteksi · bisa dibagi hosting. " + file_detail,
                            disk["used"] / disk["total"] * 100, storage_remaining)
    else:
        storage_card = card("Disk penyimpanan", "▣", "—", file_detail, remaining="Sisa disk tidak bisa dibaca")
    up, down = (format_rate(rate) for rate in rates) if rates is not None else ("—", "—")
    network = sample["network"]
    network_detail = network["scope"] if network else "Data tidak tersedia"
    if network and rates is None:
        network_detail = "Mengukur… · " + network_detail
    network_card = f'<div class="gs-stat-card"><div class="gs-stat-head"><span>Trafik jaringan</span><span class="gs-stat-icon" aria-hidden="true">↕</span></div><div class="gs-network-row"><span>↑ Upload</span><strong>{up}</strong></div><div class="gs-network-row gs-download"><span>↓ Download</span><strong>{down}</strong></div><div class="gs-stat-detail">{network_detail}</div></div>'
    st.markdown(f'<div class="gs-stats-grid">{stream_card}{memory_card}{cpu_card}{storage_card}{network_card}</div>', unsafe_allow_html=True)
    st.caption("Data lingkungan aplikasi · diperbarui setiap 2 detik saat halaman aktif; ukuran file setiap 15 detik.")
    with st.expander("Sumber dan batas pembacaan"):
        st.markdown("""
- **Stream aktif:** proses FFmpeg aplikasi yang menggunakan tujuan RTMP. Bukan konfirmasi status live dari YouTube; dapat mencakup beberapa sesi pengguna aplikasi.
- **RAM:** penggunaan container dibandingkan batas layanan yang dikonfigurasi dari Workspace Settings (2,7 GB). Jika batas container lebih kecil, batas lebih kecil tersebut digunakan. Sisa adalah selisih batas dengan penggunaan saat ini, bukan jumlah file yang aman di-upload. Nilai GB desimal berbeda dari GiB. Jika container tidak bisa dibaca, gunakan RSS proses aplikasi dan turunannya tanpa mengasumsikan jatah cloud; memori bersama bisa terhitung lebih dari sekali.
- **CPU:** persentase pemakaian terhadap batas CPU cgroup yang terdeteksi. Jika batas tidak tersedia, ditampilkan dalam core terpakai; 1 core berarti satu CPU penuh. Ini pembacaan runtime, bukan janji resource paket hosting.
- **Disk penyimpanan:** total, terpakai, dan ruang disk tersedia pada filesystem tempat folder uploads berada. Disk dapat dibagi dengan aplikasi/proses hosting lain; angka ini bukan kuota eksklusif aplikasi atau janji seluruh ruang bebas dapat dipakai. File yang disimpan menambah pemakaian; sisa juga dapat berubah karena aktivitas lain. Sebagian ruang dapat dicadangkan sistem, sehingga total dikurangi terpakai tidak selalu sama dengan sisa yang tersedia. Ukuran file aplikasi dihitung terpisah, tanpa Git, environment Python, atau cache.
- **Trafik:** perubahan byte kirim/terima pada interface non-loopback dalam namespace jaringan yang terlihat oleh aplikasi. Bisa mencakup proses lain jika namespace dibagi. Di komputer lokal, cakupannya jaringan komputer tersebut. Bukan speed test atau pengukuran khusus YouTube.
""")
