"""Non-reversible token fingerprinting shared by session services."""
import hashlib

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
