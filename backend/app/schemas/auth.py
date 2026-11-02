"""Response schemas for the authentication endpoints."""

from pydantic import BaseModel


class PasswordResetRequestOut(BaseModel):
    """What the reset-request endpoint can say without naming the account.

    ``email_delivery_configured`` describes the installation, not the address,
    so it leaks nothing about who has an account here — and it is the
    difference between "check your inbox" and a screen that waits for a letter
    nobody will send.
    """

    status: str
    email_delivery_configured: bool
