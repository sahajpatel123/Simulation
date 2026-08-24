import hashlib
import hmac
import re
import secrets
import string
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Matches CR/LF (log-forging line breaks) and other C0 control chars that
# corrupt single-line log records.
_LOG_UNSAFE_RE = re.compile(r"[\x00-\x1f\x7f]+")


def log_safe(value: object) -> str:
    """Make untrusted data safe to interpolate into a log entry.

    Strips CR/LF and control characters so a request-supplied string (an
    Origin header, an error message echoing client input, ...) cannot forge
    additional log lines or spoof earlier entries. Ints and other benign
    values pass through unchanged in content.
    """
    return _LOG_UNSAFE_RE.sub(" ", str(value))


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

# Prefix marking the current (HMAC-keyed) digest generation in the
# ``token_hash`` column; unprefixed rows are legacy bare SHA-256 hex digests.
_API_TOKEN_HASH_V2_PREFIX = "v2:"


def generate_api_token() -> str:
    """Generate a fresh opaque API token (``thecee_`` + 256 bits of entropy)."""
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _api_token_digest_key() -> bytes:
    """Domain-separated HMAC key for API-token digests.

    Derived from ``SECRET_KEY`` through a labelled SHA-256 step so the
    token-digest key and the JWT-signing key are independent streams even
    though they share a root secret. Computed per call (microsecond cost)
    so a rotated ``SECRET_KEY`` takes effect without a process restart.
    """
    return hashlib.sha256(
        b"thecee:api-token-digest:v2:" + settings.SECRET_KEY.encode("utf-8")
    ).digest()


def hash_api_token(token: str) -> str:
    """Return the digest persisted instead of the plaintext token.

    The current generation is a domain-separated HMAC-SHA256 (``v2:``
    prefix): verifying a leaked database row against a guessed token now
    also requires ``SECRET_KEY``, so the hash alone is no longer an
    offline oracle. The token itself carries 256 bits of
    ``secrets.token_urlsafe`` entropy, so this is defence-in-depth rather
    than the primary barrier; human passwords still use bcrypt via
    ``pwd_context``. Rows written before this change hold a bare SHA-256
    hex digest and keep authenticating through ``api_token_hash_candidates``
    until they are revoked or re-issued.
    """
    return (
        _API_TOKEN_HASH_V2_PREFIX
        + hmac.new(_api_token_digest_key(), token.encode("utf-8"), hashlib.sha256).hexdigest()
    )


def api_token_hash_candidates(token: str) -> list[str]:
    """Every persisted digest form that could match ``token``.

    Lookup sites must match against all accepted digest generations so a
    pre-upgrade row keeps working until rotation while newly minted tokens
    always store the strongest current form. Ordered newest-first so fresh
    tokens hit on the first candidate.
    """
    return [
        hash_api_token(token),
        hashlib.sha256(token.encode("utf-8")).hexdigest(),
    ]


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
