# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| latest 0.x release | ✅ |
| `main` | ✅ |
| older releases | ❌ — upgrade to the latest release |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, please report it privately:

- **Email**: contact@inventari.app *(or open a [GitHub Security Advisory](https://github.com/InventariLabs/Inventari/security/advisories/new))*
- Include a description of the vulnerability and steps to reproduce
- We will respond within 72 hours and keep you updated on the fix timeline

## Responsible Disclosure

We ask that you:
- Give us reasonable time to fix the issue before any public disclosure
- Do not exploit the vulnerability beyond what is necessary to demonstrate it
- Do not access or modify other users' data

We will:
- Acknowledge your report promptly
- Work to fix the issue as quickly as possible
- Credit you in the changelog (unless you prefer to remain anonymous)

## Security Best Practices for Self-Hosters

- **Never** use default passwords from `.env.example` in production
- Generate a strong `SECRET_KEY` and a `FERNET_SALT` with `openssl rand -hex 32` (production refuses to start on a placeholder or a salt shorter than 16 bytes)
- Keep your Docker images up to date
- Run behind a reverse proxy (Caddy or Nginx) with HTTPS
- Use firewall rules to restrict database port access
- Regularly back up your PostgreSQL database

## Known Security Considerations

- The app requires a valid JWT token for API endpoints, **except**:
  - the deliberately unauthenticated attestation flow in the Equipment module (`/public/attestation/{token}`, plus `/confirm` and `/dispute`, registered outside `/api/v1/`). That zero-login flow lets the holder of equipment confirm that they still have it, or report a problem, without an account: access is granted by an unguessable, expiring token that belongs to exactly one attestation response, and the endpoints are rate-limited (30/minute read, 10/minute confirm/dispute);
  - the public invitation lookup `GET /public/invitation/{code}` (30/minute);
  - registration and password reset (`/api/v1/auth/register`, `/registration-request`, `/registration-link/{token}`, `/register-complete`, `/password-reset/request`, `/password-reset/confirm`), rate-limited per endpoint (3/hour for `register`, `registration-request` and the reset request, 5/hour for the reset confirmation, 30/minute for the registration link); `/register-complete`, which needs the unguessable token of an approved registration, has no limit of its own and falls under the global per-client backstop (`RATE_LIMIT_PER_IP`, 200 per minute by default);
  - sign-in itself and its companions (`/api/v1/auth/login`, `/refresh`, `/logout`), the installation-state probe `GET /api/v1/auth/init-status`, and `POST /api/v1/demo/sandbox`, the one-click sign-in of a public demo (answers 404 unless the instance is a demo, rate-limited per address);
  - the health probes `/health` and `/health/ready`, and the two root documents `/` and `/api/`.
- Three other credentials reach otherwise-protected surfaces: **API keys** (`X-API-Key: inv_live_…`, generated in Settings; each carries only the permissions chosen when it was issued, acts for its owner's organization and can be revoked; the older `Authorization: Bearer` form is accepted through 0.11.x), the HttpOnly **refresh cookie** accepted by `/uploads` when a browser loads media directly, and the JWT that the `/ws/notifications` WebSocket takes as a **subprotocol** (`Sec-WebSocket-Protocol: bearer, <token>` — a header, like the token of every other request, so it stays out of access logs; a token in the query string is refused)
- Rate limiting is applied to auth endpoints (login, register, invite)
- Vision AI calls can be routed through OpenRouter, OpenAI-compatible endpoints, Google Gemini, or a local Ollama server (which needs no credentials) — connection credentials are stored **encrypted at rest** in your self-hosted database, per organization (AES-128-CBC via Fernet, keyed from `ENCRYPTION_KEY`, or from `SECRET_KEY` when that is empty, with a per-deployment `FERNET_SALT`; `manage.py secrets reencrypt` moves stored secrets to a new key)
- Debug mode (`DEBUG=true`) exposes performance headers — **never use in production**
