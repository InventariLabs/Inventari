"""Barcode normalization utilities.

Ensures all barcodes are stored in a canonical format (EAN-13 / GTIN-13)
regardless of the input format (UPC-A 12-digit, EAN-8, raw scans).
"""

import re

# Matches a string that is purely numeric and 8–14 digits long.
_NUMERIC_BARCODE = re.compile(r'^\d{8,14}$')

#: The GS1 prefix of the codes Inventari makes for products that carry none.
#: 20–29 is GS1's restricted-circulation range: codes a company may assign
#: inside its own walls, which no manufacturer's GTIN will ever take. 20 is
#: the one no country gives a meaning; 21–29 are where shops print weight and
#: price into the code, and a till reading one of ours would look for them.
INTERNAL_EAN_PREFIX = '20'

#: The GS1 prefix ranges a company may assign to goods sold only inside its
#: own walls: 02, 04 and 20–29. Numbers in them are not globally unique — the
#: same digits stand for different goods at every shop that prints them — so a
#: shared product database has no one meaning to answer with.
RESTRICTED_CIRCULATION_PREFIXES = ('02', '04') + tuple(
    str(prefix) for prefix in range(20, 30)
)


def is_restricted_circulation(code: str | None) -> bool:
    """Whether *code* is a GS1 restricted-circulation number.

    GS1 General Specifications, "Restricted circulation numbers": prefixes
    02, 04 and 20–29 on a GTIN-13, and a GTIN-8 beginning with 0 or 2, are
    assigned by the company that prints the code, not by GS1, and must not
    be looked up in a shared product database.

    The number is read as it was printed, because the canonical GTIN-13 form
    hides a GTIN-8's mark behind five zeroes: a scanned ``20000004`` is
    stored and looked up as ``0000020000004``. A GTIN-14 carries an indicator
    digit in front of the GTIN-13 body — zero when a shorter code is padded
    for trade-item data — so the mark sits one place to the right there.
    """
    if code is None:
        return False
    digits = code.strip()
    if not digits.isdigit():
        return False

    if len(digits) == 14:
        digits = digits[1:]

    if len(digits) == 8:
        return digits[0] in '02'
    if len(digits) == 13 and digits.startswith('00000'):
        return digits[5] in '02'

    canonical = normalize_barcode(digits)
    return canonical is not None and canonical[:2] in RESTRICTED_CIRCULATION_PREFIXES


def gtin_check_digit(body: str) -> str:
    """The GS1 mod-10 check digit that completes *body* (all digits).

    Weights alternate 3/1 starting from the digit next to the check digit,
    so the same rule serves EAN-8, UPC-A, EAN-13 and GTIN-14.
    """
    total = sum(
        int(ch) * (3 if i % 2 == 0 else 1) for i, ch in enumerate(reversed(body))
    )
    return str((10 - total % 10) % 10)


def validate_checksum(barcode: str | None) -> bool:
    """Validate the GTIN mod-10 checksum of an 8/12/13/14-digit barcode.

    Returns True for non-GTIN barcodes (non-numeric, or other lengths) so that
    internal codes are not rejected — only standard GS1 GTINs are checked.
    Returns False when the check digit does not match (a likely typo).
    """
    if not barcode or not barcode.isdigit() or len(barcode) not in (8, 12, 13, 14):
        return True  # not a GTIN — leave internal/odd-length codes alone
    return gtin_check_digit(barcode[:-1]) == barcode[-1]


def normalize_barcode(barcode: str | None) -> str | None:
    """Normalize a barcode to a canonical format.

    - Strips whitespace
    - UPC-A (12 digits) → EAN-13 via zero-padding
    - EAN-8 (8 digits) → EAN-13 via zero-padding
    - EAN-13 / GTIN-13 pass through unchanged
    - Non-numeric barcodes pass through unchanged (e.g. internal codes)
    """
    if barcode is None:
        return None

    cleaned = barcode.strip()
    if not cleaned:
        return None

    # Only normalize purely numeric barcodes
    if not _NUMERIC_BARCODE.match(cleaned):
        return cleaned

    # UPC-A (12 digits) → EAN-13: prepend leading zero
    if len(cleaned) == 12:
        return cleaned.zfill(13)

    # EAN-8 (8 digits) → EAN-13 via zero-padding: without this, an EAN-8
    # and its EAN-13 form would never collide, producing duplicate items.
    if len(cleaned) == 8:
        return cleaned.zfill(13)

    return cleaned
