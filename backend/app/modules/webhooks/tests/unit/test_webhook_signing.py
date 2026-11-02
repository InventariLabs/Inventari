"""Unit tests for webhook HMAC-SHA256 signing helpers."""

from app.modules.webhooks.signing import compute_signature


class TestComputeSignature:
    def test_returns_sha256_prefix(self) -> None:
        sig = compute_signature(b'payload', 'secret')
        assert sig.startswith('sha256=')

    def test_deterministic_for_same_inputs(self) -> None:
        sig1 = compute_signature(b'hello world', 'mysecret')
        sig2 = compute_signature(b'hello world', 'mysecret')
        assert sig1 == sig2

    def test_different_payloads_produce_different_sigs(self) -> None:
        sig1 = compute_signature(b'payload1', 'secret')
        sig2 = compute_signature(b'payload2', 'secret')
        assert sig1 != sig2

    def test_different_secrets_produce_different_sigs(self) -> None:
        sig1 = compute_signature(b'payload', 'secret1')
        sig2 = compute_signature(b'payload', 'secret2')
        assert sig1 != sig2

    def test_hex_digest_format(self) -> None:
        sig = compute_signature(b'data', 'key')
        hex_part = sig[len('sha256=') :]
        assert len(hex_part) == 64
        assert all(c in '0123456789abcdef' for c in hex_part)
