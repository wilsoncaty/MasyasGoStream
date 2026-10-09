"""Server-to-server client for the isolated Go Stream license service."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

PRODUCT = "masyasgostream"


class LicenseError(Exception):
    def __init__(self, code, status=0):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class LicenseConfig:
    api_url: str
    installation_id: str
    deployment_url: str

    @classmethod
    def from_mapping(cls, values):
        api = str(values.get("api_url", "")).strip().rstrip("/")
        deployment = str(values.get("deployment_url", "")).strip().rstrip("/")
        installation = str(values.get("installation_id", "")).strip()
        for value in (api, deployment):
            parsed = urllib.parse.urlsplit(value)
            if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
                raise LicenseError("invalid_configuration")
            if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
                raise LicenseError("invalid_configuration")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", installation):
            raise LicenseError("invalid_configuration")
        return cls(api, installation, deployment)


class LicenseClient:
    def __init__(self, config):
        self.config = config

    def request(self, endpoint, token=None, **values):
        data = {**values, "product_id": PRODUCT, "installation_id": self.config.installation_id,
                "deployment_url": self.config.deployment_url}
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "MasyasGoStream/1.0"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(self.config.api_url + endpoint, data=json.dumps(data).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise LicenseError("service_unavailable")
            if "license" in result:
                if not isinstance(result["license"], dict) or result["license"].get("product_id") != PRODUCT:
                    raise LicenseError("wrong_product")
            return result
        except urllib.error.HTTPError as error:
            try:
                code = json.loads(error.read(8192)).get("error", "service_unavailable")
            except (ValueError, AttributeError):
                code = "service_unavailable"
            raise LicenseError(code, error.code) from None
        except (OSError, ValueError, TimeoutError):
            raise LicenseError("service_unavailable") from None

    def login(self, username, password):
        return self.request("/v1/login", username=username, password=password)

    def activate(self, code, username, password):
        return self.request("/v1/activate", license_key=code, username=username, password=password)

    def check(self, token):
        status = self.request("/v1/check", token).get("license")
        if not isinstance(status, dict) or not isinstance(status.get("can_start"), bool):
            raise LicenseError("service_unavailable")
        return status


ERROR_MESSAGES = {
    "invalid_configuration": "Konfigurasi deployment belum lengkap atau tidak valid.",
    "invalid_credentials": "Username atau password salah. Gunakan minimal 12 karakter untuk password.",
    "invalid_license": "License key tidak valid untuk Masyas Go Stream.",
    "wrong_product": "Lisensi ini bukan untuk Masyas Go Stream.",
    "installation_in_use": "Lisensi sudah digunakan deployment lain. Lepaskan atau minta admin mereset aktivasi lama.",
    "activation_changed": "Aktivasi berubah saat diproses. Coba masuk kembali.",
    "license_expired": "Lisensi sudah kedaluwarsa. Hubungi penjual untuk memperpanjang.",
    "license_revoked": "Lisensi telah dicabut. Hubungi penjual.",
    "login_required": "Sesi login berakhir atau aktivasi berubah. Silakan masuk kembali.",
    "rate_limited": "Terlalu banyak percobaan. Tunggu 15 menit sebelum mencoba lagi.",
    "service_not_ready": "Server lisensi belum siap. Hubungi pengelola.",
    "service_unavailable": "Server lisensi belum bisa dihubungi. Mulai siaran baru ditunda; siaran berjalan tidak dihentikan.",
}


def error_message(error):
    return ERROR_MESSAGES.get(error.code, "Permintaan lisensi gagal. Periksa konfigurasi atau hubungi pengelola.")
