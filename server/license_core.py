import base64
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import uuid
from pathlib import Path
from typing import Optional


APP_ID = "DZSP-RS485"
LICENSE_VERSION = 1
LICENSE_FILE_NAME = "license.dat"

# Keep this value private. The Windows key generator and Linux verifier must match.
SECRET_KEY = b"dzsp-rs485-license-v1-2026-keep-private"


@dataclasses.dataclass
class VerifyResult:
    ok: bool
    message: str
    expires_at: Optional[dt.date] = None


def normalize_machine_code(machine_code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", machine_code.upper())


def machine_code_from_fingerprint(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest().upper()
    return "-".join([digest[i : i + 4] for i in range(0, 20, 4)])


def get_machine_code_from_sources(machine_ids, mac_address: str = "", hostname: str = "") -> str:
    stable_machine_ids = [value.strip() for value in machine_ids if value and value.strip()]
    if stable_machine_ids:
        return machine_code_from_fingerprint("machine-id:" + stable_machine_ids[0])
    if mac_address:
        return machine_code_from_fingerprint("mac:" + mac_address.lower())
    return machine_code_from_fingerprint("host:" + (hostname or "UNKNOWN"))


def get_machine_code() -> str:
    machine_ids = []
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
            if value:
                machine_ids.append(value)
                break
        except OSError:
            pass

    mac = uuid.getnode()
    mac_address = f"{mac:012x}" if mac else ""
    hostname = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "UNKNOWN")
    return get_machine_code_from_sources(machine_ids, mac_address=mac_address, hostname=hostname)


def _sign(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(SECRET_KEY, body, hashlib.sha256).hexdigest().upper()


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    token = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join([token[i : i + 5] for i in range(0, len(token), 5)])


def _decode(license_code: str) -> Optional[dict]:
    token = re.sub(r"[^A-Z2-7]", "", license_code.upper())
    padding = "=" * (-len(token) % 8)
    try:
        raw = base64.b32decode((token + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def generate_license_code(machine_code: str, expires_at: Optional[dt.date] = None) -> str:
    normalized = normalize_machine_code(machine_code)
    expire_value = expires_at.isoformat() if expires_at else "PERMANENT"
    payload = {
        "app": APP_ID,
        "exp": expire_value,
        "machine": normalized,
        "v": LICENSE_VERSION,
    }
    payload["sig"] = _sign(payload)
    return _encode(payload)


def verify_license_code(machine_code: str, license_code: str, today: Optional[dt.date] = None) -> VerifyResult:
    payload = _decode(license_code)
    if not payload:
        return VerifyResult(False, "授权码无效")

    signature = payload.get("sig")
    unsigned = dict(payload)
    unsigned.pop("sig", None)

    if payload.get("app") != APP_ID or payload.get("v") != LICENSE_VERSION:
        return VerifyResult(False, "授权码无效")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, _sign(unsigned)):
        return VerifyResult(False, "授权码无效")
    if payload.get("machine") != normalize_machine_code(machine_code):
        return VerifyResult(False, "授权码与本机机器码不匹配")

    exp = payload.get("exp")
    if exp == "PERMANENT":
        return VerifyResult(True, "授权成功")

    try:
        expires_at = dt.date.fromisoformat(str(exp))
    except ValueError:
        return VerifyResult(False, "授权码无效")

    current = today or dt.date.today()
    if current > expires_at:
        return VerifyResult(False, "授权码已过期", expires_at=expires_at)

    return VerifyResult(True, "授权成功", expires_at=expires_at)


def load_license(root_dir: Path) -> str:
    path = root_dir / LICENSE_FILE_NAME
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_license(root_dir: Path, license_code: str) -> None:
    path = root_dir / LICENSE_FILE_NAME
    path.write_text(license_code.strip() + "\n", encoding="utf-8")
