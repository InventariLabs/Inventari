from pydantic import BaseModel


class AboutResponse(BaseModel):
    """What the About screen shows: AGPL-3.0 §5(d) notices and §13's source."""

    name: str
    version: str
    license: str
    license_url: str
    source_code_url: str
