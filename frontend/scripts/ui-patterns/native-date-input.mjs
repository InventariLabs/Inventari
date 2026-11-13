import { lineAt, withoutComments } from "./lib.mjs";

/** `type="date"`, `type='date'` and `type={"date"}` — the attribute, not prose. */
const NATIVE_DATE = /\btype=(?:\{\s*)?["']date["']/g;

export default {
  name: "native-date-input",
  says:
    "A native `<input type=\"date\">` formats its value in the browser's " +
    "language, not the app's, and opens a picker that looks different on " +
    "every platform — every date field takes `<DateInput>` (UI_GUIDELINES " +
    "§2.8).",
  advice:
    "Use `<DateInput>` from `@/components/ui/DateInput`: it reads and writes\n" +
    "the same ISO `YYYY-MM-DD` string, so the value and the form state do not\n" +
    "change — only the control does.",

  run(files) {
    const findings = [];

    for (const file of files) {
      // Comments blanked, offsets kept: a doc comment quoting the attribute is
      // prose about the mistake, not the mistake.
      const text = withoutComments(file.text);
      for (const match of text.matchAll(NATIVE_DATE)) {
        findings.push(`${file.path}:${lineAt(text, match.index)}`);
      }
    }

    return { considered: files.length, findings };
  },
};
