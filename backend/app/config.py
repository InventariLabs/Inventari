import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import get_logger
from app.core.operator_error import OperatorError

# The upstream repository — the source link of an unmodified installation.
UPSTREAM_SOURCE_CODE_URL = 'https://github.com/InventariLabs/Inventari'

_logger = get_logger(__name__)


def _uploads_path_for_this_host(path: str) -> str:
    """The container's uploads path, moved beside the backend on a host.

    ``/app/uploads`` is where a container mounts its volume. On a host with no
    ``/app`` — a backend started with ``uv run uvicorn`` — that path is
    unwritable and the import of ``app.main`` dies, so it is replaced by the
    directory next to the backend package (``backend/uploads``, which git
    already ignores). Any other path is the operator's and is left alone.
    """
    if path == '/app/uploads' and not Path('/app').is_dir():
        return str(Path(__file__).resolve().parent.parent / 'uploads')
    return path


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = 'postgresql://localhost/inventari'
    PRODUCTS_DATABASE_URL: str | None = None
    # Used only by entrypoint.sh (via the migration_database_url property) and
    # by the db CLI commands. Points straight at Postgres so the migration
    # advisory lock (session-scoped) does not travel through a transaction-mode
    # pooler, which would hand the lock and the unlock to different server
    # connections. Falls back to DATABASE_URL.
    MIGRATION_DATABASE_URL: str | None = None
    # Transaction retry for serialization conflicts and deadlocks (SQLSTATE
    # 40001/40P01) — see app/core/db_retry.py. Total attempts per request
    # (1 = no retry), the backoff/jitter in milliseconds that keep two
    # collided requests from meeting again on the same beat, and the body
    # byte cap above which a request keeps today's behaviour instead of
    # being buffered for a replay.
    DB_RETRY_MAX_ATTEMPTS: int = 3
    DB_RETRY_BACKOFF_MS: int = 10
    DB_RETRY_JITTER_MS: int = 20
    DB_RETRY_MAX_BODY_BYTES: int = 262144

    # Redis
    REDIS_URL: str = 'redis://localhost:6379'
    # Optional dedicated instance for eviction-critical keys (token
    # blacklist, rate limiter) with a noeviction policy. Falls back to
    # REDIS_URL when unset (dev/single-instance deployments).
    REDIS_CRITICAL_URL: str | None = None
    REDIS_STREAM_NAME: str = 'inventari_stream'
    REDIS_TASKS_STREAM_NAME: str = 'inventari_tasks'
    # Stream hygiene: approximate XADD MAXLEN caps unbounded growth;
    # pending entries idle longer than CLAIM_IDLE_MS are reclaimed by the
    # periodic reaper (XAUTOCLAIM).
    EVENT_STREAM_MAXLEN: int = 100000
    TASK_STREAM_MAXLEN: int = 10000
    STREAM_CLAIM_IDLE_MS: int = 60000

    # JWT
    SECRET_KEY: str = ''
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Encryption — per-deployment salt for Fernet key derivation.
    # REQUIRED in production (>=16 bytes). If unset, a random one is
    # generated for the session (dev/test only — secrets won't survive
    # a restart). See crypto_service._get_fernet.
    FERNET_SALT: str = ''
    # The key organization secrets are encrypted with. Empty means "use
    # SECRET_KEY", which is what every install did before this existed — see
    # crypto_service._get_fernet for why the two jobs are worth separating.
    ENCRYPTION_KEY: str = ''
    # The key a rotation moves away from: still read, never written, until
    # `manage.py secrets reencrypt --apply` has rewritten every stored secret
    # under the current one. Empty outside a rotation.
    PREVIOUS_ENCRYPTION_KEY: str = ''
    # Read only so the startup check below can refuse the example
    # placeholder: the backend connects through DATABASE_URL, but the dev
    # stack passes DB_PASSWORD and a host run reads it from the root .env.
    DB_PASSWORD: str = ''
    PRODUCTS_DB_PASSWORD: str = ''

    # The model an organization gets when it has bound none (the env fallback
    # in core/llm/registry.py). LLM_PROVIDER is any provider the AI
    # Connections screen offers that speaks an LLM protocol; LLM_API_KEY is
    # its key. OPENROUTER_API_KEY is the name this setting had before the
    # provider became a choice: still read when LLM_API_KEY is empty, so an
    # existing .env keeps working (see _llm_key_has_one_name).
    # LLM_CAPABILITIES says what the model can do, comma-separated: text,
    # vision. Empty is text,vision for openrouter, as before it existed, and
    # text alone for any other provider. Checked at start-up below.
    LLM_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    LLM_PROVIDER: str = 'openrouter'
    LLM_API_BASE_URL: str = 'https://openrouter.ai/api/v1'
    LLM_MODEL: str | None = None
    LLM_CAPABILITIES: str = ''

    # Uploads
    # Hard ceiling enforced before the body is buffered. Per-endpoint limits
    # (attachments 10MB, equipment 20MB, imports 50MB, vision images 10MB)
    # still apply on top; this one exists so a backend running without the
    # reverse proxy — which caps bodies in the Caddyfile — is not a free
    # memory sink.
    MAX_REQUEST_BODY_SIZE: int = 53477376  # 51MB: 50MB payload + multipart overhead

    # File Storage Backend
    FILE_STORAGE_BACKEND: str = 'local'
    FILE_STORAGE_LOCAL_PATH: str = Field('/app/uploads', validate_default=True)
    FILE_STORAGE_S3_BUCKET: str | None = None
    FILE_STORAGE_S3_ACCESS_KEY: str | None = None
    FILE_STORAGE_S3_SECRET_KEY: str | None = None
    FILE_STORAGE_S3_REGION: str = 'us-east-1'
    FILE_STORAGE_S3_ENDPOINT_URL: str | None = None

    # CORS
    FRONTEND_URL: str = 'http://localhost:5173'

    # Emails (SMTP) - optional, can be set via UI
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    # 'none' | 'starttls' | 'ssl'. Left unset, the port decides the way it used
    # to (587 → STARTTLS, 465 → SSL, anything else → plaintext) so existing
    # installations keep working; set it to stop the port from voting.
    SMTP_ENCRYPTION: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: str = 'noreply@inventari.app'
    EMAILS_FROM_NAME: str = 'Inventari'
    # The public URL of the demo's email inbox, when this instance is the
    # public demo. The demo sends no real mail — Mailpit beside it catches
    # everything — and the sign-in screen tells visitors where to look. Empty
    # everywhere else: a normal install sends real mail and has no inbox to
    # point at.
    DEMO_INBOX_URL: str = ''
    # Whether this instance is the public demo. Declared, never inferred: a
    # database named inventari_demo on somebody's laptop is still their
    # laptop. On a demo the organization's own SMTP settings cannot be saved
    # and are never used — every message goes through the system SMTP, which
    # `docker-compose.demo.yml` pins to the Mailpit beside the stack. Read
    # here rather than by scattered `os.getenv` calls, so the backend and the
    # mail-sending processes answer from one field.
    INVENTARI_DEMO: bool = False
    # What a demo lets visitors upload between two resets (megabytes): one
    # file, and everything the instance holds in file storage. Read only when
    # INVENTARI_DEMO is on; a normal install is bounded by the per-endpoint
    # limits alone.
    DEMO_UPLOAD_FILE_MB: float = 2
    DEMO_UPLOAD_TOTAL_MB: float = 200
    # On a demo every visitor gets an organization of their own, taken from a
    # pool the demo-reset service keeps seeded (docs/DEMO.md). These bound what
    # the clicks can cost the instance: how many sandboxes wait seeded, how
    # many are handed out between two nightly resets, and how often one
    # address may ask for one.
    DEMO_SANDBOX_POOL_SIZE: int = 3
    DEMO_SANDBOX_DAILY_CAP: int = 100
    DEMO_SANDBOX_RATE_LIMIT: str = '10/hour'
    # AI requests each demo organization may make between two resets (the
    # count is monthly, the organizations live a night). The demo serves AI
    # from the environment's key, which nothing on screen can bound; the
    # spending cap at the provider is the other half (docs/DEMO.md).
    DEMO_AI_REQUESTS_MONTHLY: int = 20

    # Who runs this installation and how to reach them, as the public privacy
    # page states it: a name, and an email address or a URL. Configuration,
    # never code — the page is the same for every install, and a name written
    # into it would make every self-hosted copy claim to be somebody else's.
    # Empty means unset, and the page says so instead of naming anyone.
    OPERATOR_NAME: str = ''
    OPERATOR_CONTACT: str = ''

    # App
    DEBUG: bool = False
    TESTING: bool = False
    SQL_ECHO: bool = False
    # Lets a browser cookie turn any API call into a failure, so the error state
    # of a screen can be reached on purpose instead of waited for. Registered
    # only when DEBUG is also on — see app/main.py and core/qa_fault_injection.py.
    QA_FAULT_INJECTION: bool = False
    # Disables the global rate limiter (core/limiter.py) so a load test measures
    # the app, not the limiter. Refused outside DEBUG/TESTING unless the operator
    # also sets LOAD_TESTING_ACK_UNSAFE — see the validation below.
    LOAD_TESTING: bool = False
    LOAD_TESTING_ACK_UNSAFE: bool = False
    # See check_testing_mode_is_deliberate: TESTING with DEBUG off is refused
    # unless the operator says the combination is meant.
    TESTING_ACK_UNSAFE: bool = False
    STRICT_STARTUP: bool = False

    # Logging
    LOG_LEVEL: str = 'INFO'
    LOG_DIR: str = '/app/logs'

    # Rate limiting (slowapi limits syntax). Global backstop applied to every
    # request bucket — see `app.core.limiter` for how a bucket is derived
    # (API key > JWT user > client IP). Endpoints needing a tighter or looser
    # value carry their own `@limiter.limit`.
    RATE_LIMIT_PER_IP: str = '200 per minute'

    # Login brute-force guard. Stays tight in production; the local dev stack
    # overrides it in docker-compose.yml because E2E suites log in per spec
    # file and would otherwise stall on 429s.
    RATE_LIMIT_LOGIN: str = '5 per minute'

    # Token refresh guard. Every SPA boot calls /auth/refresh, so E2E suites
    # burn through the default quickly (the bucket falls back to client IP,
    # which every spec in a run shares). Same dev-stack override as login.
    RATE_LIMIT_REFRESH: str = '20 per minute'

    # Webhooks
    WEBHOOKS_ALLOW_PRIVATE_NETWORKS: bool = False

    # LLM outbound requests (self-hosted Ollama/LM Studio on a private
    # address needs this on; SaaS deployments leave it off).
    LLM_ALLOW_PRIVATE_NETWORKS: bool = False

    # How long one model call may take. Two defaults, because the two kinds
    # of provider are not close: a cloud endpoint that has not answered in a
    # minute is not going to, while a model running on the user's own card
    # is measured in minutes — a small vision model on a consumer graphics
    # card can take just over a minute to read one photograph, and a
    # hard-coded minute turned that into "we could not reach the provider".
    # Which of the two applies is decided by the connection's provider (see
    # app.core.llm.timeouts).
    LLM_REQUEST_TIMEOUT_SECONDS: float = 60.0
    LLM_LOCAL_REQUEST_TIMEOUT_SECONDS: float = 300.0

    # Cloud/SaaS settings
    SUPERUSER_EMAIL: str | None = None

    # Where this instance's source code can be had, shown on the About
    # screen. AGPL-3.0 §13 obliges whoever serves a modified version over a
    # network to offer its users that version's source: a fork points this
    # at its own repository.
    SOURCE_CODE_URL: str = UPSTREAM_SOURCE_CODE_URL

    # Community module signing: trusted Ed25519 public keys the
    # installer verifies module packages against. Entries separated by
    # commas or newlines, each ``key_id=<base64 public key>`` or a bare
    # base64 key. Empty means nothing is trusted: every package is
    # unsigned, and installing one needs the explicit --allow-unsigned.
    MODULE_SIGNING_PUBLIC_KEYS: str = ''

    model_config = SettingsConfigDict(
        env_file=('.env', '../.env'),
        env_file_encoding='utf-8',
        case_sensitive=False,
        # The root .env is Compose's file too: it carries DB_USER, DB_PASSWORD,
        # PRODUCTS_DB_* and printer keys that only Compose reads. pydantic
        # rejects a dotenv key no field names, so on the host the backend died
        # before serving a request. Environment variables never had that check.
        extra='ignore',
    )

    @model_validator(mode='after')
    def _llm_key_has_one_name(self) -> 'Settings':
        # Everything reads LLM_API_KEY; the old name only fills it in.
        # The warning below prints once per process, so one start shows it
        # several times (entrypoint steps, reloader, each worker). That is the
        # accepted shape: the other settings warnings here repeat the same way,
        # and a once-per-host guard would need shared state for a line that
        # only an operator with both names set ever sees.
        old = self.OPENROUTER_API_KEY
        if old and not self.LLM_API_KEY:
            self.LLM_API_KEY = old
        elif old and old != self.LLM_API_KEY:
            _logger.warning(
                'Both LLM_API_KEY and OPENROUTER_API_KEY are set and differ: '
                'using LLM_API_KEY. Remove OPENROUTER_API_KEY, the name this '
                'setting had before.'
            )
        return self

    @field_validator('FILE_STORAGE_LOCAL_PATH')
    @classmethod
    def _uploads_path_exists_on_this_host(cls, value: str) -> str:
        return _uploads_path_for_this_host(value)

    @property
    def migration_database_url(self) -> str:
        """URL migrations and the advisory lock use — direct, never pooled."""
        return self.MIGRATION_DATABASE_URL or self.DATABASE_URL


