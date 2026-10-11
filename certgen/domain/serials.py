"""Human-readable serial numbers and unguessable verification codes."""

import secrets

# Crockford base32 without I, L, O, U: no characters that get misread when a
# serial is typed in from paper.
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SERIAL_PREFIX_LENGTH = 4


def new_serial_prefix() -> str:
    return "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(SERIAL_PREFIX_LENGTH))


def format_serial(year: int, serial_prefix: str, position: int) -> str:
    """BCG-2026-K7Q4-00042: year, the job's prefix, and the 1-based row number."""
    return f"BCG-{year}-{serial_prefix}-{position + 1:05d}"


def new_verification_code() -> str:
    # 16 random bytes = 128 bits: the code is the only secret behind /verify.
    return secrets.token_urlsafe(16)
