"""Time-based one-time passwords (TOTP, RFC 6238), as authenticator apps make them.

The server and the phone share a random secret. Every 30 seconds both work
out the same 6-digit code from the secret and the current time:

    step = seconds since 1970 // 30
    code = last 6 digits of HMAC-SHA1(secret, step), "dynamically truncated"

So the code proves "has the phone that was set up with this secret", and it is
useless a minute later. Google Authenticator, Microsoft Authenticator, Aegis
and others all use SHA-1, 6 digits and 30 seconds, so those are fixed here.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
# Accept the code for the step before and after too: phones' clocks drift,
# and a person needs a few seconds to type it.
DRIFT_STEPS = 1


def new_secret() -> str:
    """20 random bytes (160 bits, the size RFC 4226 recommends) as base32, the
    form authenticator apps take ("JBSWY3DPEHPK3PXP...")."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    # "Dynamic truncation" (RFC 4226, 5.3): the last 4 bits pick where to read 4 bytes.
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def matching_step(secret: str, code: str, *, after_step: int | None = None, now: float | None = None) -> int | None:
    """The time step `code` belongs to, or None if it's wrong.

    `after_step`: the last step already used to sign in. A code from that step
    or earlier is refused, so a code seen over someone's shoulder (or caught
    on the way) can't be used a second time.
    """
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    here = current_step(now)
    for step in range(here - DRIFT_STEPS, here + DRIFT_STEPS + 1):
        # compare_digest: no timing hint about how many digits were right.
        if hmac.compare_digest(code_at(secret, step), code):
            if after_step is not None and step <= after_step:
                return None
            return step
    return None


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    """The otpauth:// link a QR code carries (Google's "Key URI Format")."""
    label = quote(f"{issuer}:{account}")
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"