settings = Settings()

# Post-initialization validation
if not settings.DEBUG and 'user:password' in settings.DATABASE_URL:
    raise OperatorError(
        'DATABASE_URL contains default credentials. Set a proper DATABASE_URL for production.'
    )

_WEAK_SECRET_KEYS = frozenset(
    {
        'your-super-secret-key-change-in-production',
        'changeme',
        'secret',
        'insecure',
        'super-secret',
        'my-secret-key',
    }
)

if not settings.SECRET_KEY:
    if settings.DEBUG:
        import secrets

        settings.SECRET_KEY = secrets.token_urlsafe(32)
        _logger.warning(
            'SECRET_KEY not set. Generated a random key for this session. Set SECRET_KEY env variable for production.'
        )
    else:
        raise OperatorError(
            'SECRET_KEY must be set in environment variables for production!'
        )
elif settings.SECRET_KEY in _WEAK_SECRET_KEYS:
    import os

    _is_dev = (
        settings.DEBUG or settings.TESTING or os.getenv('TESTING', '').lower() == 'true'
    )
    if not _is_dev:
        raise OperatorError(
            'SECRET_KEY is a known weak value. '
            'Generate a proper one: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    _logger.warning(
        'SECRET_KEY is a known weak value. This is acceptable in '
        'DEBUG/TESTING mode but must be changed for production.'
    )

