from sqlalchemy.dialects.postgresql import JSONB

from app.modules.approvals.models import ApprovalRequest


def test_request_metadata_is_jsonb_like_the_migration_builds_it() -> None:
    # The migration creates JSONB; a JSON model made test databases differ
    # from production (no JSONB operators, no equality).
    assert isinstance(ApprovalRequest.__table__.c.meta_data.type, JSONB)
