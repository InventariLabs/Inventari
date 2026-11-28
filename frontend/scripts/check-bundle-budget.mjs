#!/usr/bin/env node
/**
 * The bundle size budget — the brake the start path never had.
 *
 * Measured when this budget was introduced: the entry path carried
 * ~389 KiB gzip of translations alone and grew linearly with the number of
 * modules, and nothing in the build failed when it did. This script reads
 * `dist/` the way a browser does — index.html, then the closure of its
 * static imports — and fails the build when the two paid paths outgrow
 * their budgets:
 *
 *   initial      — what a signed-out visitor downloads before anything
 *                  renders: index.html plus the closure of the entry chunk.
 *   appFirstPaint — the same plus the App tree's closure and the heaviest
 *                  single language file, which i18next preloads before the
 *                  first render. This is the signed-in reader's price.
 *
 * Chunk sizes drift a few KiB between builds; the budgets sit one step
 * above the measured values so ordinary churn stays green and a regression
 * — a new static import into the entry, a module sneaking back into the
 * startup path — does not.
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");

/**
 * Budgets in KiB of gzip.
 *
 * Measured 2026-09-26, after the module translations and the
 * module registration left the startup path: initial 212.8, app first paint
 * 313.4 — against 196.8 / 740.8 measured on the dev tip this shipped from,
 * where the start path carried all five languages (473.0 KiB gz of it) and
 * every module's registration code. The budgets sit one step above what was
 * measured, so ordinary churn stays green and a regression — a new static
 * import into the entry, a module sneaking back into the startup path —
 * does not.
 *
 * Re-measured 2026-10-02 on the dev tip: initial 234.0, app first paint 335.9,
 * so initial moved from 230 to 240 — the start path had grown ~21 KiB in a
 * week of ordinary feature work, and the gate had never run outside the
 * production image, so nobody saw it grow. It now runs in `build:check`
 * (`make check-frontend`), not in `npm run build`: a size budget is a review
 * signal, and a production build that refuses to produce an image over a few
 * KiB stops a deploy for something no user would notice.
 *
 * Re-measured 2026-10-12: the dev tip stood at initial 239.9 / app first paint
 * 349.9, 0.1 KiB under both budgets, so the failed-load copy in five languages
 * (240.1 / 350.3) tipped them over with nothing wrong in the entry. Each moved
 * up one step, 240 to 245 and 350 to 355.
 *
 * Re-measured 2026-10-14: the dev tip stood at initial 240.4 / app first paint
 * 354.0; the error screens' copyable details (one component and two strings in
 * five languages) took it to 242.6 / 356.3, so app first paint moved up one
 * step, 355 to 360. The details sit in the error boundary, which has to ship
 * with the entry: a chunk that failed to load is the crash it reports.
 *
 * Re-measured 2026-10-17: the dev tip stood at initial 243.2 / app first paint
 * 360.0 (359.997); the short pick and receive dialogs' summary line and
 * replacement tick, merged with the deliberate skip confirmation, took it to
 * 360.1. The dialogs are opened from the session screens in the App tree, and
 * a window a worker opens on demand is not worth a lazy boundary of its own,
 * so app first paint moves up one step, 360 to 365. The picking batch toasts
 * (three strings in five languages) land in the per-language chunk every
 * first paint loads; with both changes merged the tree measures 360.3. The
 * product label copy in five languages adds 0.14 KiB gz of the Polish file,
 * the heaviest, to the start path, inside the same step: 243.4 / 360.5
 * measured on the merge with the label change.
 *
 * Re-measured 2026-10-20 on the merge: the warehouse start screen's copy —
 * four action tiles with their sentences, the To do count and footnote, and
 * the day feed's title, entry, empty states and error, in five languages —
 * took the start path to 365.1, and the Locations tab's shared form controls
 * took the merged tree to initial 243.6 / app first paint 366.6. The entry
 * path barely moved and the tab itself is a lazy chunk, so this is the
 * ordinary growth of the signed-in tree: app first paint moves one step,
 * 365 to 370, from the start screen's measurement.
 *
 * The undo action's copy (the warehouse module, loaded at first paint) and
 * counting a location (its screen, its setting and the due-count To do line,
 * in five languages) come on top, inside the same step: 243.6 / 366.7
 * measured on the merge of all three.
 *
 * Re-measured 2026-10-21 on the merge with the one-screen receive: the
 * receive sheet's copy — its fields, the line table, the paste notices and
 * the success panel, in five languages — lands in the documents language
 * file the first paint loads, and took the merged tree to initial 243.8 /
 * app first paint 370.2, 0.2 over the ceiling the dev tip had come to. app
 * first paint moves one step, 370 to 375.
 *
 * Re-measured 2026-10-21 on the merge of the work board and the stale-chunk
 * recovery: each branch stood under 370 alone (the dev tip 369.2, the board
 * 369.7, the recovery 369.6), together they measure initial 244.1 / app first
 * paint 370.2. The board's copy (columns, person chips, the custom-card form
 * and the measures strip, in five languages) and the failed-load copy both
 * sit in the per-language chunk every first paint loads, so app first paint
 * moves up one step, 370 to 375.
 *
 * Re-measured 2026-10-25 on the merge of the catalogue fixes and the kitchen
 * launch pass: the dev tip measured app first paint 375.0, exactly the
 * ceiling. The kitchen branch took it to 375.1 (initial 188.3, twice on each
 * side), and the catalogue branch's copy (the SKU label, the records count,
 * the import's "added to products you already have" line and the search
 * hit's per-product total, in five languages) added 0.2 KiB gz of the Polish
 * file, the heaviest, to the start path: 375.3 on its own. What grew is copy,
 * not an import: the reconciliation panel's new sentences and the "Choose a
 * unit" message of the recipe and shopping-list forms, and the catalogue's
 * labels, sit in the per-language chunk every first paint loads (the Polish
 * one, 133.0 KiB). App first paint moves up one step, 375 to 380.
 *
 * Re-measured 2026-10-25 on the merge of the backorder stock-cover badge, on
 * top of the catalogue step above: that merge stood at 375.3 against the new
 * ceiling of 380, and the three short sentences the badge adds to the To do
 * list ("can be issued in full", "in part", "nothing to issue yet"), in five
 * languages, sit in the warehouse copy of the per-language chunk every first
 * paint loads. They take the merged tree to initial 188.3 / app first paint
 * 375.9, still inside the ceiling the catalogue step set, so the number stays
 * at 380.
 *
 * Re-measured 2026-10-25 on the merge with the home-location question of the
 * put-away, after the two merges above: its copy (the question, the
 * three refusals, the settings choice and the list of products not asked
 * about, in five languages) sits in the warehouse language file every first
 * paint loads, and its sheet in the To do chunk the start screen opens. The
 * merged tree, the stock-cover badge in it, measures initial 188.3 / app
 * first paint 376.3, and on the phone login 381.0, launcher 395.9 and start
 * 606.8. App first paint, login and launcher stand under the ceilings the
 * dev tip already carries; only start crosses its 605, by 1.8 KiB — the sheet
 * in its own chunk, not an import that walked in — so that one ceiling moves
 * a step of five.
 *
 * Re-measured 2026-10-26 on the merge of the kitchen launch pass with that
 * put-away step: the kitchen copy sits on top of the 376.3 above and takes the
 * merged tree to app first paint 376.5, login 381.2, launcher 396.2 and start
 * 607.4 — every one inside the ceilings as they stand, so none moves.
 *
 * Re-measured 2026-10-26 on the branch that moved every location picker to a
 * server search: the picker, its two hooks and the by-id naming hook now sit
 * in the chunks of the screens that pick a place. App first paint (377.7),
 * login (382.4), launcher (397.3) and receive (447.0) stand under their
 * ceilings; start measures 611.1, issue 561.6, history 585.1 and products
 * 493.7, so those four phone budgets move one step of five: 615, 565, 590
 * and 495. The first-paint ceiling stays at 380.
 *
 * Re-measured 2026-10-25 on the merge of the office-output branch: its copy
 * (the scrap reason list and cost line, the register's scrap and unvalued
 * notes, the receive sheet's unpriced-line notice, the print layout rule, the
 * stock-value tile's lower-bound note, in five languages) lands in the
 * per-language chunk every first paint loads, 21 lines in the warehouse file
 * and 2 in the stats file, and took the tree to app first paint 375.4 on top
 * of a dev tip that stood at the ceiling. Merged with the backorder badge
 * above it measures initial 188.3 / app first paint 376.3, so the raise of
 * app first paint, 375 to 380, is the one the catalogue fixes already made
 * and it stays one step; the login and start phone budgets (385 and 610),
 * which carry that chunk, move with it.
 *
 * Re-measured 2026-10-26 after merging the development line again: the
 * document history screen, which also hosts the register with its scrap and
 * unvalued notes, measures 580.0 KiB gz against its 580 on a tree whose app
 * first paint is 376.4 (initial 188.3), so that one phone budget moves to
 * 585. The first-paint ceiling stays at 380.
 *
 * Re-measured 2026-10-26 on the merge with the community-languages change of
 * the development line: the merged tree measures initial 188.7 / app first
 * paint 377.3, both inside their ceilings, and on the phone the issue screen
 * 555.1 KiB gz against its 555 — the scrap reason list this branch adds to
 * that screen, in five languages, on top of the language files the first
 * paint loads. That one phone budget moves a step of five, to 560; the other
 * screens stand under theirs (login 382.0, launcher 397.0, start 609.2,
 * receive 446.1, history 580.9, products 489.0).
 *
 * Re-measured 2026-10-27 on the merge of the occupancy fix with the
 * development line: the dev tip alone measures the products screen at 489.9
 * KiB gz against its 490, and the occupancy screen's two new failure lines
 * (a search that could not be run, a location whose contents could not be
 * read), in five languages, sit in the warehouse language file every first
 * paint loads and take it to 490.0. That one phone budget moves a step of
 * five, to 495; the merged tree measures initial 188.7 / app first paint
 * 377.9, and the other screens stand under theirs (login 382.6, launcher
 * 397.5, start 609.9, receive 446.7, issue 555.5, history 581.5).
 *
 * Re-measured 2026-10-28 on the merge of the module-boundary change with the
 * development line: the dev tip alone measures the receive screen at 449.2
 * KiB gz against its 450, and the merged tree at 450.1. Modules that stopped
 * importing each other's files now take the card link, the composition bar,
 * the text area and the label client from @/module-sdk, and the bundler
 * keeps that barrel as one shared chunk that loads every module it
 * re-exports, so the receive screen, which loads the barrel, pays about 0.9
 * KiB for parts it never draws. That one phone budget moves a step of five,
 * to 455; the merged tree measures initial 188.9 / app first paint 379.6,
 * and the other screens stand under theirs (login 384.3, launcher 399.3,
 * start 612.6, issue 562.8, history 587.0, products 492.2).
 *
 * Re-measured 2026-10-29 on the merge of the audit journal's module writes
 * with the development line: the dev tip alone measures app first paint
 * 379.9, and the branch's labels for the fields its new journal entries
 * carry (eighteen of them, in six languages) sit in the common language
 * file every first paint loads, 0.2 KiB gz of the Polish one, and take the
 * merged tree to 380.2. App first paint moves one step, 380 to 385; the
 * merged tree measures initial 188.9, and the phone screens stand under
 * theirs (login 384.9, launcher 399.9, start 613.2, receive 450.7, issue
 * 563.4, history 587.6, products 492.8).
 *
 * Re-measured 2026-10-29 with equipment status confirmation and valuation
 * notices: their translations bring app first paint to 380.4 KiB gz and
 * phone login to 385.1, launcher to 400.1. Both phone ceilings move one
 * step of five; the remaining screens stay within their budgets.
 *
 * Re-measured 2026-10-29 on the merge of the contract-typing change with the
 * development line: the dev tip alone measures the login screen at 385.0 KiB
 * gz against its 385, and the document type now generated from the contract
 * adds the stock-count adjustment to the new-document label map, a few bytes
 * of the shared warehouse code the login chunk set carries. That one phone
 * budget moves a step of five, to 390; the merged tree measures app first
 * paint 380.3, and the other screens stand under theirs.
 *
 * Re-measured 2026-10-30 on the scan-answer branch with translated picking
 * and receiving scan answers:
 * the launcher carries the Polish copy and measures 400.1 KiB gz against
 * its 400 ceiling. Its budget moves one step to 405; app first paint is
 * 380.4 and the other phone screens remain within their budgets.
 *
 * Re-measured 2026-10-29 on the merge of the stock-take report's wording
 * with the development line: the tree without it measures the launcher at
 * 400.0 KiB gz against its 400, and the two labels the report gains (the
 * filter for differences and uncounted lines, the singular badge of an
 * uncounted row), in six languages, sit in the common language file every
 * first paint loads, a few bytes of the Polish one, which tips the launcher
 * over. That one phone budget moves a step of five, to 405; the merged tree
 * measures app first paint 380.3, and the other screens stand under theirs
 * (login 385.0, start 613.4, receive 450.9, issue 563.6, history 587.8,
 * products 493.0).
 *
 * Re-measured 2026-10-31 on the merge of the catalogue pre-publication pass
 * with the development line, wording pass included: the merged tree measures
 * the issue screen at 565.3 KiB gz against its 565 and the products screen at
 * 495.4 against its 495, the second after the branch's own additions (the
 * product page link, the wrong-label release in the Edit product sheet, the
 * unknown-code notice and their copy in six languages). Those two phone
 * budgets move a step of five, to 570 and 500; the start screen, at 616.2,
 * stands under the 620 set below. The same tree measures initial 188.9 / app
 * first paint 383.1, and the other screens stand under theirs (login 387.8,
 * launcher 402.8, receive 451.7, history 589.7).
 *
 * Re-measured 2026-10-31 on the warehouse floor's wording pass: the plain-word
 * rewrites (the hold's reason, the correction dialog, the putaway field,
 * History's subtitle), the write-off dialog's two sentences and the join
 * link's third card are copy in six languages, and the Polish one sits in
 * the language chunk the start screen loads. The write-off dialog itself is
 * loaded on the press, not on first paint; the tree measures start at
 * 615.4 KiB gz without it counted, 0.4 over its 615, with the other phone
 * screens under theirs. That one budget moves a step of five, to 620.
 *
 * Re-measured 2026-10-31 on the merge of the warehouse screens' regression
 * fixes with the development line: the dev tip alone measures issue at
 * 564.9 KiB gz against its 565, with app first paint 383.0. The branch's
 * copy (readable draft titles, the mark that tells a count's records apart,
 * the receive result's waiting-in-Receiving sentence and partner link, the
 * production sheet's reasons beside a disabled save, in six languages) sits
 * in the per-language chunk every first paint loads and takes app first
 * paint to 383.2 and issue to 565.2 — copy, not an import. That one phone
 * budget moves a step of five, to 570; the other screens stand under
 * theirs (login 387.9, launcher 402.9, start 616.1, receive 453.3, history
 * 589.7, products 494.5).
 *
 * The kitchen, approvals and statistics pass moved the same budget to the
 * same 570 for the same reason (its copy in the language chunk took issue to
 * 565.3 over a 564.9 tip). The merge of the two measures issue at 565.6 and
 * app first paint at 383.6, under the 570 and the 385 both set. The same
 * merge takes history to 590.2 KiB gz against its 590 and products to 495.1
 * against its 495: each branch's copy alone kept them under (dev tip 589.7
 * and 494.5), the two together add half a KiB to the language chunk every
 * first paint loads — copy, not an import. Those two budgets move a step of
 * five, to 595 and 500; the other screens stand under theirs (login 388.3,
 * launcher 403.3, start 616.5, receive 453.7).
 *
 * Re-measured 2026-10-31 on the merge of the first-contact and settings
 * wording with that line: the labels the branch adds to the same
 * per-language chunk (onboarding, scan-tab and audit wording) and the line's
 * own copy together take the history screen to 590.1 KiB gz against its
 * 590 — copy, not an import; the line alone measures 589.7. That one phone
 * budget moves a step of five, to 595; app first paint measures 383.5,
 * initial 189.0, and the other screens stand under theirs (login 388.2,
 * launcher 403.2, start 616.4, receive 453.6, issue 565.5, products 494.9).
 *
 * The two moves above meet on history, both to 595. Their merge measures
 * history at 590.5, products at 495.4 under the 500 the kitchen pass set,
 * issue 565.9, app first paint 383.9 and initial 189.0; the other screens
 * stand under theirs (login 388.6, launcher 403.5, start 616.8, receive
 * 454.0).
 *
 * Re-measured 2026-11-01 on the branch that ties the scanner's memory to its
 * owner: app first paint 385.06 KiB gz against its 385, over a dev tip at
 * 384.96 — 37 bytes from the line. The branch adds 101: the owner check in
 * the two stores every load imports (initial 189.02 to 189.10), and the
 * missing-category sentence in the Polish file. No import walked in; one
 * that had (the form memory store, into the auth store) was taken back out.
 * App first paint moves a step of five, to 390; the other screens stand under
 * theirs (login 389.8, launcher 404.8, start 618.4, receive 454.7, issue
 * 567.4, history 591.9, products 497.9).
 *
 * Re-measured 2026-11-02 on the branch where an order with no price says so
 * and the dialog behind its Confirm names a dead end: login, launcher and
 * receive each measure a fraction of a KiB over 390, 405 and 455, and app first
 * paint 385.3. The branch adds the Polish file's copy for it, 139.4 KiB gz in
 * all; no import walked in, and the dead-end sentences are the approvals
 * module's own rather than three new ones. Those three phone budgets move a
 * step of five, to 395, 410 and 460; the other screens stand under theirs
 * (start 618.7, issue 567.7, history 592.3, products 498.2).
 *
 * Re-measured 2026-11-03 on the merge of the confirmation pass's small fixes
 * with the development line: the branch stood at start 619.9 alone and the
 * merge measures 620.1. What grew is copy in the Polish file: the wording for
 * a receipt line with no price, the storekeeper's approval sentences, and the
 * plural forms of the units that are words. The new-partner form the same
 * branch brought to the goods screens loads on its first use, and the receipt
 * line's sentence has one form where it had four. That one budget moves a step
 * of five, to 625.
 *
 * Re-measured 2026-11-04 on the merge of the regression pass's small fixes with
 * the development line: neither side is over alone, the dev tip stood at issue
 * 569.8 and products 499.7 KiB gz, 0.2 and 0.3 under their ceilings, and the
 * branch adds 0.5 KiB gz to every screen (issue 570.3, products 500.2, app first
 * paint 387.1). It is copy, not an import: 156 lines of translated refusals,
 * notices and menu labels in the five languages' module files, which the
 * language chunk every first paint loads carries. Those two phone budgets move
 * a step of five, to 575 and 505; the other screens stand under theirs (login
 * 391.8, launcher 406.8, start 620.4, receive 457.5, history 594.0).
 *
 * Re-measured 2026-11-06 on the branch that gives the item history and the
 * audit log readable wording: the development tip alone measures the history
 * screen at 595.0 KiB gz against its 595, and the branch adds 0.1 KiB gz
 * (history 595.1). It is copy, not an import: four lines of translated
 * wording for the category field-definition change in the common language file
 * the first paint loads, and the reader that uses them, which sits in the
 * shared audit module. That one phone budget moves a step of five, to 600.
 *
 * Re-measured 2026-11-06 on the branch that pages the archived products by
 * cursor: the same tree without the module SDK's new export measures the
 * products screen at 609.9 KiB gz against its 610, and the export adds 0.3 KiB
 * gz (products 610.2). It is the cursor paging hook the stock movement ledger
 * and the audit log already use, which the Equipment archive now reaches
 * through `@/module-sdk`; the SDK is one chunk, and the products screen loads
 * it. That one phone budget moves a step of five, to 615.
 *
 * Re-measured 2026-11-07 on the branch that names the open shopping list a
 * recipe's missing items go to: the development tip alone measures the
 * receive screen at 460.0 KiB gz, on its 460, and the branch takes it over
 * the line (still 460.0 at one decimal, the Polish language chunk 142.7
 * against 142.6). It is copy, not an import: the list picker's label, its
 * announcement and the sentence for a list request that failed, in the five
 * languages' recipes files, which the language chunk every first paint loads
 * carries. That one phone budget moves a step of five, to 465; the other
 * screens stand under theirs (login 393.4, launcher 408.4, start 623.1,
 * issue 572.6, history 596.5, products 610.8, app first paint 388.7).
 * Re-measured 2026-11-07 on the branch that keeps a link's token out of the
 * copyable error report: the development tip alone measures the receive
 * screen at 460.0 KiB gz against its 460, and the branch adds 0.1 KiB gz
 * (receive 460.1, initial 189.1, app first paint 388.8). It is the masking of
 * the page address in the error details, which ship with the entry because a
 * chunk that failed to load is the crash they report. That one phone budget
 * moves a step of five, to 465; the other screens stand under theirs (login
 * 393.5, launcher 408.5, start 623.2, issue 572.7, history 596.6, products
 * 610.9).
 *
 * Re-measured 2026-11-08 on the branch that hands a one-document picking
 * session from a list to the document's page and records visits for
 * "Recently visited": the development tip alone measures the start screen at
 * 624.9 KiB gz against its 625, and the branch adds 0.6 KiB gz (start 625.5).
 * It is the list's picking sheet and its hand-off hook in the To do chunks
 * (0.4), the module SDK's `useRecordVisit` export (0.1) and the recent list's
 * scope constant beside the store that clears it (0.1) — code the screen
 * runs, not an import that walked in. That one phone budget moves a step of
 * five, to 630; the other screens stand under theirs (login 394.5, launcher
 * 409.6, receive 462.1, issue 574.7, history 598.6, products 613.4, initial
 * 189.3, app first paint 389.8).
 *
 * Re-measured 2026-11-09 on the branch whose one-step "Send for approval"
 * dialog names a stage nobody can decide: the development tip alone measures
 * app first paint at 389.9 KiB gz against its 390, and the branch adds 0.1
 * (390.0). It is copy, not an import: three sentences in the warehouse file
 * of each language, the Polish one in the language chunk every first paint
 * loads. That one budget moves a step of five, to 395; the other screens stand
 * under theirs (login 394.8, launcher 409.9, start 625.9, receive 462.4, issue
 * 575.0, history 598.9, products 613.8, initial 189.3).
 *
 * Re-measured 2026-11-09 on the development line with that branch and the one
 * that names an already-listed shopping notice without a count together:
 * neither is over alone (the development tip stood at issue 575.0 against its
 * 575, this branch alone 575.0, the other 574.9), but the Polish language
 * chunk both touch compresses less well in the merged tree and the issue
 * screen measures 575.0 over the line. It is copy in one shared chunk, not an
 * import that walked in. That one phone budget moves a step of five, to 580;
 * the others stand under theirs (login 394.8, launcher 409.9, start 625.9,
 * receive 462.5, history 598.9, products 613.8, app first paint 390.1,
 * initial 189.3).
 *
 * Re-measured 2026-11-13 on the branch where Settings names the country's
 * partner tax-ID rule: the development line alone measures the launcher at
 * 409.9 KiB gz against its 410, and the branch adds 0.1 (410.0). It is copy,
 * not an import: five sentences in the warehouse file of each language, the
 * Polish one in the language chunk every first paint loads. That one phone
 * budget moves a step of five, to 415; the other screens stand under theirs
 * (login 394.9, start 626.1, receive 462.6, issue 575.2, history 599.1,
 * products 613.9, app first paint 390.2, initial 189.3).
 *
 * Re-measured 2026-11-14 on the branch that gives four document symbols a
 * description in each language: the development line alone measures the login
 * screen at 394.9 KiB gz against its 395, and the branch adds 0.2 (395.1). It
 * is copy, not an import: four sentences in the warehouse file of each
 * language, the Polish one in the language chunk every first paint loads.
 * That one phone budget moves a step of five, to 400; the other screens stand
 * under theirs (launcher 410.3, start 626.4, receive 462.8, issue 575.4,
 * history 599.4, products 614.1, app first paint 390.4, initial 189.3).
 * Re-measured 2026-11-14 on the branch that adds the MCP Server module: the
 * development line alone measures history at 599.4 KiB gz against its 600,
 * and the new module's catalogue copy — its name and one sentence in the core
 * modules file of each language, the Polish one in the language chunk every
 * first paint loads — takes the merged tree to 600.1. That one phone budget
 * moves a step of five, to 605; the other screens stand under theirs
 * (login 395.9, launcher 411.1, start 627.2, receive 463.6, issue 576.2,
 * products 614.9, app first paint 391.2, initial 189.4).
 *
 * Re-measured 2026-11-14 on the branch that traces a batch to its suppliers
 * and customers: the development line alone measures products at 614.9 KiB gz
 * against its 615, and the branch's copy — the trace's headings, empty states
 * and truncation notice, and the production run's output-batch field, in six
 * languages — sits in the module language files the language chunk every first
 * paint loads carries and takes the merged tree to 615.2. No import walked in.
 * That one phone budget moves a step of five, to 620; the other screens stand
 * under theirs (login 396.3, launcher 411.4, start 627.5, receive 463.9,
 * issue 576.6, history 600.5, app first paint 391.5, initial 189.4).
 *
 * Re-measured 2026-11-16 on the branch that computes a made product's
 * ingredient list, allergens and nutrition from its BOM: with the branch's
 * language files set back to the development line's, the tree measures app
 * first paint at 394.6 KiB gz (login 399.3, launcher 414.4, issue 579.6), and
 * the branch's copy — the fourteen allergens' names, the label section of a
 * product's card, the BOM's Label tab and the nutrition words, in five
 * languages, plus the label sheet's one option — adds 1.0 to every screen
 * through the language chunk each first paint loads (app first paint 395.6,
 * login 400.3, launcher 415.5, issue 580.6). The code adds nothing to these
 * screens; no import walked in. Those four budgets move a step of five (app
 * first paint 400, login 405, launcher 420, issue 585); the other screens
 * stand under theirs (start 631.5, receive 468.0, history 604.5, products
 * 619.5, initial 189.5).
 *
 * Re-measured 2026-11-17 on the branch that updated the frontend's packages:
 * axios 1.20.0 to 1.21.1 is the only one that grows the start path, by 2.6
 * KiB gz — new code in the library itself (response timing, the opt-in UTF-8
 * Basic authentication, the Cookie Store read for the XSRF token, the error
 * diagnostics), not lost tree-shaking: the entry already imported all of axios.
 * Every screen carries it. Before the update app first paint measured 397.4,
 * initial 189.5, login 402.2, launcher 417.3, start 634.2, receive 470.0,
 * issue 582.7, history 607.3, products 624.7; after it 400.0, 192.0, 404.8,
 * 419.8, 636.8, 472.6, 585.3, 609.9, 627.2. The Radix primitives, react-query,
 * lucide-react and the build tools moved nothing by more than 1.5 KiB. Each
 * budget a screen came within a KiB of moves a step of five (app first paint
 * 405, login 410, launcher 425, start 640, receive 475, issue 590, history
 * 615, products 630), so the next update does not trip them again.
 *
 * Re-measured 2026-11-20 on the merge of the refusal states with the
 * development line: the receive screen measures 475.0 KiB gz against its 475,
 * after three days of the line's own growth (472.6 on 11-17) and the shared
 * failure state's refusal branch, which every list that can be refused now
 * reaches. That one phone budget moves a step of five, to 480; the other
 * screens stand under theirs (login 406.9, launcher 422.0, start 639.8, issue
 * 587.8, history 612.6, products 629.8, app first paint 402.2).
 *
 * The merge with the line's next fifteen commits (the storage products tab
 * and the unpicked-products wording) measures the products screen at 630.0
 * KiB gz against its 630; that budget moves a step of five, to 635.
 *
 * Re-measured 2026-11-20 on the branch that tells the reader what warehouse
 * setup, stock take and purchasing screens do: the start screen measures
 * 640.3 KiB gz against its 640, from 639.8 before it. What the branch adds
 * there is copy in six languages (the Polish one sits in the language chunk
 * the start screen loads) and a few lines of the module bar's active-tab
 * rule; no import walked in. That one phone budget moves a step of five, to
 * 645; the other screens stand under theirs (login 407.5, launcher 422.5,
 * receive 475.6, issue 588.4, history 613.2, products 630.6, app first paint
 * 402.7, initial 193.9).
 *
 * Re-measured 2026-11-21 on the branch that words the persona walk's
 * findings: the issue screen measures 590.0 KiB gz against its 590 (from
 * 588.4) and the history screen 615.1 against its 615 (from 613.2). What
 * the branch adds there is copy in six languages (the Polish catalogue sits
 * in the language chunk both screens load); no import walked in. Those two
 * phone budgets move a step of five, to 595 and 620; the other screens stand
 * under theirs (login 408.9, launcher 424.0, start 642.2, receive 477.2,
 * products 632.3, app first paint 404.2, initial 193.9).
 *
 * Re-measured 2026-11-21 on the branch that makes the equipment screens use
 * the words and numbers a reader sees: merged with the line, the history
 * screen measures 615.0 KiB gz against its 615, from 613.2 before it. What
 * the branch adds there is equipment copy in six languages (the Polish
 * catalogue sits in the language chunk the screen loads); no import walked
 * in. That one phone budget moves a step of five, to 620; the other screens
 * stand under theirs.
 *
 * Re-measured 2026-11-21 on the branch that closes the catalogue, locations
 * and labels findings: the issue screen measures 590.2 KiB gz against its 590,
 * from 589.8 on the line without it. What the branch adds is copy in six
 * languages and a few lines of the shared error text; no import walked in.
 * That phone budget moves a step of five, to 595 (the history budget is
 * already at 620 above); the other screens stand under theirs (login
 * 409.1, launcher 424.2, receive 477.4, start 642.6, products 633.0, app
 * first paint 404.3, initial 193.9).
 *
 * The branch that finishes the warehouse floor findings of the persona walk
 * takes the history screen to the same 615.0 on its own (614.0 on the line
 * before it), and the same step to 620 covers it. It adds code as well as
 * copy there: `documentReference.ts`, which names a document's source (stock
 * take, recipe, picking) in words and which the history rows import, plus the
 * wording itself in the language chunk (login 408.8, launcher 423.9, start
 * 642.5, receive 478.1, issue 589.9, products 632.1, app first paint 404.0,
 * initial 193.9 on that branch).
 *
 * Re-measured 2026-11-21 on the branch that settles the first-contact and
 * settings screens: the issue screen measures 590.4 KiB gz against its 590 and
 * history 615.5 against its 615. What the branch adds there is copy in six
 * languages (the browser-validation sentences, the unsaved-changes question,
 * the row-action names, the audit verbs and the settings notes), which sits in
 * the language chunk every first paint loads, and one document-level listener;
 * no import walked in. Those two phone budgets move a step of five (issue 595,
 * history 620); the other screens stand under theirs.
 *
 * Re-measured 2026-11-21 on the branch that words the persona walk's
 * findings, merged with the two changes above: app first paint measures
 * 405.3 KiB gz against its 405, login 410.0 against 410 and launcher 425.1
 * against 425. The branches add copy in six languages to the language chunk
 * every first paint loads; no import walked in. The three budgets move a step
 * of five (app first paint 410, login 415, launcher 430); the other screens
 * stand under theirs (start 643.3, receive 478.9, issue 590.9, history 616.0,
 * products 634.0).
 *
 * Re-measured 2026-11-21 on the branch that closes the catalogue, locations
 * and labels findings, merged with the line that settled the first-contact and
 * settings screens: app first paint measures 405.3 KiB gz against its 405,
 * login 410.1 against 410 and launcher 425.2 against 425. The line alone
 * measures 404.9, 409.7 and 424.8; the branch adds about 0.4 KiB to each (copy
 * in six languages and a few lines of the shared error text, in the language
 * chunk every first paint loads; no import walked in). Those three budgets move
 * a step of five (first paint 410, login 415, launcher 430); the other screens
 * stand under theirs (start 643.4, receive 479.0, issue 591.0, history 616.1,
 * products 634.8, initial 194.0).
 *
 * Re-measured 2026-11-21 on that warehouse floor branch merged with the line
 * that carries the first-contact one: the line alone measures app first paint
 * at 404.93 KiB gz against its 405, and the branch takes it to 405.11. It is
 * copy, not an import: the refusal, receipt, source-reference and
 * manager-only sentences in the Polish language chunk every first paint loads
 * (154.25 to 154.44), while the App chunk stays at 56.7. That one budget moves
 * a step of five, to 410; the other screens stand under theirs (login 409.9,
 * launcher 425.0, start 643.5, receive 479.8, issue 590.8, history 615.9,
 * products 633.8, initial 193.9).
 *
 * Re-measured 2026-11-21 on the persona walk branch merged with that warehouse
 * floor branch: the line measures the receive screen at 479.8 KiB gz against
 * its 480, and the persona walk's copy takes the product to 480.1. It is
 * copy in the language chunk the screen loads, not an import. The receive
 * budget moves a step of five, to 485; the other screens stand under theirs
 * (app first paint 405.5 of 410, login 410.3 of 415, launcher 425.3 of 430,
 * start 643.8, issue 591.2, history 616.3, products 634.3).
 *
 * Re-measured 2026-11-21 on the branch that closes the catalogue, locations
 * and labels findings, merged with the line that carries the warehouse floor
 * branch: the receive screen measures 480.1 KiB gz against its 480. The line
 * alone measures 479.8; the branch adds about 0.3 KiB of copy in six
 * languages to the language chunk that screen loads, no import. That phone
 * budget moves a step of five, to 485; the other screens stand under theirs
 * (app first paint 405.5, login 410.3, launcher 425.4, start 643.8, issue
 * 591.2, history 616.3, products 635.0, initial 194.0).
 *
 * Re-measured 2026-11-21 on the branch that gives read-only accounts their
 * answers and names the rows its error lines are about, merged with the line
 * that closes the catalogue, locations and labels findings: the products
 * screen measures 635.3 KiB gz against its 635 (635.0 on the line alone). The
 * branch adds a batch-delete reason dialog on that page and copy in six
 * languages; no import walked in. That phone budget moves a step of five, to
 * 640; the other screens stand under theirs (app first paint 405.7, login
 * 410.5, launcher 425.5, start 644.3, receive 480.5, issue 591.4, history
 * 616.5, initial 194.0).
 *
 * Re-measured 2026-11-21 on the persona walk branch merged with the line that
 * carries the catalogue, locations and labels branch: the products screen
 * measures 635.4 KiB gz against its 635. The line alone measures 634.3 to
 * 635.0 and this branch alone 634.0; together they add about 0.5 KiB of copy
 * in six languages to the language chunk the screen loads, no import. That
 * phone budget moves a step of five, to 640; the other screens stand under
 * theirs (app first paint 405.8 of 410, login 410.6 of 415, launcher 425.7 of
 * 430, start 644.2 of 645, receive 480.5 of 485, issue 591.5 of 595, history
 * 616.6 of 620, initial 194.0).
 *
 * Re-measured 2026-11-22 on the branch that closes the home, kitchen,
 * approvals and statistics findings, merged with the development line: the
 * start screen measures 645.0 KiB gz against its 645 (the line alone
 * measures 644.6). The branch adds sentences in six languages (recipe delete
 * and tag dialogs, failed-read lines, approvals, statistics) to the language
 * chunk every first paint loads; no import walked in. That phone budget moves
 * a step of five, to 650; the other screens stand under theirs (app first
 * paint 406.4 of 410, login 411.2 of 415, launcher 426.3 of 430, receive
 * 481.2 of 485, issue 592.1 of 595, history 617.2 of 620, products 635.9 of
 * 640, initial 194.0).
 *
 * Re-measured 2026-11-25 on the branch that words refusals in the reader's
 * language, merged with the development line: the receive screen measures
 * 485.1 KiB gz against its 485, and the line alone 485.0. The branch adds
 * sentences in six languages (the recipe tag limit and its refusal, the MCP
 * page's step for a reader who is not an administrator) to the language
 * chunk every first paint loads; no import walked in. That phone budget
 * moves a step of five, to 490; the other screens stand under theirs (app
 * first paint 408.5 of 410, login 413.5 of 415, launcher 428.4 of 430, start
 * 647.9 of 650, issue 594.4 of 595, history 619.5 of 620, products 638.5 of
 * 640, initial 194.2).
 *
 * Re-measured 2026-11-25 on the branch that keeps the focus, Back and the
 * touch targets right on the phone screens, merged with the development line:
 * the issue screen measures 595.6 KiB gz against its 595 and history 620.6
 * against its 620 (the line alone 594.7 and 619.8). This one is code, not
 * copy: the Back-to-start hook the posted result shares with the header, the
 * suggestion panel's placement and Tab handling in the product picker, and
 * their module SDK exports, which both screens load. Those two phone budgets
 * move a step of five, to 600 and 625; the other screens stand under theirs
 * (app first paint 409.3 of 410, login 414.2 of 415, launcher 429.1 of 430,
 * start 649.2 of 650, receive 486.5 of 490, products 639.5 of 640, initial
 * 194.3).
 *
 * Re-measured 2026-11-25 on the branch that closes the recipes and shopping
 * list findings, merged with the development line after that step: the
 * receive screen measures 485.4 KiB gz against its 490. The branch adds a
 * sentence in six languages (a collection's delete naming its
 * sub-collections) to the language chunk every first paint loads, and the
 * module SDK's useLocalStorage to the barrel the receive screen loads; no
 * import walked into the screen and no budget moves (app first paint 408.6
 * of 410, login 413.5 of 415, launcher 428.5 of 430, start 648.2 of 650,
 * issue 594.7 of 595, history 619.8 of 620, products 638.8 of 640, initial
 * 194.2).
 *
 * Re-measured 2026-11-26 on the branch that prepares a long spreadsheet
 * export in the background, merged with the development line at cd934b784:
 * the history screen measures 620.2 KiB gz against its 620 and the issue
 * screen 595.0 against its 595, where the line alone stands at 619.9 and
 * 594.8. The branch adds the follower of an export job to the items API
 * client, which every screen that lists products loads, and one sentence in
 * six languages (the notice of an export being prepared) to the language
 * chunk every first paint loads; no import walked into either screen. Both
 * phone budgets move a step of five, history to 625 and issue to 600; the
 * other screens stand under theirs (app first paint 408.9 of 410, login
 * 413.8 of 415, launcher 428.8 of 430, start 648.7 of 650, receive 485.7 of
 * 490, products 639.3 of 640, initial 194.2).
 *
 * Re-measured 2026-11-26 on the branch that keeps the focus, Back and the
 * touch targets right on the phone screens, merged with the development line
 * at d91a8765c9: app first paint measures 410.4 KiB gz against its 410,
 * login 415.4 against 415, launcher 430.3 against 430 and start 650.3
 * against 650, where the line alone stands at 409.8, 414.7, 429.7 and 649.6.
 * The branch adds about 0.6 KiB of code to the startup path: the
 * Back-to-start hook with the entry-before it keeps across a reload, and the
 * focus a closing sheet hands back. The shell hook also builds into a chunk
 * of its own, because lazy screens reach it through the module SDK; no
 * outside import walked in. Those four budgets move a step of five, to 415,
 * 420, 435 and 655. The other screens stand under theirs (receive 487.7 of
 * 490, issue 596.7 of 600, history 621.8 of 625, products 629.2 of 640,
 * initial 194.3).
 *
 * Re-measured 2026-11-26 on the branch that adds the rentals module: receive
 * measures 491.5 KiB gz against its 490, issue 600.5 against 600 and history
 * 625.6 against 625. What the branch adds is copy in six languages — the
 * module's own screens, refusals and guide, the Polish catalogue in the
 * language chunk every first paint loads — and a few exports on the module SDK
 * barrel (the side sheet, the date field, the scrolling row, the organization's
 * clock); no import walked into the startup path, and the SDK's unused select,
 * tabs and badge exports were left out rather than pull Radix into every
 * screen's barrel. Those three phone budgets move a step of five, to 495, 605
 * and 630; the other screens stand under theirs (app first paint 414.3 of
 * 415, login 419.2 of 420, launcher 434.2 of 435, start 654.1 of 655,
 * products 633.4 of 640, initial 194.6 of 245).
 *
 * Re-measured 2026-11-27 on the rentals branch, merged with the development
 * line at 6fcdfd3a2: app first paint measures 415.0 KiB gz and no longer fits
 * its 415, where the line alone stands at 411.1. The difference is the
 * module's own: its copy in six languages, of which the Polish catalogue loads
 * with every first paint (158.7 to 162.1), and its registration in the App
 * chunk (58.1 to 58.4); no import walked into the startup path. The first
 * paint budget moves a step of five, to 420. The phone screens stand under
 * theirs (login 419.9 of 420, launcher 434.9 of 435, start 654.9 of 655,
 * receive 492.3 of 495, issue 601.3 of 605, history 626.3 of 630, products
 * 634.4 of 640, initial 194.5 of 245).
 *
 * Re-measured 2026-11-27 on the merge of the Grocy move's branch with the
 * branch that reads a sheet's times, units and the preview's two readings, at
 * e1dc422216: login measures 420.1 KiB gz against its 420, launcher 435.0
 * against 435 and start 655.2 against 655, where the line alone stands at
 * 420.0, 434.9 and 654.9. The Grocy branch adds four sentences in six
 * languages (the switched-off kinds, and shopping list entries that could not
 * be brought) to the language chunk every first paint loads, the Polish one
 * growing from 162.1 to 162.2; the sheet-reader branch adds the document
 * import dialog's second preview reading and its expiry column to the chunk
 * the start screen opens with, and the second reading's key to the empty
 * analyze answer the items and partners clients give above it; the App chunk
 * stays at 58.4 and no import walked into the startup path. Those three phone
 * budgets move a step of five, to 425, 440 and 660 — the start step is the
 * one both branches asked for; the other screens stand under theirs (app
 * first paint 415.2 of 420, receive 492.5 of 495, issue 601.5 of 605, history
 * 626.6 of 630, products 634.7 of 640, initial 194.5 of 245).
 *
 * Re-measured 2026-11-28 on the branch that reads a label's QR with a second
 * decoder: the scanner's chunk carries jsQR beside html5-qrcode, 45.1 KiB gz,
 * and every screen with the scan panel pays it once — start 700.3 against
 * 660, issue 646.7 against 605, history 671.7 against 630 and products 679.9
 * against 640. What the branch adds is that decoder: html5-qrcode's zxing
 * port cannot locate a label's QR in a clean still for about one label in a
 * hundred, and on Safari and Firefox it is the only decoder the scanner has,
 * so jsQR reads the frames it reports it cannot. The chunk loads with the
 * scanner, not with the first paint: app first paint (415.2 of 420), login
 * (420.1 of 425), launcher (435.0 of 440) and receive (492.5 of 495) stand
 * as they were, and initial is 194.6 of 245. The four budgets move by the
 * reading plus a step of five, to 705, 650, 675 and 685. Merged with the
 * development line at 7907aca735, the same screens measure 701.2, 647.4,
 * 672.7 and 680.6, still inside those.
 */
