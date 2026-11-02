/**
 * UI pattern detectors — written once, read by two consumers.
 *
 * `lint-ui-conventions.mjs` runs the subset listed in BLOCKING and fails the
 * `lint:ui` step of `make check-frontend`; `scan-ui-patterns.mjs` runs all of
 * them and prints counts, so two runs can be compared while a class is being
 * drained. (Neither runs in pre-commit, so neither blocks a commit.) Before
 * this split, a review
 * grepped for a pattern by hand and the gate carried its own regex for the
 * same idea — the report saw the class, the gate saw the one incident that
 * created it, and neither noticed they disagreed.
 *
 * A detector is three things: the name of a mistake, a scan, and a sentence
 * saying what it looks for and why that is wrong. The sentence is not a
 * comment — it is what both consumers print.
 */
import borderWeight from "./border-weight.mjs";
import buttonSizeOverride from "./button-size-override.mjs";
import contrastWash from "./contrast-wash.mjs";
import contentSizeUnpadded from "./content-size-unpadded.mjs";
import destructiveOutsideConfirm from "./destructive-outside-confirm.mjs";
import destructiveAsNeutral from "./destructive-as-neutral.mjs";
import detailNotFound from "./detail-not-found.mjs";
import disclosureIndicator from "./disclosure-indicator.mjs";
import errorMessageAsCopy from "./error-message-as-copy.mjs";
import failureAsEmpty from "./failure-as-empty.mjs";
import fieldBoxClass from "./field-box-class.mjs";
import formatWithoutLocale from "./format-without-locale.mjs";
import fieldRowBaseline from "./field-row-baseline.mjs";
import flex1InAColumn from "./flex-1-in-a-column.mjs";
import iconButtonUnnamed from "./icon-button-unnamed.mjs";
import footerActionRows from "./footer-action-rows.mjs";
import footerHalfWidth from "./footer-half-width.mjs";
import hoverOnlyReveal from "./hover-only-reveal.mjs";
import heavyWeight from "./heavy-weight.mjs";
import labelLineBox from "./label-line-box.mjs";
import labelWithoutField from "./label-without-field.mjs";
import moneyUnformatted from "./money-unformatted.mjs";
import moneyWithoutCurrency from "./money-without-currency.mjs";
import overflowRow from "./overflow-row.mjs";
import sheetScrollLayer from "./sheet-scroll-layer.mjs";
import successPaletteLiteral from "./success-palette-literal.mjs";
import writeActionUngated from "./write-action-ungated.mjs";

export const DETECTORS = [
  borderWeight,
  buttonSizeOverride,
  contrastWash,
  contentSizeUnpadded,
  sheetScrollLayer,
  footerHalfWidth,
  footerActionRows,
  overflowRow,
  destructiveOutsideConfirm,
  destructiveAsNeutral,
  detailNotFound,
  disclosureIndicator,
  errorMessageAsCopy,
  failureAsEmpty,
  fieldBoxClass,
  fieldRowBaseline,
  formatWithoutLocale,
  flex1InAColumn,
  hoverOnlyReveal,
  heavyWeight,
  iconButtonUnnamed,
  labelLineBox,
  labelWithoutField,
  moneyUnformatted,
  moneyWithoutCurrency,
  successPaletteLiteral,
  writeActionUngated,
];

