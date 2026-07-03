"""Privacy-preserving, multi-identifier machine fingerprint abstraction."""

import hashlib
import os
import platform
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


FINGERPRINT_DOMAIN = "carthage-pos-machine-v1"


@dataclass(frozen=True)
class MachineFingerprint:
    fingerprint: str
    identifiers: dict[str, str]

    def to_dict(self) -> dict:
        return {"fingerprint": self.fingerprint,
                "identifiers": dict(sorted(self.identifiers.items()))}


class FingerprintProvider(ABC):
    @abstractmethod
    def get_identifiers(self) -> dict[str, str]:
        """Return raw local identifiers; callers only receive hashes."""

    def fingerprint(self) -> MachineFingerprint:
        hashed = {
            name: _hash_identifier(name, value)
            for name, value in self.get_identifiers().items()
            if str(value or "").strip()
        }
        combined = hashlib.sha256(
            "|".join(f"{name}:{value}" for name, value in sorted(hashed.items())).encode("utf-8")
        ).hexdigest()
        return MachineFingerprint(combined, hashed)


class SystemFingerprintProvider(FingerprintProvider):
    def get_identifiers(self) -> dict[str, str]:
        identifiers = {
            "host": platform.node() or os.environ.get("COMPUTERNAME", ""),
            "machine": platform.machine(),
            "mac": f"{uuid.getnode():012x}",
        }
        machine_id = _machine_id()
        if machine_id:
            identifiers["machine_id"] = machine_id
        volume = _windows_volume_serial()
        if volume:
            identifiers["system_volume"] = volume
        return identifiers


class StaticFingerprintProvider(FingerprintProvider):
    def __init__(self, identifiers: dict[str, str]):
        self.identifiers = identifiers

    def get_identifiers(self) -> dict[str, str]:
        return dict(self.identifiers)


def fingerprint_matches(bound_identifiers: list[str], current: MachineFingerprint,
                        minimum_matches: int = 1) -> dict:
    bound = set(bound_identifiers or [])
    current_values = set(current.identifiers.values())
    matches = len(bound & current_values)
    required = min(max(int(minimum_matches), 1), max(len(bound), 1))
    return {"matches": matches, "required": required,
            "matched": bool(bound) and matches >= required}


def _hash_identifier(name, value):
    normalized = str(value).strip().lower()
    return hashlib.sha256(f"{FINGERPRINT_DOMAIN}|{name}|{normalized}".encode("utf-8")).hexdigest()


def _machine_id():
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography") as key:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            return ""
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return ""


def _windows_volume_serial():
    if os.name != "nt":
        return ""
    try:
        import ctypes
        serial = ctypes.c_ulong()
        root = os.environ.get("SystemDrive", "C:") + "\\"
        success = ctypes.windll.kernel32.GetVolumeInformationW(
            root, None, 0, ctypes.byref(serial), None, None, None, 0
        )
        return f"{serial.value:08x}" if success else ""
    except (AttributeError, OSError):
        return ""
