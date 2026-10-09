"""Read-only telemetry, refreshed independently from streaming controls."""

import time
from html import escape

import psutil
import streamlit as st


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
    """Share a bounded sample between viewers, without touching FFmpeg state."""
    sample = {"streams": count_streams(), "cpu": None, "memory": None, "network": None}
    try:
        # A bounded interval avoids the meaningless initial nonblocking reading.
        sample["cpu"] = psutil.cpu_percent(interval=0.1)
    except (psutil.Error, OSError, NotImplementedError):
        pass
    try:
        memory = psutil.virtual_memory()
        sample["memory"] = (memory.total - memory.available, memory.total, memory.percent)
    except (psutil.Error, OSError, NotImplementedError):
        pass
    try:
        network = psutil.net_io_counters()
        if network is not None:
            sample["network"] = (time.monotonic(), network.bytes_sent, network.bytes_recv)
    except (psutil.Error, OSError, NotImplementedError):
        pass
    return sample


def network_rates(previous, current):
    """Actual sent/received bits per second; None means no valid interval."""
    if previous is None or current is None:
        return None
    elapsed = current[0] - previous[0]
    sent, received = current[1] - previous[1], current[2] - previous[2]
    if elapsed <= 0 or sent < 0 or received < 0:
        return None
    return sent * 8 / elapsed, received * 8 / elapsed


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
    current = sample["network"]
    previous = st.session_state.get("_gs_network_sample")
    rates = network_rates(previous, current)
    # Full UI reruns may reuse a cached sample. Keep its last valid rate.
    if current is not None and current == previous:
        rates = st.session_state.get("_gs_network_rates")
    else:
        st.session_state["_gs_network_sample"] = current
        st.session_state["_gs_network_rates"] = rates

    streams, cpu, memory = sample["streams"], sample["cpu"], sample["memory"]
    stream_card = card("Stream aktif", "◉", str(streams) if streams is not None else "—", "Proses siaran aplikasi" if streams is not None else "Data tidak tersedia")
    cpu_card = card("CPU server", "▦", f"{cpu:.1f}<small>%</small>" if cpu is not None else "—", "Penggunaan CPU saat ini" if cpu is not None else "Data tidak tersedia", cpu)
    memory_value = f'{format_memory(memory[0])}<small> / {format_memory(memory[1])}</small>' if memory else "—"
    memory_card = card("Memori server", "▤", memory_value, "Terpakai / total terdeteksi" if memory else "Data tidak tersedia", memory[2] if memory else None)
    up, down = (format_rate(rate) for rate in rates) if rates is not None else ("—", "—")
    network_detail = "Trafik aktual · bukan speed test" if rates is not None else ("Menunggu sampel berikutnya…" if current is not None else "Data tidak tersedia")
    network_card = f'<div class="gs-stat-card"><div class="gs-stat-head"><span>Trafik jaringan</span><span class="gs-stat-icon" aria-hidden="true">↕</span></div><div class="gs-network-row"><span>↑ Upload</span><strong>{up}</strong></div><div class="gs-network-row gs-download"><span>↓ Download</span><strong>{down}</strong></div><div class="gs-stat-detail">{network_detail}</div></div>'
    st.markdown(f'<div class="gs-stats-grid">{stream_card}{cpu_card}{memory_card}{network_card}</div>', unsafe_allow_html=True)
    st.caption("Diperbarui setiap 2 detik selama halaman aktif · Statistik server, bukan perangkat pengunjung.")
    with st.expander("Tentang angka monitoring"):
        st.caption("Stream aktif menghitung proses FFmpeg yang mengirim ke RTMP dari aplikasi ini, termasuk sesi pengguna lain pada proses server yang sama. Angka ini bukan konfirmasi siaran sudah tampil di YouTube. CPU dan RAM mengikuti data sistem operasi; pada hosting bersama, nilainya bisa mewakili host, bukan batas paket akun. Trafik jaringan mencakup semua aktivitas pada jaringan yang terlihat oleh server, bukan hanya siaran.")
