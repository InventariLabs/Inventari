from collections.abc import Mapping

from app.i18n._email_content import (
    INVITATION_EMAIL_CONTENT,
    PASSWORD_RESET_EMAIL_CONTENT,
    REGISTRATION_EMAIL_CONTENT,
    InvitationEmailContent,
    PasswordResetEmailContent,
    RegistrationEmailContent,
    get_invitation_email_content,
    get_password_reset_email_content,
    get_registration_email_content,
)
from app.i18n._errors_de import ERRORS_DE
from app.i18n._errors_en_pl import ERRORS_EN_PL
from app.i18n._errors_es import ERRORS_ES
from app.i18n._errors_fr import ERRORS_FR
from app.i18n._errors_pt import ERRORS_PT
from app.i18n._shopping import SHOPPING_LABELS
from app.i18n._types import (
    MAINTAINED_LANGUAGES,
    SUPPORTED_LANGUAGES,
    ErrorMessages,
    Language,
    ShoppingLabels,
    UnitLabels,
)
from app.i18n._units import UNIT_LABELS

#: Where each maintained language's error catalog lives. The sets of languages
#: are `MAINTAINED_LANGUAGES` and `COMMUNITY_LANGUAGES` (derived from the
#: `Language` literal and the community declaration in `_types`) — this table
#: answers where the complete catalogs are, it does not extend the set.
#: `ERRORS` is built from the maintained set below, so a language added to the
#: literal without a row here fails at import naming the language, instead of
#: serving raw keys to a reader.
_CATALOGS: dict[Language, ErrorMessages] = {
    'en': ERRORS_EN_PL['en'],
    'pl': ERRORS_EN_PL['pl'],
    'de': ERRORS_DE,
    'fr': ERRORS_FR,
    'es': ERRORS_ES,
}

ERRORS: dict[Language, ErrorMessages] = {
    language: _CATALOGS[language] for language in MAINTAINED_LANGUAGES
}

#: The community languages' catalogs: whatever keys they hold so far. A key
#: that is missing is answered in English by `app.i18n.service` (the way the
#: frontend falls back per key), so no change has to translate these.
COMMUNITY_ERRORS: dict[Language, Mapping[str, str]] = {'pt': ERRORS_PT}

__all__ = [
    'COMMUNITY_ERRORS',
    'ERRORS',
    'INVITATION_EMAIL_CONTENT',
    'InvitationEmailContent',
    'MAINTAINED_LANGUAGES',
    'Language',
    'PASSWORD_RESET_EMAIL_CONTENT',
    'PasswordResetEmailContent',
    'REGISTRATION_EMAIL_CONTENT',
    'RegistrationEmailContent',
    'SHOPPING_LABELS',
    'SUPPORTED_LANGUAGES',
    'UNIT_LABELS',
    'ErrorMessages',
    'ShoppingLabels',
    'UnitLabels',
    'get_invitation_email_content',
    'get_password_reset_email_content',
    'get_registration_email_content',
]