/**
 * The detectors that fail a commit today.
 *
 * A rule joins this list when its class is at zero, not when it is written —
 * a blocking rule with a backlog behind it stops everyone's work and gets
 * turned off, and a baseline of known findings is where a cleanup goes to
 * die. `button-size-override` reported 160 findings when it was written and
 * blocks now that the last one is gone; the narrow `icon-button-size` rule it
 * grew out of guarded one size of the same mistake and has been removed
 * rather than left to disagree with the wide one.
 *
 * `footer-half-width` joined the same way — 27 findings, then `SheetActions`,
 * then zero. Its class is now unreachable from a call site, because the widths
 * live on the row; what the rule guards from here on is a footer built by hand
 * instead of from the component. `overflow-row` the same, once `TabsList`
 * started scrolling its own tabs: the only finding left to make is an explicit
 * `scrollable={false}` with nothing else to scroll.
 *
 * `destructive-outside-confirm` reached zero mostly by learning to read: it
 * had been matching the `variant` prop of anything, so `<ConfirmDialog
 * variant="danger">` — the exception it exists to allow — and `<Badge
 * variant="danger">` made up two thirds of its 37 findings. Three real ones
 * were fixed and four are exceptions carrying their reason at the call site.
 *
 * `field-box-class` was written and drained in one pass: 42 findings, all of
 * them a width or a margin one element too far in, none of them visible on
 * screen until a field sat in a row beside something else.
 *
 * `label-line-box` the same, and for the same reason: 41 labels an inline box
 * held about 8px too tall, invisible until one of them sat in a grid row
 * beside a `DateInput` that renders its own. Three of its first findings were
 * prose in doc comments and five were a `const` the rule could not read —
 * both now handled in `lib.mjs`, because a rule that reports what it cannot
 * read teaches everyone to skim its output.
 *
 * `footer-action-rows` and `disclosure-indicator` joined at zero without a
 * reporting stage at all, which is unusual and worth saying why. Both classes
 * had exactly the handful of members the change that wrote them had just
 * migrated — two multi-row footers in the whole repo, one bare `<select>`, one
 * section header standing 8px taller than the controls beside it. A rule with
 * an empty class is cheap to block on and there was nothing to drain.
 *
 * `disclosure-indicator` guards the *size* of the indicator inside
 * `components/ui/` only, and that is a deliberate limit rather than an
 * oversight: §2.10 is about form controls, while the ChevronDown on a card
 * row, a tree node or an accordion is a different element at sizes from 10 to
 * 16, and nobody has decided what those should be. Claiming them would make
 * the rule assert something no guideline says.
 *
 * `content-size-unpadded` blocked its way in like the rest: the
 * class was 31 call sites asking for a size that pins no height and stating
 * no padding either — see its note at the BLOCKING set.
 *
 * `money-without-currency` joined at zero after draining its own class in the
 * same change: 12 call sites, eleven of them in `stats`, all rendering
 * "0.00 ?" on screens that had the currency a prop away. It guards the
 * one-argument call rather than the missing locale, which is the wider
 * mistake — the two-argument form still renders "PLN 0.00" where the
 * interface says "0,00 zł" — because that class has fifteen members left and
 * a rule with a backlog behind it is a rule that gets switched off. `useMoney`
 * is what drains it; the rule tightens when the last direct call is gone.
 *
 * `money-unformatted` is `money-without-currency` read from the other end:
 * that rule guards the formatter's arguments, this one guards the amounts
 * that never reached a formatter at all. Eight findings, five of them in the
 * production module, which formats money correctly in eight places and
 * printed "0.00" raw in five — the same figure the tab next door writes as
 * "0,00 zł". It reads JSX text position only, because an amount inside an
 * `<input value=…>` is a figure being edited, not a price being quoted, and
 * because `{` is otherwise the commonest character in the corpus.
 *
 * `error-message-as-copy` is the first rule here that reads `.ts` as well
 * as `.tsx`, because half of its class lived in hooks that hand a component a
 * finished sentence. It drained in one pass — 20 call sites showing axios'
 * "Request failed with status code 400" where the server had written a
 * reason, two of them branching on a substring of that library sentence and
 * therefore on a string no contract promises. It matches the read, not the
 * render, and that is deliberate: a message extracted into a variable and
 * shown three lines later is the same mistake, and the variable is where it
 * can still be fixed.
 *
 * `success-palette-literal` joined blocking in the change that wrote it.
 * A manual review counted one finding — an emerald status dot in the
 * equipment menu — and the scan found three more greens it had missed: a
 * warranty icon, a received-row tint, a summary check. All four were the
 * same one-line swap to `success-*`, the example-widgets swatch became the
 * first `palette-identity` exception (a colour the user picks as identity
 * is not a status), and the class started at zero. The `red-*` family is
 * not claimed: `destructive` has no 50–900 scale, so each red finding is a
 * design decision rather than a swap, and is left to the screens that own
 * it.
 *
 * `destructive-as-neutral` is the other side of `destructive-outside-confirm`,
 * written when the approvals workflow list shipped a Delete in
 * `variant="ghost"`. That detector reads the variant; this one reads the i18n key,
 * because the visible label is translated and the key is not — a destructive
 * action disguised as a neutral one cannot be caught by colour. It opened
 * reporting 33 call sites across twelve modules, so it reports rather than
 * blocks: a blocking rule with that backlog would be switched off. It skips
 * variants given as expressions — the §2.13a state switch, destructive in one
 * state only, is a judgement a static read cannot make.
 *
 * Its class drained to zero in one pass, and the shape of it is worth
 * recording: twenty-seven of the thirty-two were the variant done by hand.
 * `variant="ghost"` with `className="text-red-600 hover:bg-red-50"` beside
 * it is `ghostDanger` spelled out, one call site at a time, each with its own
 * shade — red-500 here, red-600 there, one with a `dark:` pair and one
 * without. The rule reads the key rather than the colour, which is why it saw
 * them: they were destructive whatever they were wearing.
 *
 * Five are exceptions, and all five say the same thing in different words —
 * the act is not destruction. Retiring an asset is a status change and the
 * register keeps it. A threshold sheet's Remove switches an alert off. Three
 * more drop a row from a form nobody has saved yet: a bulk-add entry, a
 * process step in a draft, a row of an import nobody has accepted. Each
 * carries its reason at the call site, because a list of paths is where a
 * rule goes to be forgotten.
 *
 * `detail-not-found` joined at zero in the change that drained its class.
 * Eleven detail pages answered the same 404 six different ways — a bare
 * sentence with no exit, a red block quoting axios, "Failed to load" over a
 * record that is simply gone, and "Try again" on a request the server had
 * already refused. The rule the fix left behind was written down once before,
 * for three screens, and never travelled to the other eight; a rule that
 * depends on the next author having read the last plan is not a rule.
 *
 * It read only the files named `…Detail….tsx` inside a module's `pages`
 * directory, on the argument that a wider version would have to guess which of
 * a page's queries reads the record. The guess turned out to be cheap — a page
 * that takes `id` off the route and passes it to a hook is reading that record
 * — and the narrow version was missing three screens, one of which answered
 * every failed request with "Purchase order not found". The name is
 * kept as a union with the behavioural test, so nothing that was checked stops
 * being checked; the name half keeps the guard that stops it claiming a page
 * which reads no record at all.
 *
 * `failure-as-empty` joined the same way, at zero, in the change that drained
 * the last nine of its class. Its class was the expensive one of this series:
 * fifteen surfaces across four modules, each fixed on its own, each looking
 * exactly like the next one nobody had found yet.
 *
 * `icon-button-unnamed` was written long before it blocked, and spent that
 * time asking the wrong question: it read the `size` a button declared rather
 * than what the button contained. That is the spelling of the mistake, not the
 * mistake. Eight unnamed padlocks on the period-closure screen sat in
 * `<Button size="sm">` and never entered the candidate set; nor did the
 * desktop half of a show-more toggle whose mobile twin, three lines further
 * down the same file, declared `size="iconSm"` and was reported.
 *
 * The size test is kept as one half of a union, so nothing that was checked
 * stops being checked, and the other half reads the children. Two things
 * needed care there. Elements are walked rather than matched — a lazy regex
 * for "an element" swallowed a `<span>` up to the `/>` of the icon beside it,
 * taking the visible words with it and claiming the language switcher. And a
 * ternary is read branch by branch, because the commonest icon-only button in
 * this repo is a toggle: judged whole, `{expanded ? <ChevronUp /> :
 * <ChevronDown />}` keeps the condition's name and looks like text. Anything
 * the rule cannot expand keeps a button out of the findings rather than into
 * them.
 *
 * Its class was 27 controls, and what they had in common is worth naming: a
 * `title`. Eleven of the 27 carried one, which is why they read as done — and
 * a tooltip never appears on a touch screen and several readers skip it. The
 * two halves of one row action in `StorageItems` say it best: the table
 * variant names the button, the card variant, the one a finger uses, did not.
 *
 * Two rules were considered and deliberately not written. The first: a
 * separate guard on `h-auto` in a button's className. `button-size-override`
 * already covers it, and covers it better — the mistake is not the class, it
 * is any geometry answering a size that pins the same dimension at a
 * breakpoint, and `h-auto` is one spelling of that. A second rule for one
 * spelling is how a wide rule and a narrow one end up disagreeing about the
 * same class.
 *
 * The second: a guard on any raw `<button>` carrying a height or a vertical
 * padding, meant to catch a section header used as a form control. It matches
 * 21 elements, and nearly all of them are right — a day cell in `DateInput`, a
 * swatch in `ColorSwatchPicker`, a cell in `EmojiPicker`. A rule whose output
 * is mostly correct code teaches everyone to skim it, so the disclosure header
 * is guarded by `disclosure-indicator` instead, where the thing being asserted
 * is written down in §2.10.
 *
 * `write-action-ungated` was written reporting 24 findings across twelve
 * modules and joins this set now that they are gone. The class had been found
 * and fixed three times page by page — the shell modules first, then
 * equipment's templates, then documents — which was the argument for counting
 * it in one place rather than finding it a fourth time by hand; the fourth
 * time it was counted, and the count went to zero.
 *
 * Two of its 24 were never defects. One page asked through a hook the rule
 * did not know the name of, and one is served without an account at all —
 * both now handled by the rule rather than by remembering them.
 *
 * `flex-1-in-a-column` joined at zero, the `footer-action-rows` way. Its
 * whole class was found by measuring one screen across the mobile breakpoint:
 * a public attestation page whose two buttons stand 20px tall on
 * a phone and 44 on a desktop, because `flex-1` in a column stakes the
 * button's *height* on the parent's layout — `flex-basis: 0%` becomes the
 * size along the main axis and displaces what the size variant pinned, so
 * the tool written for the `sm` breakpoint does its worst exactly where
 * fingers aim. The shape search found one more member, a shopping-list modal
 * footer, broken the same way; the fix both took (`w-full sm:w-auto`) is the
 * one the print-preview footer already used, so the class drained in the
 * change that wrote the rule. It reads the direct parent only, because a
 * button is a flex item of the container that wraps it and of nothing
 * further out, and it gives up when that parent's className is built by
 * `cn(...)` — a rule that guesses reports correct code.
 *
 * `format-without-locale` joined at zero in the change that drained its
 * class: thirteen screens printed a number, a percent, a quantity or a day
 * with the browser's own conventions — `toLocaleString(undefined, …)` beside
 * figures that already used the reader's mark. Most of them were invisible in
 * the environment where they were found, because the browser there was set to
 * the interface's own language, which is the shape of every bug in this
 * class: it is only visible from outside. The rule names the declined
 * argument rather than the missing one, because the single call left in the
 * app that passes no locale at all writes a timestamp into the stock-take
 * CSV export — a value meant for a file, not for a reader.
 *
 * `contrast-wash` joined at zero in the change that drained its class.
 * Its shape came out of a contrast check on /inventory/stats: a tile
 * labelled in `text-amber-500` on a `bg-amber-500/10` wash of the same hue
 * measured 1.99:1, its blue neighbour 3.29:1, and the same pattern kept
 * surfacing under other names — deltas in `text-amber-600` (3.19:1), an
 * equipment widget's amounts, a 10px launcher counter at 1.04:1. Thirty-odd
 * literals across a dozen files, every one fixed to the tint pair the theme
 * already carries (`bg-<status>-50` + `text-on-<status>`, the primary hue
 * with `text-primary-700 dark:text-primary-500`), so the rule started
 * blocking instead of reporting. It reads string literals rather than
 * `className` attributes because the pair often lives in the string a
 * severity helper returns; it skips `dark:`-prefixed halves because
 * `dark:bg-red-500/10 dark:text-red-300` is the blessed dark rescue, not the
 * mistake — the mistake is a light-theme pairing, and that is where it
 * bites.
 */