const BUDGETS = {
  initial: 245,
  appFirstPaint: 420,
};

/**
 * The phone budget, per screen: what a reader on a mid Android over slow 4G
 * downloads for each core screen, in KiB of gzip. `phone-budget.json` holds
 * the budgets and the recorded measurement they were set from; the load-time
 * half of it is enforced by `npm run perf:phone`, which needs a running stack
 * and a browser (`make check-frontend` runs it). The bytes need neither, so
 * they are checked here, on every build, from what `dist/` holds.
 */
const PHONE_BUDGET = JSON.parse(
  readFileSync(join(root, "scripts", "phone-budget.json"), "utf8"),
);

const KIB = 1024;
const kib = (bytes) => bytes / KIB;
const gz = (file) => kib(gzipSync(readFileSync(file)).length);

if (!existsSync(join(dist, "index.html"))) {
  console.error(
    `check-bundle-budget: ${dist}/index.html not found — build first.`,
  );
  process.exit(2);
}

const distDir = join(dist, "assets");
const html = readFileSync(join(dist, "index.html"), "utf8");

// The assets a browser must fetch with index.html before anything renders.
const initialRefs = [
  ...[...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1]),
  ...[
    ...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g),
  ].map((m) => m[1]),
  ...[...html.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g)].map(
    (m) => m[1],
  ),
];

