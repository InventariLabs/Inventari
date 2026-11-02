"""A module endpoint enforces permissions in its own namespace and no other.

``require_permission`` took any key, so a third-party module's endpoint
could guard ``items:read``: the grant an organization made for the core UI
then authorized the module's endpoint as a side effect, and a core key
looked like the module's own in the roles matrix. The runtime guard reads
the request's module identity (``app.core.module_identity``): a module the
repository ships may guard core resources (equipment guards
``items:write``), an installed community module may guard only its own
``<module>:`` keys, and core endpoints are never refused.
"""

from __future__ import annotations

import pytest

from app.core.deps import _refuse_borrowed_permission
from app.core.module_identity import module_scope


@pytest.mark.unit
class TestWhoMayGuardWhat:
    def test_core_endpoints_are_never_refused(self):
        _refuse_borrowed_permission('items:write')

    def test_a_shipped_module_may_guard_a_core_permission(self):
        with module_scope('equipment'):
            _refuse_borrowed_permission('items:write')

    def test_a_community_module_may_guard_its_own(self):
        with module_scope('shelf_notes'):
            _refuse_borrowed_permission('shelf_notes:read')

    def test_a_community_module_may_not_guard_a_core_permission(self):
        with module_scope('shelf_notes'), pytest.raises(RuntimeError) as exc:
            _refuse_borrowed_permission('items:read')
        assert 'shelf_notes' in str(exc.value)
        assert 'items:read' in str(exc.value)

    def test_a_community_module_may_not_guard_another_modules(self):
        with module_scope('shelf_notes'), pytest.raises(RuntimeError):
            _refuse_borrowed_permission('equipment:read')
