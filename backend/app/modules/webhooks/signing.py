"""HMAC-SHA256 signing for outbound webhook payloads.

Each webhook endpoint may have an optional ``secret``. When set, every
outbound delivery includes an ``X-Inventari-Signature-256`` header so
the receiver can verify authenticity — the same pattern used by GitHub
Webhooks and Stripe.

Header format:  ``sha256=<hex-digest>``
"""

import hashlib
import hmac


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Return HMAC-SHA256 signature as ``'sha256=<hex>'``."""
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return f'sha256={mac.hexdigest()}'
