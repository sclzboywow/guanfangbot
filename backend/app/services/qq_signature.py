"""QQ Bot webhook Ed25519 signature helpers (official algorithm)."""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SEED_SIZE = 32


def seed_from_secret(secret: str) -> bytes:
    seed = secret
    while len(seed) < SEED_SIZE:
        seed *= 2
    return seed[:SEED_SIZE].encode("utf-8")


def private_key_from_secret(secret: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(seed_from_secret(secret))


def public_key_from_secret(secret: str) -> Ed25519PublicKey:
    return private_key_from_secret(secret).public_key()


def sign_validation(secret: str, event_ts: str, plain_token: str) -> str:
    """Sign op=13 callback validation payload: event_ts + plain_token."""
    message = f"{event_ts}{plain_token}".encode("utf-8")
    return private_key_from_secret(secret).sign(message).hex()


def verify_request_signature(secret: str, timestamp: str, body: bytes, signature_hex: str) -> bool:
    """Verify X-Signature-Ed25519 over timestamp + raw body."""
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    if len(signature) != 64:
        return False
    message = timestamp.encode("utf-8") + body
    try:
        public_key_from_secret(secret).verify(signature, message)
        return True
    except InvalidSignature:
        return False
