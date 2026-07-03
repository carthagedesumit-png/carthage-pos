"""Strict RSA-SHA256 PKCS#1 v1.5 license signatures using public-key verification."""

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import LicenseValidationError


SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


@dataclass(frozen=True)
class RSAPublicKey:
    modulus: int
    exponent: int
    key_id: str


@dataclass(frozen=True)
class RSAPrivateKey:
    modulus: int
    private_exponent: int
    key_id: str


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def load_public_key(source: str | dict) -> RSAPublicKey:
    data = _load_key_data(source)
    try:
        if data.get("algorithm") not in {None, "RSA-SHA256-PKCS1v15"}:
            raise ValueError("algorithm")
        key = RSAPublicKey(
            modulus=int.from_bytes(_decode(data["n"]), "big"),
            exponent=int.from_bytes(_decode(data["e"]), "big"),
            key_id=str(data["key_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseValidationError("License public key is malformed.") from exc
    _validate_public_key(key)
    return key


def load_private_key(source: str | dict) -> RSAPrivateKey:
    data = _load_key_data(source)
    try:
        key = RSAPrivateKey(
            modulus=int.from_bytes(_decode(data["n"]), "big"),
            private_exponent=int.from_bytes(_decode(data["d"]), "big"),
            key_id=str(data["key_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseValidationError("License private key is malformed.") from exc
    if key.modulus.bit_length() < 2048 or key.private_exponent <= 1 or not key.key_id:
        raise LicenseValidationError("License private key does not meet security requirements.")
    return key


def sign_payload(payload: dict, private_key: RSAPrivateKey) -> str:
    encoded = _encoded_message(canonical_payload(payload), private_key.modulus)
    signature = pow(int.from_bytes(encoded, "big"), private_key.private_exponent,
                    private_key.modulus)
    size = (private_key.modulus.bit_length() + 7) // 8
    return _encode(signature.to_bytes(size, "big"))


def verify_payload(payload: dict, signature: str, public_key: RSAPublicKey) -> bool:
    try:
        signature_bytes = _decode(signature)
        size = (public_key.modulus.bit_length() + 7) // 8
        if len(signature_bytes) != size:
            return False
        signature_value = int.from_bytes(signature_bytes, "big")
        if signature_value >= public_key.modulus:
            return False
        decoded = pow(signature_value, public_key.exponent,
                      public_key.modulus).to_bytes(size, "big")
        expected = _encoded_message(canonical_payload(payload), public_key.modulus)
        return hashlib.sha256(decoded).digest() == hashlib.sha256(expected).digest() \
            and decoded == expected
    except (TypeError, ValueError):
        return False


def public_key_document(private_data: dict) -> dict:
    return {
        "algorithm": "RSA-SHA256-PKCS1v15",
        "n": private_data["n"],
        "e": private_data["e"],
        "key_id": private_data["key_id"],
    }


def _encoded_message(message: bytes, modulus: int) -> bytes:
    size = (modulus.bit_length() + 7) // 8
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(message).digest()
    padding_length = size - len(digest_info) - 3
    if padding_length < 8:
        raise LicenseValidationError("RSA key is too small for SHA-256 signatures.")
    return b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info


def _validate_public_key(key):
    if key.modulus.bit_length() < 2048 or key.exponent < 3 or key.exponent % 2 == 0:
        raise LicenseValidationError("License public key does not meet security requirements.")
    if not key.key_id:
        raise LicenseValidationError("License public key ID is required.")


def _load_key_data(source):
    if isinstance(source, dict):
        return source
    try:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LicenseValidationError("License key file is unavailable or malformed.") from exc


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    text = str(value or "")
    return base64.urlsafe_b64decode(text + ("=" * (-len(text) % 4)))
