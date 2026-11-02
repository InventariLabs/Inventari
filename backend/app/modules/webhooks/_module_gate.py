"""Whether this organization still has webhooks switched on.

`require_module` guards the router, and the router is the part a person uses.
What the module does without a person — matching an event to endpoints,
retrying a failed delivery — never asked, so switching the module off took away
the panel and left the behaviour: events kept going out to an address the admin
could no longer see, signed with an HMAC the receiver reads as proof of origin,
and there was no way left in the application to stop it. The way back to "I can
take this away" ran through switching the module back *on*, which nothing said.

Both of those paths ask here now. The purpose card promises exactly this: "the
outside world simply stops hearing" — and "whatever was listening must be able
to tell that from an endpoint that is merely quiet". Those two sentences meet in
one event: the announcement that this module itself went off. The switch is
already saved when that event reaches the dispatcher, so the gate would cut off
the very message that says "I am going quiet" before any other. It is the one
exception, and `announces_own_switch_off` is how the dispatcher recognises it.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

MODULE_NAME = 'webhooks'

_MODULE_DISABLED_EVENT = 'module.disabled'


async def webhooks_enabled_async(db: AsyncSession, organization_id: UUID) -> bool:
    """True when *organization_id* still has the webhooks module enabled."""
    return await core_api.organizations.is_module_enabled_async(
        db, organization_id, MODULE_NAME
    )


def announces_own_switch_off(event_wire_name: str, payload: Any) -> bool:
    """True for the ``module.disabled`` event that names *this* module.

    A neighbour going off while webhooks is off says nothing the receiver may
    hear, so the module name is part of the test, not only the event name.
    """
    return (
        event_wire_name == _MODULE_DISABLED_EVENT
        and getattr(payload, 'module_name', None) == MODULE_NAME
    )
