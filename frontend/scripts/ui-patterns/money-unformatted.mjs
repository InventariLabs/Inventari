import { lineAt, withoutComments } from "./lib.mjs";

/**
 * Field names that hold money in this schema. Deliberately a list rather than
 * a shape like `/_cost$/`: `quantity` and `qty_per_batch` are numbers too, and
 * a rule that guesses which ones are money reports the wrong half of them.
 */
const MONEY_FIELD =
  /\.\s*(total_cost|unit_cost|estimated_unit_cost|unit_sale_price|sale_price|reference_price|unit_price|total_price|total_amount|grand_total|subtotal|cost|price|amount)\b/;

/**
 * Owners that hold the *name* of an amount rather than the amount.
 * `{labels.subtotal}` is the word "Subtotal", and formatting it as money
 * would be the opposite mistake.
 */
const LABEL_OWNER = /\b(labels?|texts?|copy|strings|headers?)\s*\.\s*$/;

/** Calls that turn an amount into something a reader can price. */
const FORMATTED = /\b(money|formatMoney|formatCurrency)\s*\(|\bt\s*\(/;

/**
 * Whether the `{` at `open` opens JSX text rather than an object literal.
 *
 * The scan reads whole files, and `{` is the commonest character in
 * TypeScript. What separates the two is what stands before: JSX text follows
 * the `>` of a tag or the `}` of the interpolation beside it, while an object
 * literal follows `=`, `(`, `,`, `return`. The one collision is the `>` of an
 * arrow — `=>` — which is why the character before the `>` is read too.
 */
function inTextPosition(text, open) {
  let i = open - 1;
  while (i >= 0 && /\s/.test(text[i])) i--;
  if (i < 0) return false;
  if (text[i] === "}") return true;
  return text[i] === ">" && text[i - 1] !== "=";
}

/** The end of the `{…}` expression that starts at `open`, or -1. */
function closing(text, open) {
  let depth = 0;
  let quote = null;

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
    if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return i;
  }
  return -1;
}

export default {
  name: "money-unformatted",
  says:
    "An amount interpolated straight into JSX renders the string the API " +
    "sent — `0.00`, with an American point and no currency — beside the " +
    "same figure written `0,00 zł` one screen away. The reader is left to " +
    "guess whether the two are the same number, and in which currency.",
  advice:
    "Call `useMoney()` once in the component and wrap the amount:\n" +
    "`{money(breakdown.total_cost)}`. The hook supplies the organization's\n" +
    "currency and the interface language, so a screen cannot forget either.\n" +
    "An amount that is deliberately raw — inside an `<input value=…>`, or a\n" +
    "figure the user is editing — is not in text position and not reported.",

  run(files) {
    const considered = files.filter((f) => MONEY_FIELD.test(f.text));
    const findings = [];

    for (const file of considered) {
      const text = withoutComments(file.text);
      for (let i = 0; i < text.length; i++) {
        if (text[i] !== "{") continue;
        // A block that wraps other interpolations is not the finding —
        // the leaf inside it is, which is why the scan walks into nested
        // braces instead of stepping over them.
        if (!inTextPosition(text, i)) continue;
        const end = closing(text, i);
        if (end === -1) break;
        const expr = text.slice(i + 1, end);
        if (expr.includes("{")) continue;
        const money = MONEY_FIELD.exec(expr);
        if (!money || FORMATTED.test(expr)) continue;
        if (LABEL_OWNER.test(expr.slice(0, money.index + 1))) continue;
        findings.push(`${file.path}:${lineAt(text, i)}`);
      }
    }

    return { considered: considered.length, findings: findings.sort() };
  },
};
