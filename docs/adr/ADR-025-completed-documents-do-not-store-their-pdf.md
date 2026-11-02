# ADR-025: Completed Documents Do Not Store Their PDF

## Status

Accepted — 2026-10-27.

## Context

A document's PDF is produced when someone presses **Download PDF**. It is
rendered from the document's data and from the print template in force at
that moment (`document_pdf_service.py`), and nothing of the result is kept.

Part of the data it is rendered from does not move once a document is
confirmed: lines, quantities and prices cannot be edited (a receipt line's
target shelf can still be named until its goods are booked), the partner is
copied onto the document as a snapshot (name, tax number, address), each line
keeps the name and price it was written with, and a completed document
changes only through a correction document. Other inputs are read live each
time: the print template, the document type's settings (title and whether
price and tax columns show), the issuer block at the top (the organization's
own name, address and logo), and the names of the locations the document
refers to. Two prints of the same document can therefore differ in layout,
in the issuer block, in which columns show and in a renamed location, while
the document's lines, quantities, prices and partner stay the same.

Some tax regimes keep a delivery note, or any document sent to the other side,
as a commercial letter, for a number of years, in the form it was sent. The
question raised by the German GoBD analysis and the Italian DDT practice is
whether re-rendering from immutable data meets that, or whether the file as
printed has to be kept. Which of the two a tax authority accepts has not been
verified for any country, and the answer differs by country and by whether the
document was in fact sent.

## Decision

Completing a document does **not** store a PDF, and does not record a template
version. The stored record is the data; the PDF is a view of it.

The user guide (10.11) says so in plain words: a reprint reads the template,
the type's settings, the issuer details and the location names of the day; a business that must keep a document *as sent* saves the
file when it sends it, or keeps the email it went out in.

## Why

- **Inventari sends almost nothing.** The one document it emails itself is a
  purchase order, and it goes out as a mail attachment rendered at the moment
  it is sent. A delivery note or an invoice is printed or saved by a person, who is holding
  the very copy the retention rule is about. A stored second copy would be a
  second record that can disagree with the first, kept for a duty that the
  business already meets with the file in its hand.
- **A stored PDF is a new class of data.** It needs file storage, a migration,
  a place in backups and restore, a size and retention policy, and an answer
  for personal-data erasure — the same partner address now lives in a file
  the database cannot correct. Every completed document would cost that, for a
  requirement not yet shown to apply.
- **A template version alone does not solve it.** Recording which template
  printed a document says what to look for, not how to reproduce it: templates
  are editable organization data, and the issuer block is not part of them.
  Making a reprint faithful would mean freezing templates and issuer details
  too, which is a different feature.
- **The risk is bounded and stated.** The document's lines, quantities,
  prices and partner cannot change, so a reprint never states a different
  transaction; what differs is presentation and the current names of the
  issuer and locations, and the guide lists those inputs so the reader knows
  where the exception lies.

## Consequences

- Nothing in the schema changes, and no backup or erasure procedure gains a
  file store.
- The record-keeping page in the user guide carries the limit, so a business
  can put the rule "save what you send" into its own procedure description.
- If a country analysis shows that a re-rendered copy does not satisfy a
  retention rule that Inventari's own sending (email of an order, a future
  send of a delivery note) triggers, the decision is reopened for that path
  only: store the file at the moment of **sending**, beside the send record,
  rather than at completion.
