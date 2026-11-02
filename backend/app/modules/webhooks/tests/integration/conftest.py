"""Every webhook integration test answers DNS from a table, never from the network.

Creating or editing an endpoint resolves its host name first (the SSRF guard
refuses an address it cannot check), so a test that saves
``https://example.com/...`` asked the machine's resolver. When the resolver did
not answer, nineteen tests across this directory failed at once with
WEBHOOK_URL_UNRESOLVED — tests of the trace, of creation, of the event list —
none of which is about DNS. A test that is about DNS pins its own answer with
``stub_dns.resolves()`` / ``stub_dns.fails()``.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_dns(stub_dns: object) -> object:
    return stub_dns
