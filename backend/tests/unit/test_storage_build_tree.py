"""Unit tests for build_tree: the shape it returns, and cycles it survives.

``build_tree`` is pure — it takes a list of locations and a dict of counts and
returns nodes. It touches no session and performs no I/O, so nothing here
needs a database.

The shape half of this file used to live in
``tests/integration/test_storage_service.py``, where each case took the real
async session, added its locations and flushed them purely to obtain ids that
Python assigns anyway (``StorageLocation.id`` is a ``uuid.uuid4`` default, not
a sequence the server hands out). One of them called ``build_tree([], {})``
and never touched the session at all, while still paying for the fixture.

The cycle half pins an older fix: nodes whose parent chain never reached a
root — a cycle, or a node hanging below one — were silently dropped, so
``GET /locations`` returned them and ``GET /locations/tree`` did not.
"""

from uuid import uuid4

from app.models.storage_location import LocationUsage, StorageLocation
from app.services.storage._queries import build_tree


def _make_location(name, parent=None, *, short_code=None):
    return StorageLocation(
        id=uuid4(),
        name=name,
        parent_id=parent.id if parent is not None else None,
        usage=LocationUsage.INTERNAL,
        short_code=short_code,
    )


def _collect_ids(nodes):
    ids = []
    for node in nodes:
        ids.append(node.id)
        ids.extend(_collect_ids(node.children))
    return ids


class TestBuildTreeShape:
    """What the forest looks like for a well-formed set of locations."""

    def test_single_root(self):
        """One location in, one root out, carrying its own name."""
        root = _make_location('Root')

        tree = build_tree([root], {root.id: 0})

        assert len(tree) == 1
        assert tree[0].id == root.id
        assert tree[0].name == 'Root'
        assert len(tree[0].children) == 0

    def test_multiple_roots(self):
        """Two parentless locations stay two roots, neither swallowing the other."""
        root1 = _make_location('Root1')
        root2 = _make_location('Root2')

        tree = build_tree([root1, root2], {root1.id: 0, root2.id: 0})

        assert len(tree) == 2
        assert {node.name for node in tree} == {'Root1', 'Root2'}

    def test_children_hang_under_their_parent(self):
        """Two children of one root come back as that root's children."""
        root = _make_location('Root')
        child1 = _make_location('Child1', parent=root)
        child2 = _make_location('Child2', parent=root)

        tree = build_tree(
            [root, child1, child2], {root.id: 5, child1.id: 2, child2.id: 3}
        )

        assert len(tree) == 1
        assert tree[0].name == 'Root'
        assert len(tree[0].children) == 2
        assert tree[0].items_count == 5

    def test_deeply_nested_chain_keeps_its_depth(self):
        """Root -> Level2 -> Level3 survives as three levels, not a flat list."""
        root = _make_location('Root')
        level2 = _make_location('Level2', parent=root)
        level3 = _make_location('Level3', parent=level2)

        tree = build_tree([root, level2, level3], {})

        assert len(tree) == 1
        assert tree[0].name == 'Root'
        assert len(tree[0].children) == 1
        assert tree[0].children[0].name == 'Level2'
        assert len(tree[0].children[0].children) == 1
        assert tree[0].children[0].children[0].name == 'Level3'

    def test_node_carries_usage_and_short_code(self):
        """The node is not just a name: usage and short_code travel with it."""
        root = _make_location('Root', short_code='ROOT-001')

        tree = build_tree([root], {root.id: 0})

        assert tree[0].usage == LocationUsage.INTERNAL
        assert tree[0].short_code == 'ROOT-001'

    def test_item_counts_land_on_the_right_nodes(self):
        """Each location takes the count keyed to its own id."""
        loc1 = _make_location('Loc1')
        loc2 = _make_location('Loc2')

        tree = build_tree([loc1, loc2], {loc1.id: 10, loc2.id: 25})

        node_map = {node.name: node for node in tree}
        assert node_map['Loc1'].items_count == 10
        assert node_map['Loc2'].items_count == 25

    def test_missing_item_count_defaults_to_zero(self):
        """A location absent from the counts reads zero, not None."""
        root = _make_location('Root')

        tree = build_tree([root], {})

        assert tree[0].items_count == 0

    def test_complex_hierarchy_keeps_both_branches(self):
        """Kitchen (Fridge, Cabinet) and Cellar (Freezer) stay two separate roots."""
        kitchen = _make_location('Kitchen')
        fridge = _make_location('Fridge', parent=kitchen)
        cabinet = _make_location('Cabinet', parent=kitchen)
        cellar = _make_location('Cellar')
        freezer = _make_location('Freezer', parent=cellar)

        tree = build_tree([kitchen, fridge, cabinet, cellar, freezer], {})

        assert len(tree) == 2
        kitchen_node = next(n for n in tree if n.name == 'Kitchen')
        cellar_node = next(n for n in tree if n.name == 'Cellar')
        assert len(kitchen_node.children) == 2
        assert len(cellar_node.children) == 1

    def test_empty_list_gives_an_empty_forest(self):
        """No locations, no nodes — and no session consulted to find that out."""
        tree = build_tree([], {})

        assert len(tree) == 0


class TestBuildTreeCycleVisibility:
    """build_tree must keep cyclic nodes visible instead of dropping them."""

    def test_cyclic_pair_appears_as_two_roots(self):
        """A two-node cycle yields both nodes as roots, with no loop edges."""
        a = _make_location('A')
        b = _make_location('B')
        a.parent_id = b.id
        b.parent_id = a.id

        tree = build_tree([a, b], {})

        assert len(tree) == 2
        assert {node.id for node in tree} == {a.id, b.id}
        assert all(node.children == [] for node in tree)

    def test_node_hanging_below_cycle_is_visible(self):
        """A node whose parent chain enters a cycle must not disappear."""
        a = _make_location('A')
        b = _make_location('B')
        a.parent_id = b.id
        b.parent_id = a.id
        x = _make_location('X', parent=a)

        tree = build_tree([a, b, x], {})

        assert {node.id for node in tree} == {a.id, b.id, x.id}

    def test_tree_node_count_matches_input_count(self):
        """Every input node appears in the tree exactly once."""
        a = _make_location('A')
        b = _make_location('B')
        a.parent_id = b.id
        b.parent_id = a.id
        x = _make_location('X', parent=a)

        tree = build_tree([a, b, x], {})

        collected = _collect_ids(tree)
        assert len(collected) == 3
        assert set(collected) == {a.id, b.id, x.id}

    def test_valid_hierarchy_unchanged(self):
        """Control case: a healthy tree keeps its shape."""
        root = _make_location('Root')
        child = _make_location('Child', parent=root)

        tree = build_tree([root, child], {})

        assert len(tree) == 1
        assert tree[0].id == root.id
        assert [c.id for c in tree[0].children] == [child.id]
