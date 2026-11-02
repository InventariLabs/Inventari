"""Which models actually read a label, measured on photographs of real products.

The connection test answers this for one synthetic label and one model at a
time. That is the right thing for a settings screen and the wrong thing for a
recommendation: the drawn label is high-contrast black-on-white text with no
perspective, no glare and no packaging around it, so a 1B model scores the
same as a 7B one on it. Somebody installing this needs to know which model to
put in the box before their first photograph, and this is what answers that.

What it measures, and why each part is the way it is:

- **The production path, not a lookalike.** Every call goes through
  ``VisionService.extract_from_bytes_list``, so the schema is composed from
  the same module contributions, the prompt is assembled the same way, the
  retry is the same retry and the usage rows are the same rows. A harness
  that built its own request would be measuring the harness.
- **Photographs, not a rendering.** The corpus is Open Food Facts front
  images — held in hands, at angles, in daylight, in four languages. They are
  addressed by barcode and fetched at run time, so no binary blob enters the
  repository and anybody can rebuild the same corpus.
- **Three scores, because reading, reciting and misfiling look identical in
  one.** These are famous products, and a model that has memorised Nutella
  will fill in a net weight that is nowhere in the frame. ``read`` counts
  fields legible on the photograph that the model got right; ``invented``
  counts fields *not* legible that it answered anyway; ``misfiled`` counts
  answers that are genuinely printed on the package but belong to another
  field — a per-bar nutrition figure is not a net weight. A high ``invented``
  is worse than a low ``read``: it is wrong data arriving with the confidence
  of right data.
- **Two denominators, because declining is not the same as being wrong.**
  ``read`` is out of every legible field in the corpus, the photographs a
  model refused included, so silence cannot flatter a score; ``accuracy`` is
  out of what it did answer. The gap between the two columns is the silence.

Usage (from the repository root, against a running stack)::

    docker compose exec backend uv run python scripts/vision_model_matrix.py \\
        --org <uuid> --models qwen2.5vl:7b,qwen3-vl:8b --out /tmp/matrix.json

    # Render an existing result, or re-apply a corrected corpus to it without
    # paying for the calls again:
    ... --report /tmp/matrix.json
    ... --rescore /tmp/matrix.json

The organization must have a connection bound to ``vision.extract`` — the
harness swaps ``model_name`` on that connection and puts everything back when
it is done, including after a failure.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import pathlib
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

# The application lives at /app in the backend image, and this script is run
# from the repository checkout mounted beside it.
sys.path.insert(0, '/app')

CORPUS = pathlib.Path(__file__).with_name('vision_matrix_corpus.json')
OFF_API = 'https://world.openfoodfacts.org/api/v2/product/{}.json'
# Open Food Facts asks callers to identify themselves and what they are for.
USER_AGENT = 'inventari-vision-matrix/1.0 (model quality measurement)'

# What the frontend sends. ``compressImage`` in ``frontend/src/lib/imageUtils.ts``
# shrinks to 1024px on the longest side at quality 0.8 before upload, so a
# harness feeding full-resolution originals would be measuring a payload no
# user ever produces — and would flatter every model on small print.
MAX_SIDE = 1024
JPEG_QUALITY = 80

SCORED_FIELDS = ('name', 'brand', 'weight', 'expiry_date')

# The closed list ``VisionExtractResult.category`` offers. Answering outside it
# is not a misreading, it is a model that did not follow the schema, and those
# are different problems with different fixes.
CATEGORIES = {
    'dairy',
    'meat',
    'vegetables',
    'fruits',
    'drinks',
    'frozen',
    'dry',
    'canned',
    'spices',
    'other',
}


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def fetch_image(barcode: str, cache: pathlib.Path) -> bytes:
    """The front photograph for *barcode*, from cache or from Open Food Facts."""
    cached = cache / f'{barcode}.jpg'
    if cached.exists():
        return cached.read_bytes()

    def get(url: str) -> bytes:
        response = httpx.get(
            url, headers={'User-Agent': USER_AGENT}, timeout=60, follow_redirects=True
        )
        response.raise_for_status()
        return response.content

    product = json.loads(get(OFF_API.format(barcode) + '?fields=image_front_url'))
    url = (product.get('product') or {}).get('image_front_url')
    if not url:
        raise RuntimeError(f'{barcode}: Open Food Facts has no front image')
    # The '.400.' in the URL is a resize; the full original is what a phone
    # would have produced, and the harness shrinks it itself below.
    data = get(url.replace('.400.jpg', '.full.jpg'))
    if len(data) < 5000:
        data = get(url)
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def as_uploaded(image: bytes) -> bytes:
    """The image as the browser would have sent it."""
    from PIL import Image

    picture = Image.open(io.BytesIO(image)).convert('RGB')
    width, height = picture.size
    scale = min(1.0, MAX_SIDE / max(width, height))
    if scale < 1.0:
        picture = picture.resize((int(width * scale), int(height * scale)))
    buffer = io.BytesIO()
    picture.save(buffer, format='JPEG', quality=JPEG_QUALITY)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


_UNITS = {
    'g': 1.0,
    'gr': 1.0,
    'gram': 1.0,
    'grams': 1.0,
    'kg': 1000.0,
    'ml': 1.0,
    'l': 1000.0,
    'litre': 1000.0,
    'liter': 1000.0,
    'cl': 10.0,
}


def _as_quantity(text: str) -> tuple[float, str] | None:
    """(amount, family) for a printed quantity, or None if it is not one."""
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)', text.strip())
    if not match:
        return None
    unit = match.group(2).lower().rstrip('e')  # 'litre' -> 'litr', see below
    unit = {'litr': 'litre'}.get(unit, unit)
    if unit not in _UNITS:
        return None
    family = 'volume' if unit in {'ml', 'l', 'cl', 'litre', 'liter'} else 'mass'
    return float(match.group(1).replace(',', '.')) * _UNITS[unit], family


def matches(field: str, expected: list[str], read: str) -> bool:
    """Did *read* say the same thing as one of the accepted spellings?"""
    # The same normalisation the connection probe compares with, so the two
    # answer "did the model read it" with one vocabulary rather than two.
    from app.modules.vision._text_norm import normalise_text

    if field == 'weight':
        wanted = _as_quantity(expected[0])
        got = _as_quantity(read)
        return bool(wanted and got and wanted == got)
    answer = normalise_text(read)
    if not answer:
        return False
    for candidate in expected:
        accepted = normalise_text(candidate)
        # Either direction: 'Prince' for 'Prince Goût Chocolat' is a reading,
        # and so is 'Nutella Biscuits x22' for 'Nutella Biscuits'.
        if accepted and (
            accepted in answer or (len(answer) >= 3 and answer in accepted)
        ):
            return True
    return False


def legible_fields(entry: dict[str, Any]) -> int:
    """How many fields this photograph shows — the denominator of ``read``.

    A property of the corpus, not of the answer, which is why a model that
    refused the photograph is still measured out of it: silence and a wrong
    reading both leave a field unread.
    """
    expected = entry['expected']
    return sum(1 for field in SCORED_FIELDS if expected.get(field) is not None)


def score(entry: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    """What this answer got right, got wrong, and made up."""
    expected = entry['expected']
    fields: dict[str, Any] = {}
    read = legible = invented = 0
    for field in SCORED_FIELDS:
        want = expected.get(field)
        got = answer.get(field)
        if want is None:
            # Not on the photograph. Silence is the right answer — but some
            # photographs carry text a model can honestly mistake for one
            # (a per-bar nutrition figure, a '+50g' promotion). Answering
            # with that is a filing error, not a fabrication, and the two
            # deserve different columns.
            answered = got is not None and str(got).strip() != ''
            excused = answered and any(
                matches(field, [candidate], str(got))
                for candidate in (entry.get('tolerated') or {}).get(field, [])
            )
            made_up = answered and not excused
            invented += int(made_up)
            fields[field] = {
                'legible': False,
                'read': got,
                'invented': made_up,
                'tolerated': excused,
            }
            continue
        legible += 1
        # A quantity is one string, a name is a list of accepted spellings.
        # ``list('450 g')`` is five characters, and scoring against those is
        # how every model in the first pass "misread" a weight it had read.
        accepted = want if isinstance(want, list) else [want]
        hit = got is not None and matches(field, accepted, str(got))
        read += int(hit)
        fields[field] = {
            'legible': True,
            'expected': want,
            'read': got,
            'matches': hit,
        }
    category = answer.get('category')
    # Contributed groups — today that means the nutrition module's table. No
    # front-of-pack photograph in this corpus shows one, so anything non-null
    # here was supplied rather than read. It is scored separately because the
    # module states the rule the core fields do not ("leave the values null
    # rather than estimating"), which makes it the control for whether saying
    # so out loud is what keeps a model honest.
    contributed: dict[str, Any] = {}
    for module, group in (answer.get('extra') or {}).items():
        supplied = {
            key: value
            for key, value in (group or {}).items()
            if value is not None and str(value).strip() != ''
        }
        if supplied:
            contributed[module] = supplied
    return {
        'fields': fields,
        'read': read,
        'of': legible,
        'invented': invented,
        'contributed': contributed,
        'contributed_count': sum(len(v) for v in contributed.values()),
        'category': category,
        'category_off_list': bool(category) and str(category).lower() not in CATEGORIES,
    }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


async def bind_purpose(db: Any, org: UUID, connection_id: Any) -> Any:
    """Point ``vision.extract`` at *connection_id*; return what it pointed at.

    The binding lives in the organization's settings rather than on the
    connection, so measuring through a second connection means moving it — and
    putting it back, which is what the return value is for.
    """
    from sqlalchemy import select

    from app.models.organization import Organization

    stored = (
        await db.execute(select(Organization.settings).where(Organization.id == org))
    ).scalar_one()
    settings = dict(stored or {})
    defaults = dict((settings.get('ai') or {}).get('defaults') or {})
    previous = defaults.get('vision.extract')
    if str(previous) == str(connection_id):
        return previous
    defaults['vision.extract'] = str(connection_id)
    settings['ai'] = dict(settings.get('ai') or {}) | {'defaults': defaults}
    organization = await db.get(Organization, org)
    organization.settings = settings
    await db.commit()
    return previous


async def run_one(
    db: Any, org: UUID, user: UUID, image: bytes, *, disable_reasoning: bool = True
) -> tuple[dict[str, Any] | None, str | None]:
    """One production extraction. Returns (answer, failure) — exactly one.

    *user* is not decoration. ``log_llm_usage_async`` returns early when the
    caller has no user id, so a call made without one is billed by the
    provider and leaves no usage row — which would have made the token and
    cost columns of this matrix read zero for every model.
    """
    from app.modules.vision.service import VisionService

    try:
        response = await VisionService.extract_from_bytes_list(
            image_bytes_list=[image],
            db=db,
            organization_id=org,
            user_id=user,
            disable_reasoning=disable_reasoning,
        )
    except Exception as err:  # noqa: BLE001 - every failure class is a result here
        # Commit rather than roll back, so the tokens a failed call still cost
        # are counted here. Production loses them: the router turns these
        # exceptions into an HTTP error, which never reaches the session's
        # commit, and the usage rows flushed before the failure go with it.
        # Rolling back here would reproduce that blindness in the measurement.
        try:
            await db.commit()
        except Exception:  # noqa: BLE001 - a broken session has nothing to save
            await db.rollback()
        return None, f'{type(err).__name__}: {err}'
    # Production commits at the end of the request, and the usage row is part
    # of what it commits. Leaving it uncommitted would make the run free of
    # the organization's own AI quota, which is not what production does.
    await db.commit()
    return response.model_dump(), None


async def tokens_since(db: Any, org: UUID, since: datetime) -> dict[str, Any]:
    """What the provider billed for a call, read off the usage rows it wrote."""
    from sqlalchemy import func, select

    from app.models.ai_usage_log import AIUsageLog

    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.completion_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0.0),
                func.count(),
            ).where(AIUsageLog.organization_id == org, AIUsageLog.created_at >= since)
        )
    ).one()
    return {
        'prompt_tokens': int(row[0]),
        'completion_tokens': int(row[1]),
        'cost_usd': float(row[2] or 0.0),
        'provider_calls': int(row[3]),
    }


def summarise(per_image: list[dict[str, Any]]) -> dict[str, Any]:
    """The per-model row of the table, from its per-image results."""
    ok = [r for r in per_image if r['failure'] is None]
    return {
        'images': per_image,
        'answered': len(ok),
        'of_images': len(per_image),
        'read': sum(r['read'] for r in ok),
        # Two denominators, because they answer two questions. ``legible`` is
        # the whole corpus — a refused photograph is a field unread, and a
        # model cannot improve its score by declining. ``answered_legible``
        # is out of what it did answer, and the gap between the two columns
        # is the model's silence.
        'legible': sum(r['of'] for r in per_image),
        'answered_legible': sum(r['of'] for r in ok),
        'invented': sum(r['invented'] for r in ok),
        'misfiled': sum(
            1 for r in ok for f in r['fields'].values() if f.get('tolerated')
        ),
        'off_list_category': sum(1 for r in ok if r.get('category_off_list')),
        'contributed': sum(r.get('contributed_count', 0) for r in ok),
        'median_seconds': round(
            sorted(r['seconds'] for r in per_image)[len(per_image) // 2], 1
        ),
        'cost_usd': round(sum(r['cost_usd'] for r in per_image), 5),
        'tokens': sum(r['prompt_tokens'] + r['completion_tokens'] for r in per_image),
    }


def rescore(results: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-apply the corpus to answers already collected.

    The photographs cost time and the calls cost money; a correction to what
    counts as a right answer should cost neither. Every model's raw answer is
    kept per field, so a changed corpus is re-applied here rather than by
    asking fourteen models the same fourteen questions again.
    """
    by_barcode = {entry['barcode']: entry for entry in entries}
    for summary in results['models'].values():
        rebuilt = []
        for row in summary['images']:
            entry = by_barcode.get(row['barcode'])
            if entry is None:
                rebuilt.append(row)
                continue
            if row['failure']:
                # A refused photograph is measured out of the corpus like any
                # other. Restated here as well, so a result collected before
                # this was true rescores into the same denominator.
                rebuilt.append(row | {'of': legible_fields(entry)})
                continue
            answer = {field: info.get('read') for field, info in row['fields'].items()}
            answer['category'] = row.get('category')
            carried = {
                key: value
                for key, value in row.items()
                if key
                not in {
                    'fields',
                    'read',
                    'of',
                    'invented',
                    'category',
                    'category_off_list',
                }
            }
            rebuilt.append(carried | score(entry, answer))
        summary.update(summarise(rebuilt))
    return results