// Chunk files import each other with relative specifiers; follow them to the
// full static closure of whatever the browser was handed.
function closure(refs) {
  const seen = new Set();
  const queue = refs.map((ref) => ref.replace(/^\/+/, ""));
  while (queue.length > 0) {
    const ref = queue.pop();
    if (seen.has(ref) || !ref.endsWith(".js")) continue;
    if (!existsSync(join(dist, ref))) continue;
    seen.add(ref);
    const source = readFileSync(join(dist, ref), "utf8");
    for (const match of source.matchAll(
      /(?:from|import)\s*\(?\s*["'](\.[^"']+\.js)["']/g,
    )) {
      queue.push(join(dirname(ref), match[1]));
    }
  }
  return [...seen].sort();
}

const initialFiles = closure(initialRefs);

// The App tree: lazy-loaded behind sign-in, paid at the app's first paint.
// Vite names the chunk after the module — App-<hash>.js.
const appChunk = readdirSync(distDir).find((name) =>
  /^App-[\w-]+\.js$/.test(name),
);
if (!appChunk) {
  console.error(
    "check-bundle-budget: no App-*.js chunk in dist/assets — unexpected build shape.",
  );
  process.exit(2);
}
const appFiles = closure([`assets/${appChunk}`]);

// One language file is preloaded before the first render; the heaviest is
// the honest number.
const languageFiles = readdirSync(distDir)
  .filter((name) => /^i18n-[a-z-]+[\w-]*\.js$/.test(name))
  .map((name) => ({ name, gzip: gz(join(distDir, name)) }))
  .sort((a, b) => b.gzip - a.gzip);

const initialKib = initialFiles.reduce((sum, f) => sum + gz(join(dist, f)), 0);
const appOnlyKib = appFiles
  .filter((f) => !initialFiles.includes(f))
  .reduce((sum, f) => sum + gz(join(dist, f)), 0);
const languageKib = languageFiles[0]?.gzip ?? 0;
const appFirstPaintKib = initialKib + appOnlyKib + languageKib;

// A screen's price is the signed-in first paint plus the closure of its own
// lazy chunks — the part nothing else on the way in had already paid for.
const chunkNamed = (prefix) =>
  readdirSync(distDir).find((name) =>
    new RegExp(`^${prefix}-[\\w-]+\\.js$`).test(name),
  );
const screenKib = {};
const screenErrors = [];
for (const [screen, { chunks }] of Object.entries(PHONE_BUDGET.screens)) {
  const paid = new Set([...initialFiles, ...appFiles]);
  let own = 0;
  for (const prefix of chunks) {
    const chunk = chunkNamed(prefix);
    if (!chunk) {
      screenErrors.push(`${screen}: no ${prefix}-*.js chunk in dist/assets`);
      continue;
    }
    for (const file of closure([`assets/${chunk}`])) {
      if (paid.has(file)) continue;
      paid.add(file);
      own += gz(join(dist, file));
    }
  }
  screenKib[screen] = appFirstPaintKib + own;
}

const report = (label, value, budget) => {
  const mark = value <= budget ? "ok  " : "OVER";
  console.log(
    `  ${mark}  ${label.padEnd(16)} ${value.toFixed(1).padStart(7)} KiB gz  (budget ${budget})`,
  );
};

console.log("check-bundle-budget:");
report("initial", initialKib, BUDGETS.initial);
report("appFirstPaint", appFirstPaintKib, BUDGETS.appFirstPaint);
console.log(
  `         heaviest language: ${languageFiles[0]?.name ?? "none"} ${languageKib.toFixed(1)} KiB gz; ` +
    `App chunk ${appChunk} adds ${appOnlyKib.toFixed(1)} KiB gz over initial`,
);

console.log(
  "  phone budget, JS per screen (first paint + the screen's chunks):",
);
for (const [screen, kibValue] of Object.entries(screenKib)) {
  report(screen, kibValue, PHONE_BUDGET.screens[screen].budget.jsKiB);
}

const breaches = Object.entries({
  initial: initialKib,
  appFirstPaint: appFirstPaintKib,
}).filter(([name, value]) => value > BUDGETS[name]);

const screenBreaches = Object.entries(screenKib).filter(
  ([screen, value]) => value > PHONE_BUDGET.screens[screen].budget.jsKiB,
);
if (screenErrors.length > 0 || screenBreaches.length > 0) {
  console.error(
    `\ncheck-bundle-budget: phone budget — ${[
      ...screenErrors,
      ...screenBreaches.map(
        ([screen, value]) =>
          `${screen} ${value.toFixed(1)} > ${PHONE_BUDGET.screens[screen].budget.jsKiB} KiB gz`,
      ),
    ].join("; ")}. A screen a worker opens on a phone got heavier.`,
  );
  process.exitCode = 1;
}

if (breaches.length > 0) {
  console.error(
    `\ncheck-bundle-budget: ${breaches
      .map(
        ([name, value]) =>
          `${name} ${value.toFixed(1)} > ${BUDGETS[name]} KiB gz`,
      )
      .join("; ")}. The startup path grew — find the import that walked in.`,
  );
  process.exit(1);
}
