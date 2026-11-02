"""Query parameters the item listing, aggregates and export routes share."""

import logging
from uuid import UUID

from app.core.exceptions import ServiceRejectionError

logger = logging.getLogger(__name__)


def parse_template_ids(raw: str) -> list[UUID]:
    """Split a comma-separated ``template_ids`` value into UUIDs.

    Blank entries are skipped, so an empty value means "no filter". A badly
    formed id is refused with the translated ``invalid_uuid`` sentence; the
    parser's own text goes to the log, not to the reader.
    """
    try:
        return [UUID(value.strip()) for value in raw.split(',') if value.strip()]
    except ValueError as exc:
        logger.warning('Malformed template_ids %r: %s', raw, exc)
        raise ServiceRejectionError('invalid_uuid') from exc
