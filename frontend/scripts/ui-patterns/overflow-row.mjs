import { classNameOf, lineAt, openingTags } from "./lib.mjs";

/** The row is already allowed to scroll, or is wrapped in one that can. */
const HAS_SCROLLER = /(?:overflow-x-auto|overflow-auto|ScrollRow)/;

/**
 * How far back to look for a scroller around the row.
 *
 * 200 characters was not enough: `ListControlBar` opens a `ScrollRow`, then a
 * filter button, then a label, then a `<Tabs>` with three props before the
 * `TabsList` — about 400 characters of correct code the rule read as a
 * missing scroller.
 */
const LOOKBEHIND = 900;

/** The one way a call site can still ask for a row that does not scroll. */
const OPTED_OUT = /scrollable=\{false\}/;

export default {
  name: "overflow-row",
  says:
    "A `TabsList` is `inline-flex` with `whitespace-nowrap` children and no " +
    "way to scroll: past four or five tabs the last ones leave the viewport " +
    "on a phone, and the only thing that moves is the whole page, sideways.",
  advice:
    "`TabsList` scrolls its own tabs unless you turn that off. If this row\n" +
    "genuinely must not scroll, put it inside a <ScrollRow> so the page\n" +
    "still does not — ListControlBar and ModuleShell both do, and say why.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      for (const { tag, index } of openingTags(file.text, "TabsList")) {
        considered.add(file.path);

        const className = classNameOf(tag) ?? "";
        // The bar scrolls by default, so only an opt-out can be a finding.
        if (!OPTED_OUT.test(tag)) continue;
        if (HAS_SCROLLER.test(className)) continue;

        const before = file.text.slice(Math.max(0, index - LOOKBEHIND), index);
        if (HAS_SCROLLER.test(before)) continue;

        findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