def as_markdown(results: dict[str, Any]) -> str:
    """The result as the table that goes into the documentation."""
    lines = [
        '| model | answered | read | accuracy | invented | misfiled | supplied '
        '| median | tokens | cost |',
        '|---|---|---|---|---|---|---|---|---|---|',
    ]
    ranked = sorted(
        results['models'].items(),
        key=lambda item: (
            -item[1]['read'] / max(item[1]['legible'], 1),
            item[1]['invented'],
            item[1]['median_seconds'],
        ),
    )
    for model, summary in ranked:
        cost = f'${summary["cost_usd"]:.4f}' if summary['cost_usd'] else '—'
        lines.append(
            f'| `{model}` | {summary["answered"]}/{summary["of_images"]} '
            f'| {summary["read"]}/{summary["legible"]} '
            f'| {summary["read"]}/{summary.get("answered_legible", summary["legible"])} '
            f'| {summary["invented"]} '
            f'| {summary.get("misfiled", 0)} '
            f'| {summary.get("contributed", 0)} '
            f'| {summary["median_seconds"]} s '
            f'| {summary["tokens"]} | {cost} |'
        )
    # One model refusing every photograph the same way is one finding, not
    # fourteen. Repeating it fourteen times buries the failure that happened
    # on a single image, which is the one worth reading.
    grouped: dict[tuple[str, str], list[str]] = {}
    for model, summary in results['models'].items():
        for row in summary['images']:
            if row['failure']:
                grouped.setdefault((model, row['failure']), []).append(row['barcode'])
    if grouped:
        lines += ['', 'Failures:', '']
        for (model, failure), barcodes in grouped.items():
            where = (
                f'all {len(barcodes)} photographs'
                if len(barcodes)
                == len(next(iter(results['models'].values()))['images'])
                else ', '.join(barcodes)
            )
            lines.append(f'- `{model}` — {where}: {failure}')
    return '\n'.join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', help='render an existing result file and exit')
    parser.add_argument(
        '--rescore',
        help='re-apply the corpus to an existing result file, in place, and exit',
    )
    parser.add_argument('--org', help='organization UUID')
    parser.add_argument(
        '--connection',
        help=(
            'AI connection UUID to measure through; defaults to the only one '
            'the organization has. Given one, the purpose binding is pointed '
            'at it for the run and put back afterwards.'
        ),
    )
    parser.add_argument('--models', help='comma-separated model ids')
    parser.add_argument('--out', help='where to write the JSON result')
    parser.add_argument(
        '--cache',
        default=str(pathlib.Path(tempfile.gettempdir()) / 'vision-matrix-corpus'),
        help='where the fetched photographs are kept between runs',
    )
    parser.add_argument(
        '--only', default='', help='comma-separated barcodes, for a quick pass'
    )
    parser.add_argument(
        '--keep-reasoning',
        action='store_true',
        help=(
            'let the model think — production asks providers to skip the chain '
            'of thought, and this is how that default gets checked rather than '
            'assumed'
        ),
    )
    return parser


