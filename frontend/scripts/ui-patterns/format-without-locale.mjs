import { lineAt, withoutComments } from "./lib.mjs";

/**
 * A locale left to the runtime: `undefined`, or `navigator.language`, which
 * is the browser's language and not the interface's.
 */
const RUNTIME_LOCALE = "(?:undefined\\b|navigator\\s*\\.\\s*languages?\\b)";

/**
 * A locale spelled `undefined`: the argument slot is there, the options are
 * there, and the language was left to the runtime. `\s*` crosses newlines —
 * the text is scanned whole, so a call broken over several lines reads like
 * the one-liner.
 *
 * The bare `toLocaleString()` is deliberately not matched — that shape has one
 * member in this app and it is a machine file's timestamp (the stock-take CSV
 * export), where the figure is data rather than a sentence. The mistake this
 * rule guards is the one made while *choosing* an argument.
 */
const TO_LOCALE_STRING = new RegExp(
  `\\.toLocale(?:Date|Time)?String\\(\\s*${RUNTIME_LOCALE}`,
  "g",
);

/**
 * `Intl.DateTimeFormat().resolvedOptions().timeZone` asks for the zone, which
 * has no language in it — the one empty call that is the right call.
 */
const TIME_ZONE_READ = "\\s*\\.\\s*resolvedOptions\\(\\s*\\)\\s*\\.\\s*timeZone\\b";

/**
 * The constructor spelling of the same mistake. Unlike `toLocaleString()`,
 * `new Intl.NumberFormat()` has no machine-file reading worth sparing: the
 * shared formatter is built on it, so the empty call is a formatter that
 * forgot its language.
 */
const INTL_CONSTRUCTOR = new RegExp(
  `\\bIntl\\s*\\.\\s*(?:NumberFormat|DateTimeFormat)\\(\\s*(?:\\)(?!${TIME_ZONE_READ})|${RUNTIME_LOCALE})`,
  "g",
);

export default {
  name: "format-without-locale",
  corpus: "scripts",
  says:
    "`toLocaleString(undefined, …)`, `new Intl.NumberFormat()` and a locale " +
    "read from `navigator.language` ask the runtime for its own language, " +
    "which is the browser's, not the interface's. A Polish screen then " +
    "writes the American number for everyone whose browser is English — and " +
    "looks correct to the one reader who cannot see it, whose browser is " +
    "Polish too.",
  advice:
    "Name the reader's language — `date.toLocaleDateString(i18n.language,\n" +
    "…)` — or use the shared formatter, which reads `i18next.language`\n" +
    "itself: `formatNumberLocale`, `formatPercentLocale`,\n" +
    "`formatQuantityLocale`, `formatQuantityLocaleWithUnit`, `formatMoney`,\n" +
    "`formatDate`, `formatDateMedium`, `formatDateTime`. A value inside an\n" +
    "`<input value=…>` is a figure being edited, not one being read, and is\n" +
    "not reported.",

  run(files) {
    const considered = files.filter(
      (f) => f.text.includes("toLocale") || f.text.includes("Intl"),
    );
    const findings = [];

    for (const file of considered) {
      const text = withoutComments(file.text);
      const lines = new Set();
      for (const pattern of [TO_LOCALE_STRING, INTL_CONSTRUCTOR])
        for (const match of text.matchAll(pattern))
          lines.add(lineAt(text, match.index));
      for (const line of [...lines].sort((a, b) => a - b))
        findings.push(`${file.path}:${line}`);
    }

    return { considered: considered.length, findings };
  },
};
