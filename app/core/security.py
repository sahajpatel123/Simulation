import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if not any(ch.islower() for ch in password):
        raise ValueError("Password must include a lowercase letter")
    if not any(ch.isupper() for ch in password):
        raise ValueError("Password must include an uppercase letter")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("Password must include a number")
    allowed_punctuation = set(string.punctuation)
    if not any(ch in allowed_punctuation for ch in password):
        raise ValueError("Password must include a special character")
    return password


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"exp": expire, "sub": str(subject), "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token() -> str:
    """Opaque refresh token; validated via refresh_tokens table hash, not JWT."""
    return secrets.token_urlsafe(32)


def decode_token(token: str, token_type: str = "access") -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != token_type:
            return None
        return payload.get("sub")
    except JWTError:
        return None
