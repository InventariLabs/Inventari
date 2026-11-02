"""Storage type names seeded in English join the language their reader reads.

A storage type's name is data: it stands in the storage picker, on the
storage's card and in every exported row. It was seeded in English for every
organization regardless of the language it was being set up in, so a Polish
organization's first contact with the wizard offered "Shelf / Cabinet" and
"Storage type: Freezer" beside fully translated screens — indistinguishable
from a label the user had typed themselves. The seeders now write the name in
the language they run in (``StorageTypeDeclaration.translations``, and
``translations`` on the profile seeds); this migration repairs the rows
seeded before that.

Which language a row is repaired into is the question a migration has to
answer without a reader. The answer here is the language of the user who
created the organization — the person who ran the seeding and was the reader
it was written for. An organization whose creator is unknown, or whose
creator reads English, is left exactly as it is.

Only rows still carrying the literal the seeder wrote are touched, and only
while ``is_system`` holds: a type the organization renamed is the
organization's, and renaming it would destroy the only record of what it is
called on the shelf. The same rule now guards both seeders, so this cannot
drift back.

Revision ID: stypei18n01
Revises: pkgremove01
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'stypei18n01'
down_revision: str | None = 'pkgremove01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The name each seeded type was written with, per type code.
SEEDED_ENGLISH: dict[str, str] = {
    'SHELF': 'Shelf / Cabinet',
    'STORAGE_ROOM': 'Storage Room',
    'SYSTEM': 'System',
    'FREEZER': 'Freezer',
    'FRIDGE': 'Fridge',
    'PANTRY': 'Pantry',
    'MEDICINE_CABINET': 'Medicine Cabinet',
    'TOOL_ROOM': 'Tool Room',
    'ASSET_STORAGE': 'Asset Storage',
    'IT_RACK': 'IT Rack / Server Room',
    'MAINTENANCE_BAY': 'Maintenance Bay',
    'SERVER_ROOM': 'Server Room',
    'IT_STORAGE': 'IT Storage / Warehouse',
}

#: What each of those is called in the four non-English languages, written
#: out here rather than imported: a migration records the world as it was on
#: this date, and reading today's declarations would make it change meaning
#: every time a module adds a type.
TRANSLATIONS: dict[str, dict[str, str]] = {
    'SHELF': {
        'pl': 'Półka / szafa',
        'de': 'Regal / Schrank',
        'fr': 'Étagère / armoire',
        'es': 'Estante / armario',
    },
    'STORAGE_ROOM': {
        'pl': 'Pomieszczenie magazynowe',
        'de': 'Lagerraum',
        'fr': 'Local de stockage',
        'es': 'Sala de almacenamiento',
    },
    'SYSTEM': {'pl': 'System', 'de': 'System', 'fr': 'Système', 'es': 'Sistema'},
    'FREEZER': {
        'pl': 'Zamrażarka',
        'de': 'Gefrierschrank',
        'fr': 'Congélateur',
        'es': 'Congelador',
    },
    'FRIDGE': {
        'pl': 'Lodówka',
        'de': 'Kühlschrank',
        'fr': 'Réfrigérateur',
        'es': 'Refrigerador',
    },
    'PANTRY': {
        'pl': 'Spiżarnia',
        'de': 'Speisekammer',
        'fr': 'Garde-manger',
        'es': 'Despensa',
    },
    'MEDICINE_CABINET': {
        'pl': 'Apteczka',
        'de': 'Medikamentenschrank',
        'fr': 'Armoire à pharmacie',
        'es': 'Botiquín',
    },
    'TOOL_ROOM': {
        'pl': 'Narzędziownia',
        'de': 'Werkzeugraum',
        'fr': "Salle d'outils",
        'es': 'Sala de herramientas',
    },
    'ASSET_STORAGE': {
        'pl': 'Magazyn zasobów',
        'de': 'Anlagenlager',
        'fr': 'Stockage des actifs',
        'es': 'Almacén de activos',
    },
    'IT_RACK': {
        'pl': 'Szafa RACK / serwerownia',
        'de': 'IT-Rack / Serverraum',
        'fr': 'Baie informatique / salle des serveurs',
        'es': 'Rack informático / sala de servidores',
    },
    'MAINTENANCE_BAY': {
        'pl': 'Stanowisko serwisowe',
        'de': 'Wartungsbereich',
        'fr': 'Atelier de maintenance',
        'es': 'Zona de mantenimiento',
    },
    'SERVER_ROOM': {
        'pl': 'Serwerownia',
        'de': 'Serverraum',
        'fr': 'Salle des serveurs',
        'es': 'Sala de servidores',
    },
    'IT_STORAGE': {
        'pl': 'Magazyn IT',
        'de': 'IT-Lager',
        'fr': 'Stockage informatique',
        'es': 'Almacén informático',
    },
}


def _reader_language_by_organization(bind) -> dict[str, str]:
    """The language the organization was seeded in, as its creator reads.

    No reader exists at migration time, so the closest thing to one is the
    person who ran the seeding: the account that created the organization. An
    organization without it, or one whose creator reads English, is absent
    from this map and keeps its names.
    """
    rows = bind.execute(
        sa.text(
            """
            SELECT o.id::text AS org_id, coalesce(u.preferred_language, 'en') AS lang
            FROM organizations o
            LEFT JOIN users u ON u.id = o.created_by
            """
        )
    ).fetchall()
    return {row.org_id: row.lang for row in rows}


def upgrade() -> None:
    bind = op.get_bind()
    languages = _reader_language_by_organization(bind)
    if not languages:
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT id::text AS row_id, organization_id::text AS org_id,
                   type_code, name
            FROM storage_types
            WHERE is_system IS TRUE AND organization_id IS NOT NULL
            """
        )
    ).fetchall()

    for row in rows:
        english = SEEDED_ENGLISH.get(row.type_code)
        if english is None or row.name != english:
            continue
        localized = TRANSLATIONS.get(row.type_code, {}).get(
            languages.get(row.org_id, 'en')
        )
        if not localized or localized == english:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE storage_types
                SET name = :localized
                WHERE id = :row_id AND name = :english
                """
            ),
            {'localized': localized, 'row_id': row.row_id, 'english': english},
        )


def downgrade() -> None:
    """Put the English literal back on every row this migration renamed.

    The condition is the same pair it was renamed under — a system row whose
    name is one of the translations — so a row the organization has renamed
    since is left alone, as it was on the way in.
    """
    bind = op.get_bind()
    for type_code, translations in TRANSLATIONS.items():
        english = SEEDED_ENGLISH[type_code]
        for localized in set(translations.values()):
            if localized == english:
                continue
            bind.execute(
                sa.text(
                    """
                    UPDATE storage_types
                    SET name = :english
                    WHERE type_code = :type_code AND name = :localized
                      AND is_system IS TRUE
                    """
                ),
                {
                    'english': english,
                    'type_code': type_code,
                    'localized': localized,
                },
            )
