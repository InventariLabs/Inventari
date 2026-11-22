"""The enrichment's verdict needs the viewer's grants, or it is null."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.approvals._services_enrichment import _viewer_can_decide


def _open_request_naming(viewer_id: object) -> tuple[object, object]:
    request = SimpleNamespace(status='PENDING', current_stage=1, created_by=uuid4())
    workflow = SimpleNamespace(
        stages=[{'order': 1, 'role': 'manager', 'approver_user_ids': [str(viewer_id)]}]
    )
    return request, workflow


@pytest.mark.unit
class TestViewerCanDecideNeedsGrants:
    @pytest.mark.parametrize(
        ('approve', 'read'),
        [(None, None), (None, True), (True, None), (False, None)],
    )
    def test_a_named_viewer_without_both_grants_gets_null(
        self, approve: bool | None, read: bool | None
    ) -> None:
        viewer = uuid4()
        request, workflow = _open_request_naming(viewer)

        verdict = _viewer_can_decide(
            request,  # type: ignore[arg-type]
            workflow,  # type: ignore[arg-type]
            viewer,
            False,
            viewer_has_approve_grant=approve,
            viewer_has_read_grant=read,
        )

        assert verdict is None

    def test_a_named_viewer_with_the_grants_stated_gets_a_verdict(self) -> None:
        viewer = uuid4()
        request, workflow = _open_request_naming(viewer)

        verdict = _viewer_can_decide(
            request,  # type: ignore[arg-type]
            workflow,  # type: ignore[arg-type]
            viewer,
            False,
            viewer_has_approve_grant=False,
            viewer_has_read_grant=True,
        )

        assert verdict is True
