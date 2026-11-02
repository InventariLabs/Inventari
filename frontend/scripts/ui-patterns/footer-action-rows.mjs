import { lineAt, openingTags, withoutComments } from "./lib.mjs";

/** Buttons that name themselves destructive, whatever the label says. */
const DESTRUCTIVE = /variant="(?:ghostDanger|destructive|danger)"/;

/**
 * The escape hatch, in the shape `destructive-outside-confirm` established: a
 * reason at the call site rather than a list of paths somewhere else, and it
 * has to be a sentence.
 *
 *   {\/* ui-pattern: footer-action — the sheet *is* the confirmation step,
 *       there is no record to act on outside it *\/}
 */
const EXCEPTION = /ui-pattern:\s*footer-action\s*[—-]?\s*([^*}]+)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 500;

/**
 * The body of one `<SheetFooter>`, from its opening tag to its close.
 *
 * `SheetFooter` never nests inside itself, so the next closing tag is this
 * one's — no depth counting needed.
 */
function footerRegions(text) {
  const out = [];

  for (const m of text.matchAll(/<SheetFooter\b/g)) {
    const close = text.indexOf("</SheetFooter>", m.index);
    out.push({
      index: m.index,
      body: close === -1 ? text.slice(m.index) : text.slice(m.index, close),
    });
  }
  return out;
}

function excused(text, index) {
  const before = text.slice(Math.max(0, index - LOOKBEHIND), index);
  const reason = before.match(EXCEPTION)?.[1] ?? "";
  return reason.trim().split(/\s+/).filter(Boolean).length >= MIN_REASON_WORDS;
}

export default {
  name: "footer-action-rows",
  says:
    "A <SheetFooter> holding more than one <SheetActions>, or holding a " +
    "destructive action, has stopped being a footer about the current edit — " +
    "UI_GUIDELINES §4.3 gives it exactly one row (Cancel, then the primary " +
    "action) and sends Delete/Archive to the header's <ActionMenu>, because " +
    "those act on the record and outlive the dialog.",
  advice:
    "Use <FormSheetFooter> for the row, and put the record's own actions in\n" +
    "an <ActionMenu> beside the close button. A second row is not a smaller\n" +
    "version of the problem: SheetActions gives every button `flex-1` below\n" +
    "`sm`, so four actions on a 390px screen are four ~90px buttons.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      // Comments are blanked character for character, so an offset here still
      // points into `file.text` — which is where an exception's reason lives.
      const text = withoutComments(file.text);

      for (const { index, body } of footerRegions(text)) {
        considered.add(file.path);

        const rows = [...body.matchAll(/<SheetActions\b/g)].length;
        if (rows > 1 && !excused(file.text, index)) {
          findings.push(`${file.path}:${lineAt(text, index)}`);
          continue;
        }

        for (const { tag, index: at } of openingTags(body, "Button")) {
          if (!DESTRUCTIVE.test(tag)) continue;
          if (excused(file.text, index + at)) continue;
          findings.push(`${file.path}:${lineAt(text, index + at)}`);
        }
      }
    }

    return { considered: considered.size, findings };
  },
};
