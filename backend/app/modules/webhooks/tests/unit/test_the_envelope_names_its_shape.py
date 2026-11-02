"""The outbound envelope names the shape it speaks.

Four keys went out with no version among them, so an external consumer had
nothing to pin its parsing against: a field added to the envelope, renamed, or
nestled differently would arrive as the same four-key blob and be read as the
same four-key blob. Anyone following the delivery had to treat the shape as
frozen by goodwill.

``schema_version`` costs one key now, while the consumers are few, and turns
every later change into something a receiver can detect instead of guess at.
It is additive — no key is removed or reworded — so a reader that ignores it
keeps working exactly as before.
"""

from uuid import uuid4

from app.core.contracts.events._base import TenantEventPayload
from app.modules.webhooks._webhook_constants import build_outbound_payload


def _payload() -> TenantEventPayload:
    return TenantEventPayload(**{'organization_id': str(uuid4()), 'detail': 'x'})


class TestTheEnvelopeNamesItsShape:
    def test_the_envelope_carries_a_schema_version(self) -> None:
        outbound = build_outbound_payload('item.created', _payload())

        assert outbound['schema_version'] == 1, (
            'the envelope has no way to say which shape it is speaking, so a '
            'consumer cannot tell a changed contract from a bad day'
        )

    def test_the_version_is_additive_rather_than_a_reskin(self) -> None:
        """Every key that shipped before is still there under its own name.

        A consumer written against the unversioned envelope must not need a
        change to keep reading it.
        """
        outbound = build_outbound_payload('item.created', _payload())

        assert set(outbound) == {
            'event',
            'timestamp',
            'organization_id',
            'data',
            'schema_version',
        }
