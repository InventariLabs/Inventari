import { lineAt, withoutComments } from "./lib.mjs";

/**
 * Top-level arguments of a call whose `(` is at `open`, each trimmed.
 *
 * Same bracket/quote walk as the old `argumentCount`, but it records the span
 * of each argument instead of just counting them, so a detector can ask what
 * the currency argument *says* — `undefined` is a different answer from
 * `currency ?? orgCurrency`.
 */
function argumentsOf(text, open) {
  const args = [];
  let depth = 0;
  let quote = null;
  let start = open + 1;

  for (let i = open; i < text.length; i++) {
    const ch = text[i];

    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      quote = ch;
      continue;
    }
    if (ch === "(" || ch === "[" || ch === "{") {
      depth++;
      continue;
    }
    if (ch === ")" || ch === "]" || ch === "}") {
      depth--;
      if (depth === 0) {
        const last = text.slice(start, i).trim();
        // A trailing comma (prettier's multi-line output) opens an argument
        // that never comes; it is not a second one.
        if (last !== "" || args.length === 0) args.push(last);
        return args;
      }
      continue;
    }
    if (ch === "," && depth === 1) {
      args.push(text.slice(start, i).trim());
      start = i + 1;
    }
  }
  return args;
}

export default {
  name: "money-without-currency",
  says:
    "`formatMoney(amount)` with nothing after the amount — or with a currency " +
    "argument that is literally `undefined` or `null` — renders `0.00 ?`, the " +
    "marker the formatter prints when it is not told which currency the " +
    "number is in. It is not a formatting glitch; it is the second argument " +
    "nobody passed, on screens that know the answer.",
  advice:
    "Call `useMoney()` and pass the amount alone: the hook supplies the\n" +
    "organization's currency and the interface language, so neither can be\n" +
    "forgotten. Pass `formatMoney(amount, currency, locale)` directly only\n" +
    "when the amount carries a currency of its own — a purchase order in a\n" +
    "supplier's currency — and give it the locale in the same breath. When\n" +
    "the currency genuinely can be missing, render an em dash instead\n" +
    "of passing `undefined` through to the formatter.",

  run(files) {
    const considered = files.filter((f) => /formatMoney\(/.test(f.text));
    const findings = [];

    for (const file of considered) {
      const text = withoutComments(file.text);
      const call = /\bformatMoney\(/g;
      let match;
      while ((match = call.exec(text)) !== null) {
        const open = match.index + match[0].length - 1;
        const args = argumentsOf(text, open);
        // Fewer than two arguments: no currency was passed at all.
        if (args.length < 2) {
          findings.push(`${file.path}:${lineAt(text, match.index)}`);
          continue;
        }
        // Two or more: the second argument is the currency. A literal
        // `undefined` or `null` there is the missing answer spelled in full —
        // the formatter prints the same "?" marker for it as for no argument.
        if (args[1] === "undefined" || args[1] === "null") {
          findings.push(`${file.path}:${lineAt(text, match.index)}`);
        }
      }
    }

    return { considered: considered.length, findings };
  },
};
