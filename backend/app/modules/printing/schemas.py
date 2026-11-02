"""Request and response shapes of the print queue."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

JobStatus = Literal['queued', 'printing', 'printed', 'failed']

#: The printing protocol this server speaks. The agent announces the protocol
#: it speaks and the server refuses one outside
#: ``PROTOCOL_MIN_VERSION``–``PROTOCOL_VERSION``: an agent runs on a machine
#: nobody here controls, and a contract that cannot be refused is a contract
#: nobody can change. Raise ``PROTOCOL_VERSION`` by one when a change would
#: break an agent, and leave ``PROTOCOL_MIN_VERSION`` where it is while the
#: older agents in the field still work under the new code.
PROTOCOL_VERSION = 1
PROTOCOL_MIN_VERSION = 1


class PrintAgentRegister(BaseModel):
    """What an agent says about its printer when it starts.

    An agent from before the label size moved to the job also sends
    ``media``, ``width_mm`` and ``height_mm``; they are ignored, not refused.
    ``agent_version`` and ``protocol_version`` are the opposite: an agent that
    names no protocol is refused, because the server cannot tell what it
    speaks and so cannot tell it from an agent it would refuse.
    """

    name: str = Field(..., min_length=1, max_length=100)
    printer_type: str = Field(..., min_length=1, max_length=50)
    #: The agent's own release, only recorded: which build stands next to
    #: this printer.
    agent_version: str | None = Field(None, min_length=1, max_length=50)
    #: The printing protocol the agent speaks.
    protocol_version: int | None = Field(None, ge=1)


class PrintAgentResponse(BaseModel):
    model_config = {'from_attributes': True}

    id: UUID
    name: str
    printer_type: str
    last_seen_at: datetime
    #: Asked for work within the last ``ONLINE_SECONDS``.
    online: bool = False
    #: What the agent said about itself at registration, kept as recorded.
    agent_version: str | None = None
    protocol_version: int | None = None
    #: The protocol this server speaks. Every answer carries it, so an agent
    #: reading its own registration is told where the server stands — an old
    #: server's answer simply has not heard of this field.
    server_protocol_version: int = PROTOCOL_VERSION


class PrintJobCreate(BaseModel):
    """Labels to print: pool labels by id or short code, storage locations,
    or products' barcode labels.

    ``agent_id`` may be left out while the organization has one printer.
    """

    agent_id: UUID | None = None
    label_ids: list[UUID] = Field(default_factory=list, max_length=200)
    short_codes: list[str] = Field(default_factory=list, max_length=200)
    location_ids: list[UUID] = Field(default_factory=list, max_length=200)
    item_ids: list[UUID] = Field(default_factory=list, max_length=200)
    #: A product label's lot and expiry line, printed when the record has them.
    details: bool = True
    #: The same options the label download offers, so a strip sent to the
    #: printer matches the file: one caption for every label instead of each
    #: label's own, the code alone, and several copies of each label.
    caption: str | None = Field(None, max_length=200)
    qr_only: bool = False
    #: The short code printed small under the QR, as the download offers it.
    show_code: bool = False
    copies: int = Field(1, ge=1, le=20)
    #: The size of every label in the job: the preview's, so the printer
    #: gets the label the person looked at, not a size of its own. The bounds
    #: are the label export's.
    width_mm: float = Field(50.0, ge=10.0, le=300.0)
    height_mm: float = Field(24.0, ge=5.0, le=300.0)
    #: Storage locations as shelf labels: the code in Code 128 for a 1D
    #: scanner, instead of the QR label.
    bars: bool = False
    #: With ``bars``: a QR beside the bars as well.
    qr: bool = False


class PrintJobResponse(BaseModel):
    model_config = {'from_attributes': True}

    id: UUID
    agent_id: UUID
    status: JobStatus
    #: How many labels the job prints.
    count: int
    #: The first few codes, so a list of jobs says what each one was.
    short_codes: list[str]
    width_mm: float
    height_mm: float
    attempts: int
    error: str | None
    #: The share of its size the agent printed the labels at, when it had to
    #: shrink them to fit its printer; absent when they printed at their size.
    scale: float | None = None
    created_at: datetime
    finished_at: datetime | None


class PrintJobClaim(BaseModel):
    """A job handed to an agent: print it before the lease runs out."""

    id: UUID
    count: int
    #: The labels' size, so the agent can tell how much of it its printer
    #: can hold.
    width_mm: float
    height_mm: float
    lease_until: datetime
    attempt: int = Field(
        description='Which claim of the job this is; the report carries it back.'
    )


class PrintJobReport(BaseModel):
    agent_id: UUID
    attempt: int = Field(
        ge=1, description='The attempt the claim named; an older claim is refused.'
    )
    printed: bool
    error: str | None = Field(None, max_length=2000)
    #: Up to 1 inclusive: the report comes after the labels are on paper, and
    #: a refused one leaves the job to be printed again. A scale that reads
    #: as 100% is recorded as printed at its size.
    scale: float | None = Field(
        None,
        gt=0.0,
        le=1.0,
        description=(
            'The share of their size the labels were printed at, when the '
            'printer could not hold them whole; left out when it could.'
        ),
    )


class ProductLabelExport(BaseModel):
    """Products whose barcode labels to draw, and how: the preview and download."""

    item_ids: list[UUID] = Field(..., min_length=1, max_length=200)
    width_mm: float = Field(50.0, ge=10.0, le=300.0)
    height_mm: float = Field(24.0, ge=5.0, le=300.0)
    copies: int = Field(1, ge=1, le=20)
    #: The lot and expiry line, printed when the record has them.
    details: bool = True


class LocationLabelExport(BaseModel):
    """Locations whose shelf labels to draw, and how: the preview and download."""

    location_ids: list[UUID] = Field(..., min_length=1, max_length=200)
    width_mm: float = Field(50.0, ge=10.0, le=300.0)
    height_mm: float = Field(24.0, ge=5.0, le=300.0)
    copies: int = Field(1, ge=1, le=20)
    #: A QR beside the bars, for a phone camera.
    qr: bool = False
