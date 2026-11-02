"""The shape of a task on the floor's To do list.

One task, whatever it was derived from: an expected delivery, an order to
ship, a production run, a document waiting for an approval, a count that has
fallen due, or a task the boss typed in. The sentence the reader sees is
built from these fields in the reader's language, not stored here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints

WorkItemState = Literal['todo', 'in_progress', 'done']
WorkItemView = Literal['all', 'mine', 'overdue']


class WorkItemSchema(BaseModel):
    """A task, with the one next action and the record that action opens.

    ``state`` is read from what has happened to the source, never typed in:
    nothing recorded is ``todo``, an open session or recorded quantities is
    ``in_progress``, a source posted or recorded in the last day is ``done``
    (listed only when asked for), and a cancelled one is no longer a task.
    A custom task is ``done`` when it is ticked, which nothing else can say.
    """

    key: str
    #: ``receive``, ``ship``, ``expected_delivery``, ``produce``, ``approve``,
    #: ``backorder``, ``count``, ``putaway`` or ``custom`` — or a kind a
    #: module added.
    kind: str
    state: WorkItemState
    #: The kind of record the task is derived from (``document``,
    #: ``purchase_order``, ``production_order``, ``cycle_count``,
    #: ``putaway`` — the receipt line whose goods wait in a receiving area —
    #: ``custom``, or a module's own); with ``source_id`` it names the task.
    source_kind: str
    source_id: UUID
    due_date: date | None = None
    overdue: bool = False
    assignee_id: UUID | None = None
    assignee_name: str | None = None
    #: A built-in verb (``receive``, ``pick``, ``resume``, ``pack``,
    #: ``complete``, ``receive_delivery``, ``produce``, ``review_approval``,
    #: ``open_draft``, ``count``, ``put_away``) the screen words and routes
    #: itself.
    next_action: str | None = None
    #: A ready sentence, label and in-app link, for a task a module
    #: contributed that the screen has no wording or route for.
    sentence: str | None = None
    action_label: str | None = None
    action_href: str | None = None
    #: What the sentence is about: the supplier, the customer, the product to
    #: make, the count's name, or a custom task's own title.
    subject: str | None = None
    number: str | None = None
    #: How much of it: order or document lines, or the quantity to make or
    #: put away.
    count: Decimal | None = None
    #: The unit ``count`` is in, where it is a quantity of goods.
    unit: str | None = None
    #: The shelf the goods come from or go to, where one is named.
    place: str | None = None
    #: That shelf's label code, when it has one — the line the floor reads
    #: first on the shared shelf card.
    place_code: str | None = None
    #: That shelf, where the action needs it: a putaway's suggested shelf.
    place_id: UUID | None = None
    #: Why that shelf: a ``rule`` named it, the product already lies there
    #: (``stock``), or it is the shelf the last move into the zone used
    #: (``zone``). Empty when nothing named it.
    place_source: Literal['rule', 'stock', 'zone'] | None = None
    #: Set when the profile asks the worker to scan the shelf's label before
    #: the goods go on it. The shelf card then waits for the scan, and the
    #: put-away action carries the code that confirmed it.
    shelf_scan_required: bool = False
    #: Set on a document task, so a dispatch can be picked from the list.
    document_type: str | None = None
    document_status: str | None = None
    stage_holder_name: str | None = None
    #: The number of the document a backorder continues.
    origin_number: str | None = None
    #: On a backorder draft that takes goods out: whether the shelves it would
    #: draw from cover it now, in full, in part or not at all. Read at request
    #: time from the stock; empty on every other task.
    stock_cover: Literal['full', 'partial', 'none'] | None = None
    #: On a document task: how many of its lines are finished, so a card
    #: under way can show how far it has got.
    lines_done: int | None = None
    #: When a ``done`` task was posted or ticked off; empty when the source
    #: does not say.
    done_at: datetime | None = None


class WorkItemsSection(BaseModel):
    """The tasks and the server's own count of every task there is.

    A capped dashboard section, not a pageable list; see ``DocumentsTodoSection``.
    """

    items: list[WorkItemSchema]
    total: int


class WorkItemMeasures(BaseModel):
    """What this week's work says about the floor, from the records alone.

    ``dock_to_stock_seconds`` averages, over the receipts posted this week,
    the time from the first scan of the delivery to its posting; a receipt
    nobody scanned has no arrival and is left out of ``dock_to_stock_count``.
    ``shipped_same_day`` of ``shipped_total`` dispatches posted this week left
    on the day they were raised.
    """

    dock_to_stock_seconds: int | None = None
    dock_to_stock_count: int = 0
    shipped_same_day: int = 0
    shipped_total: int = 0


class WorkItemAssign(BaseModel):
    """Who a task is for; ``null`` leaves it with nobody.

    ``only_if_unassigned`` makes the write a claim: the task is given to
    ``assignee_id`` only while nobody holds it, and a task somebody else has
    taken in the meantime is refused rather than taken from them.
    """

    assignee_id: UUID | None = None
    only_if_unassigned: bool = False


class WorkItemCustomCreate(BaseModel):
    """A task the boss adds by hand."""

    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    assignee_id: UUID | None = None
    due_date: date | None = None


class WorkItemDone(BaseModel):
    """Tick a custom task off, or take the tick back."""

    done: bool


class PutawayDo(BaseModel):
    """The shelf the goods were carried to — the suggestion, or another.

    ``scanned_code`` is the label the worker read at that shelf. The profile
    may ask for it before the goods go on: the server resolves it then, so a
    scan is something the shelf answered rather than something the screen
    claims.
    """

    location_id: UUID
    scanned_code: str | None = None
