"""Password hashing and role permissions. No third-party crypto: stdlib scrypt."""
import hashlib
import hmac
import os

MIN_PASSWORD_LEN = 10
MAX_FAILED = 5
LOCK_MINUTES = 10

ROLES = ["admin", "assistant", "frontdesk"]

# Which role may open which page. Least privilege: front desk never sees clinical results.
PAGE_ACCESS = {
    "Dashboard": {"admin", "assistant", "frontdesk"},
    "Patients": {"admin", "assistant", "frontdesk"},
    "Appointments": {"admin", "assistant", "frontdesk"},
    "Treatment Plans": {"admin", "assistant"},
    "Diagnostic Orders": {"admin", "assistant"},
    "Billing": {"admin", "frontdesk"},
    "Users & Audit": {"admin"},
}


def pages_for(role: str) -> list[str]:
    return [p for p, roles in PAGE_ACCESS.items() if role in roles]


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """Return a message if the password is too weak, else None."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Use at least {MIN_PASSWORD_LEN} characters."
    if password.isalpha() or password.isdigit():
        return "Mix letters with numbers or symbols."
    return None
