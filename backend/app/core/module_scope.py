"""Module context-tag scoping.

Derives the set of context_tags "claimed" by vertical modules from their
CategoryDeclaration.context_tag. Used to isolate the default Inventory view
from vertical-module data (equipment, library, ...).

Pure-Python (no DB session, no organization) so it can be called from both
sync (run_sync) and async handlers.
"""

from app.core.module_registry import module_registry


def get_claimed_context_tags() -> set[str]:
    """Context tags owned by vertical modules — every registered one.

    Whether an organization has the module enabled deliberately does not
    enter into it. Data outlives the module that wrote it: an organization
    that switches ``equipment`` off still has its laptops, and reading the
    claim off the enabled set would drop every one of them back among the
    unclaimed at the moment the module stops looking after them. The tag
    records which module a category belongs to, and that stays true while
    the module is off.

    Registered, not installed, is also what makes the answer the same for
    every organization — the set is a property of the running build, so it
    costs no query and cannot go stale between two lists on one page.

    With only the equipment module declaring a tag this returns
    ``{'equipment'}``; a 'library' module declaring ``context_tag='media'``
    makes it ``{'equipment', 'media'}``.
    """
    claimed: set[str] = set()
    for mod in module_registry.get_all():
        declarations = mod.metadata.categories
        for cat in declarations:
            if cat.context_tag:
                claimed.add(cat.context_tag)
    return claimed


def get_claimed_modules() -> set[str]:
    """Names of the vertical modules that claim their own records.

    A module claims its data by declaring a category context_tag; the same
    modules write their records under a ``meta_data`` namespace named after
    themselves (AGENTS.md, "meta_data namespace convention"). This is the set
    an item's ``module_name`` is measured against — ``{'equipment'}`` today.

    Registered, not installed, for the reason
    :func:`get_claimed_context_tags` gives: the record outlives the module.
    """
    claimed: set[str] = set()
    for mod in module_registry.get_all():
        declarations = mod.metadata.categories
        if any(cat.context_tag for cat in declarations):
            claimed.add(mod.metadata.name)
    return claimed


def get_context_tags_of(module_name: str) -> set[str]:
    """The context tags one named module declares.

    A module's name and the tag it files its categories under are two things,
    not one — ``equipment`` happens to use the same word for both, and a
    'library' module declaring ``context_tag='media'`` does not. Anything
    scoping a query to one module needs the pair, so it is resolved here
    rather than assumed at each call site.
    """
    for mod in module_registry.get_all():
        if mod.metadata.name != module_name:
            continue
        declarations = mod.metadata.categories
        return {cat.context_tag for cat in declarations if cat.context_tag}
    return set()
