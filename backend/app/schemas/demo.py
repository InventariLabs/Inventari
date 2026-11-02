from pydantic import BaseModel

from app.i18n import Language


class DemoSandboxRequest(BaseModel):
    """Ask for a demo sandbox: your own again, or with ``fresh`` a new one.

    ``preferred_language`` is the language the visitor was reading in; a new
    sandbox's account takes it, so signing in does not switch the interface.
    """

    fresh: bool = False
    preferred_language: Language | None = None
