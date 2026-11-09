"""The shared event bus publishes to the stream this test run owns."""

from app.config import settings
from app.core._event_bus import event_bus


def test_the_event_bus_singleton_uses_the_run_scoped_stream() -> None:
    # conftest points the setting at a per-run stream after app.main (and with
    # it the singleton) has been imported; the bus must follow, or two suites
    # on one Redis would share the default stream.
    assert settings.REDIS_STREAM_NAME != 'inventari_stream'
    assert event_bus.stream_name == settings.REDIS_STREAM_NAME
