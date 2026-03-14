"""
Security utilities: JWT token creation/verification, password hashing,
API key generation, and field-level encryption.
"""

import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# ---- Password Hashing ----
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---- JWT Tokens ----
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


# ---- API Key Generation ----
API_KEY_PREFIX = "atk_"


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (full_key, key_hash)."""
    raw = secrets.token_urlsafe(32)
    full_key = f"{API_KEY_PREFIX}{raw}"
    key_hash = pwd_context.hash(full_key)
    return full_key, key_hash


def verify_api_key(plain_key: str, key_hash: str) -> bool:
    return pwd_context.verify(plain_key, key_hash)


def get_api_key_prefix(key: str) -> str:
    return key[:12]


# ---- Field Encryption (for provider API keys stored in DB) ----
def _get_fernet() -> Fernet:
    # Fernet requires a 32-byte url-safe base64-encoded key
    import base64
    key_bytes = settings.ENCRYPTION_KEY.encode()[:32].ljust(32, b"\0")
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_value(plain: str) -> bytes:
    return _get_fernet().encrypt(plain.encode())


def decrypt_value(encrypted: bytes) -> str:
    return _get_fernet().decrypt(encrypted).decode()