def load_corpus(
    only: str, cache: pathlib.Path
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """The entries to measure and their photographs, as the browser would send them."""
    entries = json.loads(CORPUS.read_text())['images']
    if only:
        wanted = {code.strip() for code in only.split(',')}
        entries = [entry for entry in entries if entry['barcode'] in wanted]
    print(f'Corpus: {len(entries)} photos', flush=True)
    images = {
        entry['barcode']: as_uploaded(fetch_image(entry['barcode'], cache))
        for entry in entries
    }
    print(
        f'Fetched and cut to {MAX_SIDE}px: '
        f'{sum(len(image) for image in images.values()) // 1024} kB total',
        flush=True,
    )
    return entries, images


async def measure_model(
    database: Any,
    connection_id: Any,
    org: UUID,
    user_id: Any,
    model: str,
    entries: list[dict[str, Any]],
    images: dict[str, bytes],
    *,
    disable_reasoning: bool = True,
) -> dict[str, Any]:
    """Put *model* on the connection and walk it through the whole corpus."""
    from app.models.ai_connection import AiConnection

    async with database.AsyncSessionLocal() as db:
        connection = await db.get(AiConnection, connection_id)
        connection.model_name = model
        await db.commit()

    print(f'\n=== {model}', flush=True)
    per_image = []
    for entry in entries:
        async with database.AsyncSessionLocal() as db:
            started_at = datetime.now(UTC)
            clock = time.perf_counter()
            answer, failure = await run_one(
                db,
                org,
                user_id,
                images[entry['barcode']],
                disable_reasoning=disable_reasoning,
            )
            elapsed = time.perf_counter() - clock
            usage = await tokens_since(db, org, started_at)
        row = {
            'barcode': entry['barcode'],
            'note': entry['note'],
            'seconds': round(elapsed, 2),
            'failure': failure,
            **usage,
        }
        row |= (
            score(entry, answer)
            if answer
            else {
                'fields': {},
                'read': 0,
                'of': legible_fields(entry),
                'invented': 0,
                'contributed': {},
                'contributed_count': 0,
            }
        )
        per_image.append(row)
        mark = f'{row["read"]}/{row["of"]}' if answer else 'ERROR'
        print(
            f'  {entry["barcode"]:14} {mark:>5}  invented={row.get("invented", 0)}'
            f'  {row["seconds"]:6.1f}s  {failure or ""}',
            flush=True,
        )
    return summarise(per_image)


def render_only(args: argparse.Namespace) -> int | None:
    """Handle the two modes that touch no model, or say this is not one."""
    if args.report:
        print(as_markdown(json.loads(pathlib.Path(args.report).read_text())))
        return 0
    if args.rescore:
        target = pathlib.Path(args.rescore)
        updated = rescore(
            json.loads(target.read_text()), json.loads(CORPUS.read_text())['images']
        )
        target.write_text(json.dumps(updated, indent=2, ensure_ascii=False))
        print(as_markdown(updated))
        return 0
    return None


async def _restore_connection(
    database: Any, conn: Any, original_model: str, original_binding: Any
) -> None:
    """Put the connection back the way the run found it."""
    from app.models.ai_connection import AiConnection

    restore_factory = database.AsyncSessionLocal
    if restore_factory is None:
        raise SystemExit('async engine was never initialised')
    async with restore_factory() as db:
        connection = await db.get(AiConnection, conn.id)
        if connection is None:
            raise SystemExit(f'connection {conn.id} disappeared mid-run')
        connection.model_name = original_model
        if original_binding is not None:
            await bind_purpose(db, conn.organization_id, original_binding)
        await db.commit()


async def main() -> int:
    args = build_parser().parse_args()

    offline = render_only(args)
    if offline is not None:
        return offline
    missing = [name for name in ('org', 'models', 'out') if not getattr(args, name)]
    if missing:
        raise SystemExit(
            f'--{", --".join(missing)} required unless --report or --rescore is given'
        )

    from sqlalchemy import select

    from app import database
    from app.core.module_registry import module_registry
    from app.models.ai_connection import AiConnection

    module_registry.discover_modules()
    database.init_async_engine()

    org = UUID(args.org)
    entries, images = load_corpus(args.only, pathlib.Path(args.cache))

    results: dict[str, Any] = {
        'ran_at': datetime.now(UTC).isoformat(),
        'corpus': str(CORPUS.name),
        'max_side_px': MAX_SIDE,
        'disable_reasoning': not args.keep_reasoning,
        'models': {},
    }

    session_factory = database.AsyncSessionLocal
    if session_factory is None:
        raise SystemExit('async engine was never initialised')
    async with session_factory() as db:
        query = select(AiConnection).where(AiConnection.organization_id == org)
        if args.connection:
            query = query.where(AiConnection.id == UUID(args.connection))
        conn = (await db.execute(query)).scalars().first()
        if conn is None:
            print(f'No AI connection in organization {org}', file=sys.stderr)
            return 2
        original_model = conn.model_name
        # The connection this run puts a model on and the connection the purpose
        # resolves to have to be the same one, or the harness measures whichever
        # model happens to be bound elsewhere.
        original_binding = await bind_purpose(db, org, conn.id)
        print(
            f'Connection: {conn.name} ({conn.provider}), model saved: '
            f'{original_model!r}',
            flush=True,
        )

        from app.models.user import User

        member = (
            (await db.execute(select(User).where(User.organization_id == org)))
            .scalars()
            .first()
        )
        if member is None:
            print(f'Organization {org} has no user', file=sys.stderr)
            return 2
        user_id = member.id

    try:
        for model in [name.strip() for name in args.models.split(',') if name.strip()]:
            summary = await measure_model(
                database,
                conn.id,
                org,
                user_id,
                model,
                entries,
                images,
                disable_reasoning=not args.keep_reasoning,
            )
            results['models'][model] = summary
            print(
                f'  -> answers {summary["answered"]}/{summary["of_images"]}, '
                f'read {summary["read"]}/{summary["legible"]}, '
                f'invented {summary["invented"]}, '
                f'median {summary["median_seconds"]}s',
                flush=True,
            )
    finally:
        await _restore_connection(database, conn, original_model, original_binding)
        print(f'\nModel restored on the connection: {original_model!r}', flush=True)

    pathlib.Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f'\nResult: {args.out}\n', flush=True)
    print(as_markdown(results), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
