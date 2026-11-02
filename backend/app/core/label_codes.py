"""What a label's short code looks like — said once, for both sides.

A short code is a prefix, a hyphen and a body: ``STM-2BWO``, ``B12-6UPR``,
``DELL-LAT5540``. Two rules about that shape used to live apart, and they
disagreed on one character class. The creation schema invited digits in
the prefix — its own field description offered ``B12`` as the example —
while the recognition pattern took letters only, so a label generated as
``B12-6UPR`` was printed, stuck to a shelf, and then met
``SCAN_UNRECOGNIZED``: "no product, label, place or document matches",
said about a row sitting in that organization's own ``label_pool``.

The two limits here are **not** required to be the same number, and the
difference is the point:

* ``LABEL_PREFIX_MAX_LENGTH`` is what this app will *create*. It stays
  short because the prefix shares a printed sticker with a four-character
  body, and the generated code has to fit the sticker as well as the
  column.
* ``LABEL_CODE_PREFIX_MAX_LENGTH`` is what the scanner will *recognise*.
  It is wider on purpose: a row in ``label_pool`` can predate whatever cap
  the schema carries today, and a sticker already on a shelf has to keep
  scanning. Recognition is a superset of creation, and a test asserts it
  rather than leaving it to whoever edits one of the two next.

The character class is shared outright, because that is where the two
drifted apart and the drift produced a dead sticker.

The hyphen is what keeps a label code distinct from a plain barcode,
which is digits and nothing else (``BarcodeScanProvider``). Digits in the
prefix therefore cost that distinction nothing.
"""

import re

#: Characters a prefix may be made of, on either side. The generator
#: uppercases what it is given, so the stored code only ever holds the
#: upper half of this.
LABEL_PREFIX_CHARS = 'A-Za-z0-9'

#: Longest prefix this app will generate a code for.
LABEL_PREFIX_MAX_LENGTH = 5

#: Longest prefix the scanner will recognise — at least the above.
LABEL_CODE_PREFIX_MAX_LENGTH = 12

#: Longest body the scanner will recognise. The generator draws four.
LABEL_CODE_BODY_MAX_LENGTH = 12

#: Pydantic-side constraint on a prefix a caller may ask for.
LABEL_PREFIX_PATTERN = rf'^[{LABEL_PREFIX_CHARS}]+$'

#: Recognises a stored ``short_code``. Shared so the provider chain and the
#: legacy scan service agree on what is a label.
LABEL_CODE_PATTERN = re.compile(
    rf'^[A-Z0-9]{{1,{LABEL_CODE_PREFIX_MAX_LENGTH}}}'
    rf'-[A-Z0-9]{{1,{LABEL_CODE_BODY_MAX_LENGTH}}}$'
)

assert LABEL_CODE_PREFIX_MAX_LENGTH >= LABEL_PREFIX_MAX_LENGTH, (
    'the scanner must recognise every prefix the generator can produce'
)
