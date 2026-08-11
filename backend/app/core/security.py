import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta

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


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"exp": expire, "sub": str(subject), "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token() -> str:
    """Opaque refresh token; validated via refresh_tokens table hash, not JWT."""
    return secrets.token_urlsafe(32)


# Personal API tokens (long-lived, revocable bearer credentials for
# programmatic access). Plaintext tokens are prefixed so they are instantly
# recognisable in logs / shell history, while only their SHA-256 hash is ever
# persisted — a leaked database row cannot be replayed.
API_TOKEN_PREFIX: str = "thecee_"
API_TOKEN_DEFAULT_DAYS: int = 90
API_TOKEN_MIN_DAYS: int = 1
API_TOKEN_MAX_DAYS: int = 365


def generate_api_token() -> str:
    """Generate a fresh opaque API token (``thecee_`` + 256 bits of entropy)."""
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_token(token: str) -> str:
    """Return the SHA-256 hex digest persisted instead of the plaintext token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def api_token_expiry(expires_in_days: int | None = None) -> datetime:
    """Compute the UTC expiry for a new token, clamped to the supported range.

    ``None`` (or an out-of-range value) falls back to the 90-day default so a
    caller can never accidentally mint a permanent token through bad input.
    """
    if expires_in_days is None:
        days = API_TOKEN_DEFAULT_DAYS
    else:
        days = max(API_TOKEN_MIN_DAYS, min(API_TOKEN_MAX_DAYS, int(expires_in_days)))
    return datetime.now(UTC) + timedelta(days=days)


def api_token_is_expired(
    expires_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return whether a token has passed its expiry, tolerating naive datetimes.

    ``None`` means the token never expires. Naive timestamps (e.g. SQLite
    round-trips) are interpreted as UTC so the check is deterministic across
    deployments.
    """
    if expires_at is None:
        return False
    reference = now if now is not None else datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return expires_at <= reference


def decode_token(token: str, token_type: str = "access") -> str | None:
    """Decode and validate a JWT, returning the subject on success.

    Pins the allowed algorithm to ``settings.ALGORITHM`` to block the
    classic ``alg=none`` / HS-vs-RS confusion attacks, and explicitly
    requires ``exp``, ``sub`` and ``type`` so a token missing any of
    those claims fails closed rather than silently bypassing checks.

    python-jose uses ``require_<claim>`` keys (not a ``require`` array)
    to gate claim presence — see ``jose.jwt._validate_claims``.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={
                "require_exp": True,
                "require_sub": True,
                "require_type": True,
                "verify_exp": True,
            },
        )
    except JWTError:
        return None
    if payload.get("type") != token_type:
        return None
    return payload.get("sub")
