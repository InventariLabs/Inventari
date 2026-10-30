# Inventari — why the UI rules are what they are

The record behind [`UI_GUIDELINES.md`](UI_GUIDELINES.md): the measurements and incidents each rule
grew from. The rules themselves live in the guidelines and nowhere else; this file only says why, so a
rule can be read and applied without it. Sections are numbered after the rule they explain.

## §1.2 Typography

**Each weight has one job.** Weight stopped carrying information once `font-semibold` covered twelve
sizes from 7px to 24px — 613 call sites, 45% of every weight declaration, the page title and a 10px
caption alike. With one weight spanning the range, hierarchy rested on size and colour alone and the
product read as flat. The micro-label once carried the heavier weight in the role table, which
inverted the pair of label roles it belongs to.

**Uppercase is a label role.** Counted as visible runs of uppercase on one screen: `maker` 51,
`recipes` 47, `inventory` 6 — one product, an eightfold spread. Uppercase means "this is a label, not
content", and the signal dies when fifty things are labels, while the costs stay: no word shape to
read by, Polish diacritics losing definition at 10px, and truncation eating whole words
(`PCS.` → `PC…`).

## §2.0 Who owns which class

`h-auto` on `<Button size="sm">` (`h-11 … md:h-8`) beats `h-11` and leaves `md:h-8` standing: the
button obeys below `md` and ignores the call site on every desktop. Nothing errors, nothing looks
wrong in the diff, and a unit test asserting the className passes — which is why this exact shape
shipped three times before a rule caught it.

## §2.10 Form control geometry

In the "New document" dialog, as measured, one section held a 40px/8px-radius select, a second
identical select, and a 44px/12px-radius date field directly below them — plus a border that was 1px
on lists and 2px in dialogs. The label-to-field rhythm measured 12 / 0 / 19 / 7px where forms spaced
their own labels. Nine call sites once used `labelClassName` to undo the canonical label geometry and
were snapped back to it. One storage sheet showed a system arrow, a lucide chevron and a third
indicator within a single column.

## §2.11 Heading levels

Six screens across the trade modules went `h1` → `h3` with no `h2`, which a screen reader reads as a
missing level.

## §2.12 Borders

A documents list at 390px carried **109 outlined elements**: one per card, one per badge inside those
cards, one per filter chip, plus every control. Nothing stood out, because everything was framed.

## §2.13 Horizontal scrollers

A row with `overflow-x-auto` and nothing else hid its overflow behind a hard edge — the status filters
ended at "Confirmed" with no sign that "Completed" and "Cancelled" were one swipe away — while the
browser's own scrollbar rendered as a thick grey bar that read like a UI element.

## §2.13a Destructive actions in a row

Three modules shipped the same row: `Edit | Deactivate`, `Edit | Confirm | Cancel` — the destructive
action flush against the safe one, in the same weight, with the warning appearing only on hover. On a
touch screen there is no hover, so the first signal arrived after the tap. Some filled red buttons are
right anyway — a screen that expands into its own confirmation step instead of opening a dialog, a
remove chip sitting on a photo where a ghost button disappears into whatever the user photographed —
which is why the gate takes a marker with a reason rather than a list of exempt paths: a list with no
argument attached is where a rule goes to be forgotten.

## §2.13c A control hidden by transparency

Three rows hid a destructive action behind `opacity-0` and a hover class: remove a member, delete a
notification, delete a file from object storage.

## §4.3 Bottom sheet pattern

**Footer widths.** Every footer that hand-rolled the action row wrote `flex-1` and stopped: that is the
phone half of the rule, and without the `sm:` half the dialog split down the middle on a desktop.
Hand-rolling the bottom inset is how footers ended up with `pb-safe-bottom`, a utility this project
does not define and which therefore did nothing.

**One Escape closes one layer.** Measured at 390px, one press took down the date picker _and_ the
campaign dialog behind it, with everything typed. The same shape appeared the other way round: a sheet
opened from inside another sheet — the location list under the storage wizard's first step — where
one press used to close the list _and_ raise the wizard's discard question over it, with a destructive
Discard a click away.

**A full-screen panel is a sheet on a phone.** `SearchableCombobox` was a Radix popover in both
places. Its panel is around 550px of header, search field and list — more than fits under a trigger
halfway down a form — so Radix flipped it above the trigger and clamped it against the top of the
_layout_ viewport, which on a phone is behind the browser's own chrome. Measured at 390x620: the panel
started at -118px and the search field, the first thing the reader is meant to type into, sat
entirely off-screen between -48px and -4px.

**A sheet inside `DialogContent`.** Measured at 390x620 in the putaway-rule dialog, the panel ran 88px
below the bottom of the screen; the date picker has the same geometry there today.

## §14.1a Row height on the desktop list

The list this rule was written for showed six rows out of 584 records, because it had grown a `py-4`
cell around a 48px thumbnail. Six rows is a viewer, not a list: the reader scrolls past a hundred
screens to reach the end of a warehouse.

## §14.1b The phone card's content target

`ItemMobileCard`'s row button — the thing that opens the product — is left under the 44px floor on
purpose. Measured at 390px it is **228 × 38**: five times the floor on the axis a thumb travels along,
and six pixels short on the other. Its height is what the row carries — name, identifiers, metadata —
and the card around it is 118px tall, set not by the row but by its neighbours: a 44×44 quantity badge
on the left, two stacked 44×44 actions on the right.

The floor is written for controls: `h-11 md:h-10`, a height a call site declares. A full-width row
between two columns of controls is not that — the reader aims at the row, and the 44px targets are
already at both ends of it. Padding the button to 44 would add 6px to every product in a list built
for scrolling, or need a negative margin to hide the padding again.

## §14.2 Location vocabulary

The app used to say Storages / storage location / target location / Locations / Warehouse for the same
thing, leaving no way to tell whether those were five things or one. In Polish "Magazyn" became the
name of the warehouse module, which received the word when the container lost it.

The production sheet and the cook-for-stock window carried "Magazyn wyjściowy" / "Stockage de
sortie" / "Almacén de salida" one line under a subtitle promising a _target_ place; in Polish that is
the exact reverse of the movement, and the mistake is silent — nothing downstream questions it.

## §14.3 The record is a Product

The record used to be two things at once: the sidebar and the page title said "Items" while the
subtitle directly beneath them said "Browse and manage your products", and one sentence in the
bulk-edit window used both nouns in a single breath — "applied to all 3 selected products …
unchanged for each item".

## §14.5 One ellipsis

Three periods wrap and truncate as three glyphs, and a screen reader may read them out as "dot dot
dot"; the gate exists so a new label cannot pick the losing side by accident.

## §14.6 The WMS session row

The receiving row used to stack name, quantity, an uppercase 10px status and then the actions
underneath — four lines for facts the picking row held in one, with a second vocabulary for the state
and the actions out of the place the eye had learned.
