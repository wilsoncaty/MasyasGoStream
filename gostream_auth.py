"""Owner login and license UI. Tokens live only in each browser's server session."""

import time
from datetime import datetime, timezone
from html import escape

import streamlit as st
from gostream_license import LicenseClient, LicenseConfig, LicenseError, error_message


def config_from_secrets():
    try:
        return LicenseConfig.from_mapping(dict(st.secrets["gostream_license"]))
    except (KeyError, FileNotFoundError):
        raise LicenseError("invalid_configuration") from None


def clear_owner():
    for key in ("_gs_owner_token", "_gs_owner_status", "_gs_owner_checked_at", "_gs_owner_api_error"):
        st.session_state.pop(key, None)


def remember(result):
    if not isinstance(result.get("session_token"), str) or not result.get("license"):
        raise LicenseError("service_unavailable")
    st.session_state["_gs_owner_token"] = result["session_token"]
    st.session_state["_gs_owner_status"] = result["license"]
    st.session_state["_gs_owner_checked_at"] = time.monotonic()
    st.session_state.pop("_gs_owner_api_error", None)


def refresh_status(client):
    token = st.session_state.get("_gs_owner_token")
    if not token:
        raise LicenseError("login_required", 401)
    try:
        status = client.check(token)
        st.session_state["_gs_owner_status"] = status
        st.session_state["_gs_owner_checked_at"] = time.monotonic()
        st.session_state.pop("_gs_owner_api_error", None)
        return status
    except LicenseError as error:
        st.session_state["_gs_owner_api_error"] = error_message(error)
        if error.status == 401:
            clear_owner()
        raise


def require_owner():
    try:
        client = LicenseClient(config_from_secrets())
    except LicenseError as error:
        st.subheader("Siapkan Masyas Go Stream")
        st.info("Pemilik deployment perlu memasang konfigurasi lisensi di Streamlit Settings → Secrets terlebih dahulu.")
        st.caption("Gunakan file konfigurasi instalasi yang diberikan penjual. Identitas instalasi harus tetap sama setelah reboot/redeploy.")
        st.stop()

    if st.session_state.get("_gs_owner_token"):
        if time.monotonic() - st.session_state.get("_gs_owner_checked_at", 0) > 30:
            try:
                refresh_status(client)
            except LicenseError as error:
                if error.status != 401:
                    # An authenticated owner retains Stop access during an outage.
                    return client
        if st.session_state.get("_gs_owner_token"):
            return client

    st.subheader("Masuk ke studio")
    st.caption("Dashboard hanya untuk pemilik. Satu lisensi berlaku untuk satu deployment; beberapa browser dapat login ke deployment yang sama.")
    with st.form("owner_login", clear_on_submit=True):
        username = st.text_input("Username pemilik", max_chars=64)
        password = st.text_input("Password pemilik", type="password", max_chars=128)
        submit = st.form_submit_button("Masuk", type="primary", use_container_width=True)
    if submit:
        try:
            remember(client.login(username, password))
            st.rerun()
        except LicenseError as error:
            st.error(error_message(error))
    with st.expander("Aktivasi pertama / pindah deployment"):
        st.caption("Masa aktif 365 hari dimulai saat aktivasi pertama berhasil. Untuk pindah deployment, gunakan akun pemilik yang sama; masa aktif tidak dimulai ulang.")
        with st.form("owner_activation", clear_on_submit=True):
            code = st.text_input("License key Go Stream", type="password")
            owner = st.text_input("Buat username pemilik", help="3–64 karakter: huruf kecil, angka, titik, garis bawah, atau tanda minus.")
            secret = st.text_input("Buat password pemilik", type="password", help="Minimal 12 karakter; simpan di password manager.", max_chars=128)
            confirm = st.text_input("Ulangi password", type="password", max_chars=128)
            activate = st.form_submit_button("Aktifkan lisensi", use_container_width=True)
        if activate:
            if secret != confirm:
                st.error("Konfirmasi password tidak sama.")
            else:
                try:
                    remember(client.activate(code, owner, secret))
                    st.rerun()
                except LicenseError as error:
                    st.error(error_message(error))
    st.stop()


def can_start_stream(client):
    """Fresh server validation at the start boundary, never a cached UI decision."""
    try:
        status = refresh_status(client)
    except LicenseError as error:
        st.error(error_message(error))
        return False
    if not status.get("can_start"):
        st.error("Lisensi tidak aktif. Siaran baru tidak dapat dimulai; siaran yang berjalan tetap bisa dihentikan.")
        return False
    return True


@st.fragment(run_every="30s")
def owner_panel(client):
    try:
        status = refresh_status(client)
    except LicenseError as error:
        if error.status == 401:
            st.rerun(scope="app")
        st.warning(error_message(error))
        status = st.session_state.get("_gs_owner_status", {})
    expiry = status.get("expires_at")
    expires = datetime.fromtimestamp(expiry, timezone.utc).strftime("%d %b %Y, %H:%M UTC") if expiry else "Belum aktif"
    state = {"active": "Aktif", "expired": "Kedaluwarsa", "revoked": "Dicabut"}.get(status.get("status"), "Belum terverifikasi")
    st.markdown(f'<div class="gs-license-bar"><strong>Lisensi Go Stream · {escape(state)}</strong><span>Berlaku sampai {escape(expires)}</span></div>', unsafe_allow_html=True)
    with st.expander("Akun pemilik & lisensi"):
        st.write(f"Pemilik: **{status.get('owner_username', '')}**")
        st.caption("1 deployment · beberapa browser · 365 hari sejak aktivasi pertama. Kedaluwarsa membatasi mulai siaran baru, bukan menghentikan proses yang sedang berjalan.")
        if st.button("Keluar dari browser ini", key="owner_logout"):
            try:
                client.request("/v1/logout", st.session_state.get("_gs_owner_token"))
            except LicenseError:
                pass
            clear_owner()
            st.rerun(scope="app")
        confirmed = st.checkbox("Saya ingin melepas deployment ini untuk pindah ke aplikasi lain.", key="confirm_release")
        if st.button("Lepas aktivasi deployment", disabled=not confirmed, key="owner_release"):
            from gostream_runtime import runtime
            if runtime.is_running():
                st.error("Hentikan siaran terlebih dahulu sebelum melepas deployment.")
            else:
                try:
                    client.request("/v1/release", st.session_state.get("_gs_owner_token"))
                    clear_owner()
                    st.rerun(scope="app")
                except LicenseError as error:
                    st.error(error_message(error))
