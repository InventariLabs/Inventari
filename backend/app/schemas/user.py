import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.exceptions import ServiceRejectionError
from app.i18n import Language

_PASSWORD_DESCRIPTION = (
    'Password must be at least 8 characters with uppercase, lowercase, and digit'
)

#: bcrypt hashes at most 72 bytes of a password, and since bcrypt 5 it raises
#: instead of truncating anything longer. The ceiling is counted in bytes, not
#: characters: 37 letters with Polish diacritics are already past it.
PASSWORD_MAX_BYTES = 72


def validate_password_byte_ceiling(value: str) -> str:
    """Refuse a password bcrypt cannot hash, in the reader's language.

    The complexity rules below raise static English because pydantic wraps
    them for a programmer; this one names a limit the reader just typed
    against, so it comes from the error catalogue instead.
    ``get_current_lang`` falls back to the default language outside a
    request — the CLI reaches this through ``validate_password_policy``.
    """
    if len(value.encode('utf-8')) > PASSWORD_MAX_BYTES:
        raise ServiceRejectionError('password_too_long', max_bytes=PASSWORD_MAX_BYTES)
    return value


def validate_password_policy(value: str) -> str:
    """Apply the account password policy outside a Pydantic model.

    The CLI creates accounts without going through `UserCreate`, and an
    account it can create but the API would reject is worse than useless —
    it is a login that does not work.
    """
    if len(value) < 8:
        raise ServiceRejectionError('password_too_short')
    return _validate_password_complexity(validate_password_byte_ceiling(value))


def _validate_password_complexity(value: str) -> str:
    if not re.search(r'[a-z]', value):
        raise ServiceRejectionError('password_needs_lowercase')
    if not re.search(r'[A-Z]', value):
        raise ServiceRejectionError('password_needs_uppercase')
    if not re.search(r'\d', value):
        raise ServiceRejectionError('password_needs_digit')
    return value


def _validate_email_loose(value: str) -> str:
    """Minimal email validation that permits intranet/local domains.

    pydantic ``EmailStr`` (email-validator) rejects special-use TLDs such as
    ``.local``, which broke on-prem/intranet logins with a 500 on GET /auth/me.
    We only enforce the basic shape (one ``@``, non-empty local and domain
    parts) so legitimate intranet addresses pass while garbage is rejected.
    """
    if not isinstance(value, str) or value.count('@') != 1:
        raise ServiceRejectionError('invalid_email')
    local, _, domain = value.partition('@')
    if not local.strip() or not domain.strip():
        raise ServiceRejectionError('invalid_email')
    return value.strip()


class UserBase(BaseModel):
    email: str
    full_name: str | None = None
    preferred_language: Language = 'en'

    @field_validator('email')
    @classmethod
    def _email_loose(cls, v: str) -> str:
        return _validate_email_loose(v)


class UserCreate(UserBase):
    password: str = Field(
        min_length=8,
        max_length=128,
        description=_PASSWORD_DESCRIPTION,
    )
    invite_code: str | None = None
    # Overrides the base default so the endpoint can tell "the caller chose
    # English" from "the caller said nothing". A hard 'en' default meant a
    # browser in Polish got a Polish sign-in screen and an English onboarding
    # the moment the account was created.
    preferred_language: Language | None = None  # type: ignore[assignment]

    @field_validator('password')
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_byte_ceiling(_validate_password_complexity(v))

    model_config = ConfigDict(
        json_schema_extra={
            'example': {
                'email': 'user@example.com',
                'password': 'SecurePass123',
                'full_name': 'John Doe',
                'preferred_language': 'en',
            }
        }
    )


class UserUpdate(BaseModel):
    full_name: str | None = None
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description=_PASSWORD_DESCRIPTION,
    )
    #: Required whenever ``password`` is set — a hijacked session must
    #: not be enough to take the account over.
    current_password: str | None = None
    preferred_language: Language | None = None

    @field_validator('password')
    @classmethod
    def password_complexity(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_password_byte_ceiling(_validate_password_complexity(v))


class User(UserBase):
    id: UUID
    role: str | None = 'user'
    is_active: bool
    is_superuser: bool | None = False
    is_blocked: bool = False
    blocked_at: datetime | None = None
    blocking_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    organization_name: str | None = None
    # Filled in by GET /auth/me only — the computed permission set for the
    # caller, so the frontend can gate on something other than role == admin.
    # Other endpoints returning a User leave it empty rather than paying for
    # the role join on every user row they list.
    permissions: list[str] = []
    model_config = ConfigDict(from_attributes=True)


class UserInDB(User):
    hashed_password: str


class Token(BaseModel):
    """Login/refresh response.

    The refresh token is deliberately absent: it lives in the HttpOnly
    ``refresh_token`` cookie only, out of reach of page scripts.
    """

    access_token: str
    token_type: str = 'bearer'


class TokenData(BaseModel):
    user_id: UUID | None = None


class RegistrationRequestBase(BaseModel):
    email: str
    full_name: str | None = None
    preferred_language: Language = 'en'

    @field_validator('email')
    @classmethod
    def _email_loose(cls, v: str) -> str:
        return _validate_email_loose(v)


class RegistrationRequestCreate(RegistrationRequestBase):
    pass


class RegistrationRequest(RegistrationRequestBase):
    id: UUID
    created_at: datetime
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    is_rejected: bool
    approved_by_id: UUID | None = None
    model_config = ConfigDict(from_attributes=True)


class RegistrationComplete(BaseModel):
    token: str
    password: str = Field(
        min_length=8,
        max_length=128,
        description=_PASSWORD_DESCRIPTION,
    )
    full_name: str | None = None
    # None = "the form did not say" — register_complete then falls back to the
    # language captured on the registration request. A literal 'en'
    # default would silently overwrite it.
    preferred_language: Language | None = None

    @field_validator('password')
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_byte_ceiling(_validate_password_complexity(v))
