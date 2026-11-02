"""The core's word for the tenant, in every language.

``get_error_message`` is the core's refusal catalogue, shared by every
vertical. It named the tenant after one of them: "Nieprawidłowe zaproszenie do
gospodarstwa domowego" answered a registration in an IT-asset organization —
and so did six other refusals — while the interface said "organizacja"
everywhere ("Ustawienia organizacji") and German, French and Spanish already
said Organisation / organisation / organización.

The gate: no language's word for a *household* appears in the catalogue. The
list is short and specific — nouns, not adjectives — so a hit is a message
about the tenant, not a coincidence. `przepis`/`recipe` keys are out of scope
on purpose: those are a module's own messages, kept in the shared catalogue
until modules load their own; what this rule is about is a *core* concept
(the tenant) wearing a vertical's word.
"""

from collections.abc import Mapping

from app.i18n import ERRORS

#: One vertical's word for the tenant, per language.
HOUSEHOLD_WORDS: dict[str, tuple[str, ...]] = {
    'en': ('household',),
    # gospodarstwo / gospodarstwa / gospodarstwem — one stem covers them.
    'pl': ('gospodarstw',),
    'de': ('haushalt',),
    'fr': ('ménage', 'foyer'),
    'es': ('hogar',),
}


def households_in(
    messages_by_language: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Every message that names the tenant after a household, as `lang:key`."""
    found: list[str] = []
    for language, messages in messages_by_language.items():
        for key, value in messages.items():
            text = str(value).lower()
            if any(word in text for word in HOUSEHOLD_WORDS.get(language, ())):
                found.append(f'{language}:{key}')
    return sorted(found)


class TestTheCoreNamesTheTenantNeutral:
    def test_no_refusal_calls_the_tenant_a_household(self) -> None:
        assert households_in(ERRORS) == []

    def test_every_language_is_watched(self) -> None:
        """A language missing from the list would pass by not being read."""
        assert set(HOUSEHOLD_WORDS) == set(ERRORS), (
            'a language carries refusals the household scan does not read'
        )

    def test_the_scan_would_see_the_household_come_back(self) -> None:
        pre_fix = {
            'pl': {
                'organization_invite_invalid': (
                    'Nieprawidłowe zaproszenie do gospodarstwa domowego'
                )
            },
            'en': {'organization_not_found': 'Household not found'},
        }

        assert households_in(pre_fix) == [
            'en:organization_not_found',
            'pl:organization_invite_invalid',
        ]
