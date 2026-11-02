"""The organization a self-registered account starts with is named sensibly."""

import pytest

from app.services.auth_service import default_organization_name


@pytest.mark.parametrize('blank', [None, '', '   '])
def test_a_blank_name_yields_the_plain_fallback(blank):
    assert default_organization_name(blank) == 'My Organization'


def test_a_name_is_possessive():
    assert default_organization_name('Jane Doe') == "Jane Doe's Organization"


def test_surrounding_whitespace_is_dropped():
    assert default_organization_name('  Jane Doe ') == "Jane Doe's Organization"


@pytest.mark.parametrize(
    ('lang', 'expected'),
    [
        ('pl', 'Organizacja: Piotr Nowak'),
        ('pl-PL', 'Organizacja: Piotr Nowak'),
        ('de', 'Organisation von Piotr Nowak'),
        ('fr', 'Organisation de Piotr Nowak'),
        ('es', 'Organización de Piotr Nowak'),
        ('en', "Piotr Nowak's Organization"),
        (None, "Piotr Nowak's Organization"),
    ],
)
def test_the_name_is_written_in_the_registrants_language(lang, expected):
    assert default_organization_name('Piotr Nowak', lang) == expected


def test_a_blank_name_falls_back_in_the_registrants_language():
    assert default_organization_name(None, 'pl') == 'Moja organizacja'
