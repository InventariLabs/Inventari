"""The declarative base a module's own tables inherit.

The core's ``Base`` lives in ``app.database``, and the install-time safety scan
refuses that import to every module outside this repository: the base's
metadata is the core's, so a table declared on it would be proposed by the
core's autogenerate and created by a core migration — while the platform's
rule is that a module's tables are created by the module's own migration chain
(``docs/subsystems/MIGRATION_OWNERSHIP.md``). The modules this repository
ships reach Core's base through the SDK (``CoreModelBase``), their tables
still created by their own chains.

So a module gets a base of its own. Tables declared on this one are the
module's: ``app.database.Base.metadata`` never grows them, core autogenerate
never proposes them, and the module's ``migrations/versions/`` creates them in
a chain recorded under ``alembic_version_<module>``.

It sits in the contract surface for the same reason the DTOs do — it is the
name a module outside the repository may build on, and it moves only with the
same care (``docs/subsystems/CONTRACTS_STABILITY.md``).
"""

from sqlalchemy.orm import DeclarativeBase


class ModuleModelBase(DeclarativeBase):
    """Declarative base for the tables a module owns."""
