"""Mail an organization sends is from the organization, unless it chose a name.

The sender name defaulted to the product's name, so an invitation arrived from
"Inventari <address>" while its text, the join page and the documents all used
the organization's name.
"""

from __future__ import annotations

from typing import Any

from app.services.auth_service import AuthService


async def _config_for(db: Any, org: Any, smtp: dict[str, Any]) -> dict[str, Any]:
    org.settings = {'smtp': smtp}
    db.add(org)
    await db.commit()
    config = await AuthService.get_org_smtp_config_async(db, org.id)
    assert config is not None
    return config


class TestTheSenderName:
    async def test_a_blank_name_becomes_the_organizations(
        self, real_async_db_session: Any, async_test_household: Any
    ) -> None:
        org = async_test_household
        config = await _config_for(
            real_async_db_session,
            org,
            {'host': 'smtp.example.com', 'port': 587, 'from_name': ''},
        )

        assert config['from_name'] == org.name

    async def test_a_name_that_was_never_set_becomes_the_organizations(
        self, real_async_db_session: Any, async_test_household: Any
    ) -> None:
        org = async_test_household
        config = await _config_for(
            real_async_db_session, org, {'host': 'smtp.example.com', 'port': 587}
        )

        assert config['from_name'] == org.name

    async def test_a_name_the_administrator_chose_is_kept(
        self, real_async_db_session: Any, async_test_household: Any
    ) -> None:
        config = await _config_for(
            real_async_db_session,
            async_test_household,
            {'host': 'smtp.example.com', 'port': 587, 'from_name': 'Acme Support'},
        )

        assert config['from_name'] == 'Acme Support'
