"""Read-only telemetry, refreshed independently from streaming controls."""

import time
from html import escape

import psutil
import streamlit as st
from gostream_resources import container_resources, process_resources, application_storage, network_sample


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
    return {**resources, "streams": count_streams(), "time": time.monotonic(),
            "network": network_sample(), "storage": storage_sample()}


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


def card(title, icon, value, detail, percent=None):
    bar = ""
    if percent is not None:
        percent = max(0, min(100, percent))
        bar = f'<div class="gs-stat-track" role="meter" aria-label="{escape(title)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent:.1f}"><span style="width:{percent:.1f}%"></span></div>'
    return f'<div class="gs-stat-card"><div class="gs-stat-head"><span>{escape(title)}</span><span class="gs-stat-icon" aria-hidden="true">{icon}</span></div><div class="gs-stat-value">{value}</div>{bar}<div class="gs-stat-detail">{escape(detail)}</div></div>'


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
    if memory:
        memory_value = format_memory(memory["used"])
        memory_detail = "Container" if memory["scope"] == "container" else "RSS proses aplikasi + FFmpeg"
        if memory["limit"] is not None:
            memory_value += f'<small> / {format_memory(memory["limit"])}</small>'
            memory_percent = memory["used"] / memory["limit"] * 100
            memory_detail += " · terpakai / batas terdeteksi"
        else:
            memory_detail += " · batas tidak tersedia"
    memory_card = card("RAM aplikasi", "▤", memory_value, memory_detail, memory_percent)

    storage = sample["storage"]
    storage_card = card("Storage file aplikasi", "▣", format_memory(storage) if storage is not None else "—",
                        "Project & uploads · kuota tidak tersedia" if storage is not None else "Data tidak tersedia")
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
- **RAM:** penggunaan dan batas cgroup container jika bisa dibaca. Jika tidak, jumlah RSS proses aplikasi dan turunannya (termasuk FFmpeg); memori bersama bisa terhitung lebih dari sekali. Tidak memakai total RAM server induk sebagai jatah aplikasi.
- **CPU:** persentase pemakaian terhadap batas CPU cgroup yang terdeteksi. Jika batas tidak tersedia, ditampilkan dalam core terpakai; 1 core berarti satu CPU penuh. Ini pembacaan runtime, bukan janji resource paket hosting.
- **Storage:** ukuran logis file project dan uploads, tidak termasuk environment Python, cache, atau Git. Kuota storage hosting tidak diketahui, sehingga tidak ditampilkan sebagai persentase disk server.
- **Trafik:** perubahan byte kirim/terima pada interface non-loopback dalam namespace jaringan yang terlihat oleh aplikasi. Bisa mencakup proses lain jika namespace dibagi. Di komputer lokal, cakupannya jaringan komputer tersebut. Bukan speed test atau pengukuran khusus YouTube.
""")
