"""SMTP config schema used by /api/organizations/my/test-email and stored
under org.settings.smtp.

Explicit validation so junk values are rejected with 422 instead of being saved and silently
failing later.
"""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class SmtpConfig(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    # Absent on configurations saved before the field existed; the service then
    # reads the intent from the port (see ``_encryption_implied_by_port``).
    encryption: Literal['none', 'starttls', 'ssl'] | None = None
    user: str = Field(default='', max_length=255)
    password: str = Field(default='', max_length=1024)
    from_email: EmailStr | None = None
    from_name: str = Field(default='Inventari', max_length=255)


__all__ = ['SmtpConfig']
