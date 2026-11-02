"""The production stack runs the application as a role without SUPERUSER.

The postgres image makes ``DB_USER`` the cluster's bootstrap superuser, and
Postgres never lets that role give the attribute up. An application connected
as it hands any SQL that reaches the database ``COPY ... TO PROGRAM`` and
``pg_read_file``. So the compose files keep ``DB_USER`` for administration and
put the application — the backend, its migrations, PgBouncer, the demo reset —
on ``DB_APP_USER``, which ``docker/postgres/app-role.sh`` creates as the owner
of the schema and nothing more.

What the role can and cannot do is Postgres's to enforce and was measured on a
running stack; what these tests pin is the wiring, because a single connection
string pointed back at ``DB_USER`` restores the whole exposure and looks like
an innocent edit.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

#: The checkout root: three parents above this file on the host, the
#: read-only mount ``INVENTARI_REPO_ROOT`` names in the container.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: ``postgresql://<user>:<password>@`` with compose's ``${VAR}`` /
#: ``${VAR:-default}`` interpolation in the first two places.
_URL_CREDENTIALS = re.compile(r'postgresql://\$\{(\w+)[^}]*\}:\$\{(\w+)[^}]*\}@')


def _services(name: str) -> dict[str, Any]:
    return yaml.safe_load((_REPO_ROOT / name).read_text(encoding='utf-8'))['services']


def _credentials(url: str) -> tuple[str, str]:
    match = _URL_CREDENTIALS.match(url)
    assert match, f'not a postgresql URL with interpolated credentials: {url}'
    return match.group(1), match.group(2)


def _variable(value: str) -> str:
    match = re.fullmatch(r'\$\{(\w+)[^}]*\}', value)
    assert match, f'not a single interpolated variable: {value}'
    return match.group(1)


def _waits_for_the_role(service: dict[str, Any]) -> bool:
    condition = service.get('depends_on', {}).get('db-app-role', {}).get('condition')
    return condition == 'service_completed_successfully'


class TestTheProductionStack:
    def test_the_backend_and_its_migrations_connect_as_the_application_role(
        self,
    ) -> None:
        env = _services('docker-compose.prod.yml')['backend']['environment']

        assert _credentials(env['DATABASE_URL']) == ('DB_APP_USER', 'DB_APP_PASSWORD')
        assert _credentials(env['MIGRATION_DATABASE_URL']) == (
            'DB_APP_USER',
            'DB_APP_PASSWORD',
        )

    def test_the_pooler_logs_in_as_the_application_role(self) -> None:
        env = _services('docker-compose.prod.yml')['pgbouncer-main']['environment']

        assert _variable(env['DB_USER']) == 'DB_APP_USER'
        assert _variable(env['DB_PASSWORD']) == 'DB_APP_PASSWORD'

    def test_the_role_exists_before_anything_logs_in_as_it(self) -> None:
        services = _services('docker-compose.prod.yml')

        assert _waits_for_the_role(services['backend'])
        assert _waits_for_the_role(services['pgbouncer-main'])

    def test_the_role_is_set_up_by_the_superuser_and_its_password_is_required(
        self,
    ) -> None:
        role = _services('docker-compose.prod.yml')['db-app-role']
        env = role['environment']

        assert _variable(env['PGUSER']) == 'DB_USER'
        assert _variable(env['DB_APP_USER']) == 'DB_APP_USER'
        # ``:?`` stops `docker compose up` on an empty value instead of
        # creating a role with an empty password.
        assert env['DB_APP_PASSWORD'].startswith('${DB_APP_PASSWORD:?')

    def test_the_example_environment_names_the_application_role(self) -> None:
        names = re.findall(
            r'^([A-Z_]+)=',
            (_REPO_ROOT / '.env.production.example').read_text(encoding='utf-8'),
            flags=re.MULTILINE,
        )

        assert {'DB_APP_USER', 'DB_APP_PASSWORD'} <= set(names)


class TestTheProductsDatabase:
    """The optional `food` profile had the same exposure the main database had.

    Its bootstrap superuser was also what `pgbouncer-products` and the
    documented `PRODUCTS_DATABASE_URL` connected as, and the pooler connected
    nothing at all: no service, no document and no example ever named it as a
    host. So the split arrives here the same way it arrived for `db`, and the
    pooler is gone rather than wired up.
    """

    def test_the_role_is_set_up_by_the_superuser_with_the_same_script(self) -> None:
        role = _services('docker-compose.prod.yml')['products-app-role']
        env = role['environment']

        assert role['profiles'] == ['food']
        assert _variable(env['PGUSER']) == 'PRODUCTS_DB_USER'
        assert _variable(env['DB_APP_USER']) == 'PRODUCTS_DB_APP_USER'
        # ``:-``, not ``:?``: compose interpolates the whole file before it
        # looks at profiles, so a required value would stop every install
        # that never enables `food`. The script inside refuses instead —
        # on the start where the profile is actually used.
        assert env['DB_APP_PASSWORD'] == '${PRODUCTS_DB_APP_PASSWORD:-}'
        assert role['volumes'] == ['./docker/postgres/app-role.sh:/app-role.sh:ro']

    def test_the_pooler_that_nothing_connected_to_is_gone(self) -> None:
        services = _services('docker-compose.prod.yml')

        assert 'pgbouncer-products' not in services

    def test_the_backend_waits_for_the_role_only_when_the_profile_is_on(self) -> None:
        depends = _services('docker-compose.prod.yml')['backend']['depends_on'][
            'products-app-role'
        ]

        assert depends['condition'] == 'service_completed_successfully'
        # Without `required: false` compose refuses a dependency on a service
        # its own profile excludes, and the stack would not start at all on an
        # install that leaves `food` off.
        assert depends['required'] is False

    def test_the_example_environment_names_the_products_application_role(self) -> None:
        names = re.findall(
            r'^([A-Z_]+)=',
            (_REPO_ROOT / '.env.production.example').read_text(encoding='utf-8'),
            flags=re.MULTILINE,
        )

        assert {'PRODUCTS_DB_APP_USER', 'PRODUCTS_DB_APP_PASSWORD'} <= set(names)

    def test_the_documented_connection_string_is_the_application_role(self) -> None:
        """A deployer copies these; aimed at the superuser they bypass the split."""
        for doc in ('DEPLOYMENT.md', 'docs/OFF_DATABASE_SETUP.md'):
            source = (_REPO_ROOT / doc).read_text(encoding='utf-8')

            assert 'postgresql://products_app:' in source, (
                f'{doc} shows no connection string as the application role'
            )
            assert 'postgresql://products_user:' not in source, (
                f'{doc} still aims the application at the bootstrap superuser'
            )
            assert 'pgbouncer-products' not in source, (
                f'{doc} names a pooler docker-compose.prod.yml no longer runs'
            )


class TestTheDemoReset:
    def test_it_connects_as_the_application_role(self) -> None:
        reset = _services('docker-compose.demo.yml')['demo-reset']

        assert _credentials(reset['environment']['DATABASE_URL']) == (
            'DB_APP_USER',
            'DB_APP_PASSWORD',
        )
        assert _waits_for_the_role(reset)


class TestTheRoleScript:
    def test_it_refuses_to_make_the_superuser_the_application_role(self) -> None:
        # The check runs before the script reaches for the database, so no
        # server is needed to see it refuse.
        result = subprocess.run(
            ['/bin/sh', str(_REPO_ROOT / 'docker' / 'postgres' / 'app-role.sh')],
            env={
                'PATH': os.environ.get('PATH', ''),
                'PGHOST': 'nowhere',
                'PGUSER': 'inventari_user',
                'PGPASSWORD': 'x',
                'PGDATABASE': 'inventari_db',
                'DB_APP_USER': 'inventari_user',
                'DB_APP_PASSWORD': 'y',
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 1
        assert 'DB_APP_USER must differ from DB_USER' in result.stderr

    def test_it_names_the_variable_the_products_profile_fills(self) -> None:
        # compose hands this script DB_APP_PASSWORD in both databases, so the
        # sentence has to name the .env variable a deployer actually sets —
        # for the products database that is not DB_APP_PASSWORD, and following
        # the message literally would change the wrong line.
        result = subprocess.run(
            ['/bin/sh', str(_REPO_ROOT / 'docker' / 'postgres' / 'app-role.sh')],
            env={
                'PATH': os.environ.get('PATH', ''),
                'PGHOST': 'nowhere',
                'PGUSER': 'products_user',
                'PGPASSWORD': 'x',
                'PGDATABASE': 'products_db',
                'DB_APP_USER': 'products_app',
                'DB_APP_PASSWORD': '',
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        # The status is the shell's: a null expansion aborts with whatever
        # /bin/sh there uses, so what is pinned is the refusal, not its number.
        assert result.returncode != 0
        assert 'PRODUCTS_DB_APP_PASSWORD' in result.stderr
