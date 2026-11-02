"""The lint that refuses a function taking an organization it never reads.

Of four planted tenant-filter omissions, two left the ``organization_id``
parameter unread and every gate stayed green. A parameter that names the
tenant and is then ignored is the shape a forgotten filter leaves behind, and
it is visible without running anything.
"""

from pathlib import Path

from app.core.architecture_lint._quality_checks_tenancy import (
    _check_unread_org_parameter,
)


def _app(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / 'app'
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return root


def _errors(entries: list[str]) -> list[str]:
    return [e for e in entries if e.startswith('::error')]


FORGOTTEN_FILTER = """
async def get_async(db, organization_id, partner_id):
    return await db.scalar(select(Partner).where(Partner.id == partner_id))
"""

READ_FILTER = """
async def get_async(db, organization_id, partner_id):
    return await db.scalar(
        select(Partner).where(
            Partner.id == partner_id, Partner.organization_id == organization_id
        )
    )
"""


def test_a_function_that_takes_the_organization_and_never_reads_it_is_refused(
    tmp_path,
):
    root = _app(tmp_path, {'services/partner_service.py': FORGOTTEN_FILTER})

    errors = _errors(_check_unread_org_parameter(root, set()))

    assert len(errors) == 1
    assert 'services/partner_service.py::get_async' in errors[0]
    assert 'organization_id' in errors[0]


def test_reading_the_organization_passes(tmp_path):
    root = _app(tmp_path, {'services/partner_service.py': READ_FILTER})

    assert _check_unread_org_parameter(root, set()) == []


def test_handing_the_organization_on_counts_as_reading_it(tmp_path):
    # What the callee does with it is its own signature's business.
    root = _app(
        tmp_path,
        {
            'services/a.py': (
                'def outer(db, org_id, item_id):\n'
                '    return inner(db, organization_id=org_id, item_id=item_id)\n'
            )
        },
    )

    assert _check_unread_org_parameter(root, set()) == []


def test_methods_are_named_by_their_class(tmp_path):
    root = _app(
        tmp_path,
        {
            'core/public_api/_items_writes.py': (
                'class CoreItemsWritesMixin:\n'
                '    async def create_async(self, db, organization_id, data, user):\n'
                '        return await create_item(db=db, item_in=data, user=user)\n'
            )
        },
    )

    errors = _errors(_check_unread_org_parameter(root, set()))

    assert len(errors) == 1
    assert '_items_writes.py::CoreItemsWritesMixin.create_async' in errors[0]


def test_a_body_with_nothing_in_it_declares_a_signature_and_is_not_refused(
    tmp_path,
):
    # Protocols, abstract methods and stubs promise the parameter to an
    # implementation; the implementation is where it is read or not.
    root = _app(
        tmp_path,
        {
            'core/protocols.py': (
                'class Reader(Protocol):\n'
                '    async def read(self, db, organization_id): ...\n'
                '    async def count(self, db, organization_id):\n'
                '        """How many."""\n'
                '    def total(self, organization_id):\n'
                '        raise NotImplementedError\n'
                '    def other(self, organization_id):\n'
                '        pass\n'
            )
        },
    )

    assert _check_unread_org_parameter(root, set()) == []


def test_a_baselined_function_is_a_notice_not_an_error(tmp_path):
    root = _app(tmp_path, {'services/partner_service.py': FORGOTTEN_FILTER})
    key = f'{root.name}/services/partner_service.py::get_async'

    entries = _check_unread_org_parameter(root, {key})

    assert _errors(entries) == []
    assert len(entries) == 1
    assert entries[0].startswith('::notice')


def test_tests_are_not_read(tmp_path):
    root = _app(tmp_path, {'modules/x/tests/test_x.py': FORGOTTEN_FILTER})

    assert _check_unread_org_parameter(root, set()) == []