/**
 * `label-beside-its-field` is the one entry here that is deliberately a subset
 * of a rule that still reports. `label-without-field` names a real class of
 * 155 findings, and the doctrine above says a rule with that backlog must not
 * block — but a third of that backlog was one shape with one fix: a bare
 * `<label>` written above a house field component, which takes a `label` prop
 * and wires the id and the `htmlFor` itself. Draining it took the wide rule
 * from 155 to 97 and cost nothing in judgement, because there was none to
 * make.
 *
 * The narrow rule holds that ground while the rest drains. Every finding it
 * can make is also a finding of the wide one, never a second opinion, so the
 * two cannot end up disagreeing the way a wide and a narrow rule usually do.
 * When `label-without-field` reaches zero it blocks on its own and this rule
 * is deleted rather than left to duplicate it. It has: the wide rule drained
 * and now blocks in this set — so `label-beside-its-field`, the
 * narrow subset that held the ground until then, is deleted with its work
 * done, exactly as this note promised.
 */
/**
 * `content-size-unpadded` joins at zero, the footer-action-rows
 * way: 31 buttons as tall as their own text — pagination chevrons, tab
 * pairs, "show more" toggles — each given the rhythm at its call site
 * (`py-2 min-h-11 md:min-h-10` for a row of text, the icon form where the
 * button is a square), which is the fix the rule itself advises.
 */
