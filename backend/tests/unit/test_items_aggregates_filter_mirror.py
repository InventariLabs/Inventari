"""The aggregates' narrowing decision cannot drift from the filter list.

``_query_get`` hand-maintains two ``any(...)`` groups answering "did this
request remove rows from the default view" (``narrowing``) and "did it only
add rows beyond it" (``widening``) — the decision that keeps the ledger from
pricing a shrunken slice at organization-wide rates, while a widened set
keeps its figure. The groups are a hand-copy of
``_apply_item_filters``'s parameter list, so each failure mode is silent:
a new filter parameter defaults to NOT counting (a narrowed answer priced
as whole-organization), and a new scoping parameter defaults to counting
(a whole-screen refusal). This gate forces every new parameter to make
that decision consciously — and to pick a side, not merely to appear.

One instrument, stated plainly: the gate reads the function's signature
and each group's source. It cannot tell a narrowing from a widening —
that judgement stays human, which is why the exclusions live in an
explicit list with a reason each, not in the regex.
"""

import inspect
import re
from pathlib import Path

from app.services.items import _query_get

#: Parameters of ``_apply_item_filters`` that deliberately count as
#: neither narrowing nor widening, each with the reason both groups
#: exclude them.
DELIBERATELY_EXCLUDED = {
    'query': 'the select being filtered, not a filter',
    'organization_id': 'tenancy, not a filter',
    'user_organization_id': 'tenancy for the user mode, not a filter',
    'user_storage_ids': 'tenancy, not a filter',
    'is_deleted': 'the default view, not a narrowing below it',
    'claimed_tags': 'scoping, not a narrowing',
    'today': 'the clock the window is measured by, not a filter',
    'scope_organization_id': (
        'the organization a whole-product question is asked about, not a '
        'narrowing: only_low_stock sums a product beyond the rows this '
        'query is about, and only_low_stock itself is counted as narrowing'
    ),
    'short_products_listed': (
        'only_low_stock once the list has turned it into template_ids, which '
        'are counted as narrowing; the aggregates never pass it, they filter '
        'by only_low_stock itself'
    ),
}

#: The file whose ``narrowing``/``widening`` groups mirror the signature.
QUERY_GET = Path(_query_get.__file__)

# Each group lives inside a function; grabbing the whole module source
# would also match filter names in prose, so the walk starts at the
# assignment and ends at its balanced parenthesis.
_GROUP_ANCHORS = {
    'narrowing': re.compile(r'^\s{4}narrowing = any\(', re.M),
    'widening': re.compile(r'^\s{4}widening = any\(', re.M),
}


def _group_source(name: str) -> str:
    src = QUERY_GET.read_text()
    start = _GROUP_ANCHORS[name].search(src)
    assert start, f'the {name} = any(...) group moved — re-anchor the gate'
    depth = 0
    for index in range(start.start(), len(src)):
        if src[index] == '(':
            depth += 1
        elif src[index] == ')':
            depth -= 1
            if depth == 0:
                return src[start.start() : index + 1]
    raise AssertionError(f'unbalanced parentheses in the {name} group')


def test_every_filter_parameter_picks_a_side_consciously():
    groups = {name: _group_source(name) for name in _GROUP_ANCHORS}
    params = list(inspect.signature(_query_get._apply_item_filters).parameters)

    for name in params:
        if name in DELIBERATELY_EXCLUDED:
            continue
        # Word boundary, not substring: `category` must not be satisfied by
        # a group's `category_id` — a phantom parameter whose name is a
        # prefix of a real one counts as missing, which is the only honest
        # answer.
        sides = [
            group
            for group, source in groups.items()
            if re.search(rf'\b{re.escape(name)}\b', source)
        ]
        assert sides, (
            f'`{name}` is a parameter of _apply_item_filters but neither '
            'the narrowing nor the widening group mentions it — a value '
            'that removes rows silently defaults to keeping the ledger '
            'figure. Place it in narrowing (its values remove rows, the '
            'figure is withheld), in widening (its values only add rows, '
            'the figure stands), in both with complementary conditions '
            '(the side depends on the value, as usage does), or, if it is '
            'scoping rather than either, add it to DELIBERATELY_EXCLUDED '
            'with the reason.'
        )


def test_the_exclusion_list_cannot_rot():
    params = set(inspect.signature(_query_get._apply_item_filters).parameters)
    stale = set(DELIBERATELY_EXCLUDED) - params
    assert not stale, (
        f'DELIBERATELY_EXCLUDED names parameters the filter no longer '
        f'takes: {sorted(stale)}. Remove them from the exclusion list.'
    )


def test_the_withholding_reads_the_narrowing_group_only():
    """The gate cannot read intent, so it pins the one wire that carries
    it: the decision that withholds the ledger figure must be the
    narrowing group — not the widening one, not both."""
    src = QUERY_GET.read_text()
    assert re.search(r'^\s{4}filtered = narrowing$', src, re.M), (
        'the aggregates read `filtered = narrowing` — if the withholding '
        'decision gained another input, the narrowing/widening split no '
        'longer describes it and this gate needs rethinking.'
    )
