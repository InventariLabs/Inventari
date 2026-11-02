from typing import Any

from pydantic import BaseModel

#: A request field and the column it is written to, where the two names
#: differ: a client meets a location, the tables keep their storage spelling.
_COLUMN_FOR_FIELD = {
    'location_id': 'storage_location_id',
    'location_type_id': 'storage_type_id',
}


def keyed_by_column(data: dict[str, Any]) -> dict[str, Any]:
    """*data*, a request's ``model_dump``, keyed by the columns it writes.

    What runs below a write — interceptors, the audit line, the history —
    reads column names, so a request is translated once, where it is dumped.
    """
    return {_COLUMN_FOR_FIELD.get(key, key): value for key, value in data.items()}


#: What a preview cell may hold once pandas has read it.
SheetPreviewValue = str | int | float | None


class SheetAnalysisResponse(BaseModel):
    """What the mapping step is told about an uploaded sheet.

    Headers alone were not enough. The reader chose a mapping without seeing
    a single value, so a sheet with a shifted header row — or one pandas split
    on the wrong delimiter — looked correctly mapped, and the mismatch only
    showed up after the rows had been written.
    """

    headers: list[str]
    preview_rows: list[dict[str, SheetPreviewValue]]
    total_rows: int
    #: Per header, how many of the file's rows carry a non-empty value in
    #: it — counted over the whole sheet, because the preview stops at five
    #: rows and a warning about the data ("not one row carries a code")
    #: must speak about the file, not about the first five rows of it.
    filled_counts: dict[str, int]


class MessageResponse(BaseModel):
    message: str


class InitStatusResponse(BaseModel):
    is_initialized: bool
    #: True on the public demo, where the organization's email settings are
    #: refused and every message is caught in the demo inbox. The screens read
    #: this rather than inferring "demo" from the inbox URL being set: the two
    #: keys are independent, and a screen that guesses is a screen that lies
    #: when only one of them is present.
    is_demo: bool = False
    #: Whether this installation can send mail at all. The request-access page
    #: reads it so it does not promise an e-mail on an install without SMTP.
    email_delivery_configured: bool = False
    #: Set only on a public demo: the URL of the Mailpit inbox where every
    #: message the instance "sends" is caught. The sign-in screen links to it,
    #: so a visitor can read the purchase order or invitation that would have
    #: gone out — and see that nothing leaves the demo.
    demo_inbox_url: str | None = None
    #: Who runs this installation and how to reach them (an email address or
    #: a URL), for the public privacy page. ``None`` when the operator has not
    #: configured them — a self-hosted install names nobody rather than
    #: somebody else.
    operator_name: str | None = None
    operator_contact: str | None = None


class BulkUpdateResponse(BaseModel):
    updated: int


class ImageUploadResponse(BaseModel):
    image_url: str


class LogoUploadResponse(BaseModel):
    """The stored org-scoped path of the uploaded logo.

    Served back to the browser as ``/uploads/{logo_url}``; read server-side
    by the PDF service for embedding.
    """

    logo_url: str


class LabelUnassignResponse(BaseModel):
    message: str


class ModuleToggleResponse(BaseModel):
    success: bool
    enabled_modules: list[str]


class ModuleEnablePreview(BaseModel):
    """What switching a module on would put into motion."""

    resumes: int


class ModuleSettingsResponse(BaseModel):
    settings: dict
    settings_schema: dict | None = None


class ModuleSettingsUpdateResponse(BaseModel):
    status: str


class SkuSchemaResponse(BaseModel):
    sku_schema: dict


class RegistrationRequestResponse(BaseModel):
    message: str


class RegistrationApproveResponse(BaseModel):
    message: str
    registration_token: str
    registration_link: str
    email_sent: bool


class LogoutResponse(BaseModel):
    message: str


class TestEmailResponse(BaseModel):
    message: str


class AttachmentDeleteResponse(BaseModel):
    message: str