/**
 * `heavy-weight` joins at zero in the change that wrote it. The typography
 * table (§1.2) retires `font-bold` outside monospace code, and the rule reads
 * the three shapes that need no reading of intent to be wrong — the seven in a
 * class with `uppercase`, on an `<h1>`–`<h3>`, or beside `text-xs` — each a
 * second layer of emphasis where the table gives the job to `font-semibold`
 * (titles) or `font-medium` (labels). The class was already nearly empty when
 * the rule was written (the table's own rewrite had drained it), so it blocks
 * from day one the way `footer-action-rows` and `disclosure-indicator` did.
 * Weight where the seven carries information — a monospace code, a numeric
 * tile whose figure is its only content — is outside the rule's shapes or
 * takes the call-site marker with a sentence reason.
 */
export const BLOCKING = new Set([
  "border-weight",
  "content-size-unpadded",
  "button-size-override",
  "contrast-wash",
  "destructive-as-neutral",
  "destructive-outside-confirm",
  "detail-not-found",
  "disclosure-indicator",
  "error-message-as-copy",
  "failure-as-empty",
  "field-box-class",
  "field-row-baseline",
  "flex-1-in-a-column",
  "format-without-locale",
  "footer-action-rows",
  "footer-half-width",
  "heavy-weight",
  "hover-only-reveal",
  "icon-button-unnamed",
  "label-line-box",
  "label-without-field",
  "money-unformatted",
  "money-without-currency",
  "overflow-row",
  "sheet-scroll-layer",
  "success-palette-literal",
  "write-action-ungated",
]);

export function byName(name) {
  return DETECTORS.find((d) => d.name === name);
}