# Enforce minimum key length for HS256 (NIST SP 800-107: >= 256-bit / 32 bytes).
# The blocklist above only rejects known-weak literals; a short but non-blocklisted
# key (e.g. 'a') would otherwise pass silently in production.
_key_bytes = len(settings.SECRET_KEY.encode('utf-8'))
if _key_bytes < 32:
    _is_dev = (
        settings.DEBUG or settings.TESTING or os.getenv('TESTING', '').lower() == 'true'
    )
    _msg = (
        f'SECRET_KEY must be at least 32 bytes for HS256 security (current: {_key_bytes} bytes). '
        'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )
    if not _is_dev:
        raise OperatorError(_msg)
    _logger.warning(_msg)


def check_testing_mode_is_deliberate(
    *, debug: bool, testing: bool, ack_unsafe: bool
) -> None:
    """Refuse ``TESTING=true`` on a deployment that is otherwise production.

    TESTING is not a quieter DEBUG. It switches on the password-reset
    ``_dev_token`` response, which hands a valid reset token back to anyone
    who names an address that exists; it makes the token blacklist fail open,
    so a Redis outage stops revoking anything; and it accepts a SECRET_KEY
    from the known-weak list. Each of those is deliberate for a test run and
    indefensible for an install serving people, and with ``DEBUG=false`` the
    deployment looks production-shaped from every other angle — nothing on a
    dashboard says the three are off.

    Acknowledged rather than forbidden, following ``LOAD_TESTING_ACK_UNSAFE``:
    an E2E stack that wants production-ish settings with the test hooks on is
    a real case, and it can say so.
    """
    if not testing or debug or ack_unsafe:
        return
    raise OperatorError(
        'TESTING=true with DEBUG=false. TESTING enables the password-reset '
        'dev-token response, makes the token blacklist fail open and accepts a '
        'known-weak SECRET_KEY — none of which belong on a deployment that '
        'looks like production from every other angle. Refusing to start: set '
        'TESTING=false for a normal deployment, or TESTING_ACK_UNSAFE=true if '
        'this really is a test stack.'
    )


check_testing_mode_is_deliberate(
    debug=settings.DEBUG,
    testing=settings.TESTING or os.getenv('TESTING', '').lower() == 'true',
    ack_unsafe=settings.TESTING_ACK_UNSAFE,
)

_OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
_LLM_ENV_CAPABILITIES = ('text', 'vision')


def llm_env_capabilities(provider: str, capabilities: str) -> frozenset[str]:
    """What the environment's model is declared to do (``LLM_CAPABILITIES``).

    The fallback once claimed for its connection whatever the asking purpose
    needed, so a text-only model was handed photographs and failed inside the
    call. A declaration is what the resolver refuses a purpose against, before
    any call is made.
    """
    declared = frozenset(c.strip() for c in capabilities.split(',') if c.strip())
    if not declared:
        return frozenset(
            _LLM_ENV_CAPABILITIES if provider == 'openrouter' else ('text',)
        )
    unknown = declared.difference(_LLM_ENV_CAPABILITIES)
    if unknown:
        raise OperatorError(
            f'LLM_CAPABILITIES names {", ".join(sorted(unknown))}, which no '
            f'model is asked for. Allowed: {", ".join(_LLM_ENV_CAPABILITIES)}.'
        )
    return declared


def check_llm_environment(
    *, provider: str, api_key: str | None, base_url: str, capabilities: str
) -> None:
    """Refuse an environment model the fallback could not call as written.

    The env fallback is the one key path that reaches an organization nobody
    configured — a fresh install, or a demo rebuilt every night — so a mistake
    here shows as AI missing everywhere, with nothing naming the variable.
    """
    from app.core.llm.enums import LlmProvider, protocol_for

    allowed = sorted(p.value for p in LlmProvider if protocol_for(p.value))
    if provider not in allowed:
        raise OperatorError(
            f'LLM_PROVIDER={provider!r} is not a provider this server can call '
            f'a model through. Allowed: {", ".join(allowed)}.'
        )
    llm_env_capabilities(provider, capabilities)
    if not api_key:
        return
    base = base_url.strip().rstrip('/')
    if not base:
        raise OperatorError(
            'LLM_API_KEY is set but LLM_API_BASE_URL is empty: set it '
            f'to the endpoint of the {provider} API.'
        )
    if provider != 'openrouter' and base == _OPENROUTER_BASE_URL:
        raise OperatorError(
            f'LLM_PROVIDER={provider} but LLM_API_BASE_URL is still the '
            'OpenRouter address, so the key would be sent to OpenRouter. Set '
            f'LLM_API_BASE_URL to the {provider} endpoint (.env.example has '
            'examples).'
        )


check_llm_environment(
    provider=settings.LLM_PROVIDER,
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_API_BASE_URL,
    capabilities=settings.LLM_CAPABILITIES,
)

# Production startup validation
_is_prod = not settings.DEBUG and not settings.TESTING

# LOAD_TESTING switches the global rate limiter off (core/limiter.py). Left on in
# a real deployment it removes brute-force protection from every endpoint without
# a single log line, so refuse to start rather than serve traffic unprotected.
# The one legitimate prod-like use is the load-test stack
# (docker-compose.loadtest-backend.yml), which opts in explicitly.
if settings.LOAD_TESTING and _is_prod and not settings.LOAD_TESTING_ACK_UNSAFE:
    raise OperatorError(
        'LOAD_TESTING=true disables the global rate limiter, and DEBUG/TESTING are off. '
        'Refusing to start: this would run production traffic with no brute-force protection. '
        'Set LOAD_TESTING=false for a normal deployment, or — if this really is a load-test '
        'run — set LOAD_TESTING_ACK_UNSAFE=true to acknowledge the limiter stays off.'
    )


def frontend_url_is_deployable(url: str) -> bool:
    """False for a FRONTEND_URL that only makes sense on a developer's machine.

    Every invitation, registration and password-reset mail is built from this
    value. Left at its default in production it does not fail, it *sends* —
    links to localhost, to people who cannot open them, and nothing in the
    logs says why the invitations stopped working. It sat outside the
    production checklist next to DATABASE_URL and SECRET_KEY, which is the
    company it belongs in.
    """
    if not url:
        return False
    host = urlparse(url).hostname or ''
    return host.lower() not in {'localhost', '127.0.0.1', '::1', '0.0.0.0'}


def warn_if_frontend_url_is_local() -> bool:
    """Log a warning when a production server builds its links to localhost.

    Called once from the server's startup, not when this module is imported:
    every ``manage.py`` command and lint run imports the settings, and on a
    development stack that runs with DEBUG=false (the value the shipped
    .env.example carries) the line came out at the head of each of them,
    where it said nothing anyone could act on. The server's log is where an
    operator looks when the invitations stop arriving.

    Returns whether it warned, so a test can assert on the decision rather
    than on the log line.
    """
    if settings.DEBUG or settings.TESTING:
        return False
    if frontend_url_is_deployable(settings.FRONTEND_URL):
        return False
    _logger.warning(
        'FRONTEND_URL is %s — every invitation, registration and '
        'password-reset link is built from it, so on a real deployment '
        'those mails go out pointing at a machine the recipient does not '
        'have. Set FRONTEND_URL to the address people actually use.',
        settings.FRONTEND_URL or '(empty)',
    )
    return True


if _is_prod:
    _required = {
        'DATABASE_URL': settings.DATABASE_URL,
        'REDIS_URL': settings.REDIS_URL,
        'SECRET_KEY': settings.SECRET_KEY,
    }
    _missing = [
        k
        for k, v in _required.items()
        if not v or v.startswith('postgresql://localhost')
    ]
    if _missing:
        raise OperatorError(
            f'Missing or default production values for: {", ".join(_missing)}. '
            'Set them in environment variables before starting in production mode.'
        )

#: The marker every placeholder in the shipped example files carries
#: (.env.example, backend/.env.example). Matched anywhere in a value, so a
#: placeholder password inside a copied DATABASE_URL is caught too.
_PLACEHOLDER_MARKERS = ('change-me', 'change_me')


def placeholder_settings(values: dict[str, object]) -> list[str]:
    """Names of the settings whose value is still an example placeholder."""
    return sorted(
        name
        for name, value in values.items()
        if isinstance(value, str)
        and any(marker in value.lower() for marker in _PLACEHOLDER_MARKERS)
    )


_placeholders = placeholder_settings(settings.model_dump())
if _is_prod and _placeholders:
    raise OperatorError(
        f'{", ".join(_placeholders)} still carry the placeholder from the '
        'example configuration file. Replace each with a value of your own '
        '(secrets: openssl rand -hex 32) before starting with DEBUG off.'
    )

# FERNET_SALT — per-deployment salt for Fernet key derivation.
# Replaces the hardcoded b'inventari-fernet-salt' shared across deployments.
# In production: must be set to a per-deployment random value (>=16 bytes).
# In dev/test: auto-generate a random one so the session works without config.
# The dev value below is long enough to clear the length check, so a
# copied-over .env would satisfy production without being per-deployment —
# the same reason SECRET_KEY carries a blocklist.
_WEAK_FERNET_SALTS = frozenset(
    {
        'dev-fernet-salt-please-rotate-1234567890abcdef',
        'change-me-generate-with-openssl-rand-hex-32',
        'inventari-fernet-salt',
        'changeme',
    }
)

_fernet_salt_bytes = len(settings.FERNET_SALT.encode('utf-8'))
if _is_prod and _fernet_salt_bytes < 16:
    raise OperatorError(
        'FERNET_SALT must be set to a per-deployment random value (>=16 bytes) '
        'in production. Generate with: '
        'python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )
if _is_prod and settings.FERNET_SALT in _WEAK_FERNET_SALTS:
    raise OperatorError(
        'FERNET_SALT is a known example value shipped with the project. '
        'Generate a per-deployment one: '
        'python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )
if not settings.FERNET_SALT and not _is_prod:
    import secrets

    settings.FERNET_SALT = secrets.token_urlsafe(32)
    _logger.warning(
        'FERNET_SALT not set. Generated a random salt for this session. '
        'Set FERNET_SALT env variable for production.'
    )
