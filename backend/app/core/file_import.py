"""Shared file import utilities (CSV/XLS analysis)."""

from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.import_sheet import read_sheet, row_text
from app.core.logging import get_logger

logger = get_logger(__name__)


#: How many rows the mapping step shows the reader before they commit.
PREVIEW_ROWS = 5


def _filled_counts(df: pd.DataFrame) -> dict[str, int]:
    """Per column, how many of the file's rows carry a non-empty value.

    Read over the whole frame, not the preview: a mapping step that warns
    about the data must speak about the file, and the preview stops at
    ``PREVIEW_ROWS`` rows — a sheet whose codes start below them is not an
    empty-coded sheet, whatever the first rows say.
    """
    counts: dict[str, int] = {}
    for column in df.columns:
        values = df[column].astype('string').str.strip()
        counts[column] = int(values.ne('').sum())
    return counts


async def analyze_import_file(file_content: bytes, filename: str) -> dict[str, Any]:
    """Return headers, a short preview, the total row count and per-column
    filled counts.

    The file is parsed ONCE. It used to be read for five preview rows and
    then read again in full purely to count them — and an xlsx is a ZIP, so
    the second pass paid the decompression cost a second time on a file
    somebody uploaded. When that second read failed the count silently
    stayed at five, which is the other reason it is gone: a wrong total is
    worse than a refusal, because the reader acts on it.
    """
    full_df = read_sheet(file_content, filename)

    preview = full_df.head(PREVIEW_ROWS)
    preview = preview.where(pd.notnull(preview), None)

    return {
        'headers': list(full_df.columns),
        'preview_rows': preview.fillna('').to_dict(orient='records'),
        'total_rows': len(full_df),
        'filled_counts': _filled_counts(full_df),
    }


#: What the application itself puts between the steps of a location's path.
#: The breadcrumb on every screen uses it, so it is what somebody copying a
#: location out of the interface will paste into a spreadsheet. ``>`` is
#: accepted beside it because the typographic character does not survive
#: every keyboard.
_PATH_SEPARATORS = ('\u203a', '>')

#: How many candidates a refusal spells out before it starts counting.
_CANDIDATES_SHOWN = 5


def _split_location_path(text: str) -> list[str]:
    """``"Home > Garage > Rack A"`` into its steps, outermost first."""
    for separator in _PATH_SEPARATORS:
        text = text.replace(separator, '\x00')
    return [part.strip() for part in text.split('\x00') if part.strip()]


def _full_path(location: Any, by_id: dict[UUID, Any]) -> str:
    """The location as the interface writes it, root first."""
    names: list[str] = []
    seen: set[UUID] = set()
    current = location
    while current is not None and current.id not in seen:
        seen.add(current.id)
        names.append(current.name)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return ' \u203a '.join(reversed(names))


def _path_ends_at(location: Any, segments: list[str], by_id: dict[UUID, Any]) -> bool:
    """Whether *segments* name this location and its parents, innermost last.

    A partial path is enough: ``Rack A > Shelf 1`` picks out one shelf
    without anybody having to write the site and the building above it.
    """
    current = location
    for name in reversed(segments):
        if current is None or current.name.casefold() != name.casefold():
            return False
        current = by_id.get(current.parent_id) if current.parent_id else None
    return True


async def resolve_storage_location_async(
    db: AsyncSession,
    org_id: UUID,
    row: pd.Series,
    mapping: dict[str, str],
    default_id: str | None,
    cache: dict[str, str],
) -> str | None:
    """Async: look up a storage location by name or path from an import row.

    A bare name is not an address. Names are unique among siblings and
    nowhere else, so "Shelf 1" may sit under every rack in the building —
    and since the depth limit was lifted, naming places that way is the
    ordinary thing to do. This used to take the first row it found, so one
    spreadsheet could file a whole delivery onto the wrong shelf without a
    word to anybody.

    A path resolves as far as it is given: the last step names the location,
    the ones before it name its parents, and a partial path is enough as
    long as it picks out one place. A name that picks out several is
    refused, with the candidates spelled out — the caller shows the refusal
    beside the row it came from, which is the one place a person can act on
    it. Choosing for them is the one thing this must not do.
    """
    from app.core.public_api import core_api

    text = row_text(row, mapping.get('location'))
    if not text and default_id:
        return default_id
    if not text:
        return None
    if text in cache:
        return cache[text]

    # Every location, not the first page of them: the default page size is
    # 200 and an organization with more places than that would have had its
    # later ones read as "no such location".
    locations = await core_api.locations.list_async(db, org_id, limit=100_000)
    by_id = {loc.id: loc for loc in locations}
    segments = _split_location_path(text)
    if not segments:
        return None

    candidates = [loc for loc in locations if _path_ends_at(loc, segments, by_id)]
    if not candidates:
        return None
    if len(candidates) > 1:
        paths = sorted(_full_path(loc, by_id) for loc in candidates)
        shown = ', '.join(paths[:_CANDIDATES_SHOWN])
        if len(paths) > _CANDIDATES_SHOWN:
            shown += ', …'
        raise ServiceRejectionError(
            'storage_location_ambiguous',
            text=text,
            count=len(paths),
            shown=shown,
            example=paths[0],
        )

    cache[text] = str(candidates[0].id)
    return cache[text]


async def resolve_category_async(
    db: AsyncSession,
    org_id: UUID,
    row: pd.Series,
    mapping: dict[str, str],
    default_id: str | None,
    cache: dict[str, str],
) -> str | None:
    """Async: look up a category by code or name from an import row."""
    from app.core.public_api import core_api

    name = row_text(row, mapping.get('category'))
    if not name and default_id:
        return default_id
    if not name:
        return None
    if name in cache:
        return cache[name]

    categories = await core_api.categories.list_async(db, org_id)
    for cat in categories:
        if (cat.code and cat.code.lower() == name.lower()) or (
            cat.name and cat.name.lower() == name.lower()
        ):
            cache[name] = str(cat.id)
            return str(cat.id)
    return None
