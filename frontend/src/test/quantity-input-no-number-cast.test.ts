import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

/**
 * The quantity field reports what a number input reports — and while a
 * fraction is being typed, that includes the empty string: the browser
 * sanitises the incomplete "12." to "". A caller that answers
 * `onChange` by casting the report through `Number()` writes 0 into its
 * numeric state, the controlled field rewrites itself to "0", and the dot
 * the reader was still holding dies with it: "12.5" kg ended as "05",
 * five units on the document instead of twelve and a half.
 *
 * The field therefore offers `onQuantityChange`, which hands the caller a
 * number when the text is one and `null` while it is not — there is no
 * text worth casting. Callers whose storage is text keep `onChange` and
 * echo the text verbatim, which the browser's editing buffer survives.
 *
 * This check keeps the class from coming back. It scans every non-test
 * `.tsx` under `src/` for a `<QuantityInput>` whose `onChange` handler
 * casts the report through a numeric constructor without first making
 * the empty report a case of its own. A `Number.isNaN` guard does not
 * count: `Number("")` is 0, not NaN, so only an explicit `""` comparison
 * keeps the dot step's report out of the state. The reverse checks below
 * keep the scan itself honest: if the known cast sites are renamed or
 * stop rendering `QuantityInput`, the scan has gone blind and fails too.
 */

const CAST = /\b(?:Number|parseInt|parseFloat)\s*\(/;
const EMPTY_GUARD = /===\s*""/;

const KNOWN_CONSUMERS = [
  "src/modules/shared/components/LineItemsEditor/LineItemRow.tsx",
  "src/modules/warehouse/components/LineQuantityStepper.tsx",
  "src/modules/warehouse/components/DocumentQuickAddPanel.tsx",
  "src/modules/warehouse/components/ExecutionLineCard.tsx",
  "src/modules/shopping_lists/components/AddItemModal.tsx",
];

const FIELD = "src/components/ui/QuantityInput.tsx";

/**
 * The attributes of one JSX opening tag, from `<Name` to the `>` that ends
 * it. A `>` inside an attribute expression (`onChange={(e) => …}`) sits at
 * brace or paren depth > 0, and one inside a quoted string is skipped, so
 * the first bare `>` really is the tag's end.
 */
function openingTag(source: string, start: number): string {
  let depth = 0;
  let quote: string | null = null;
  for (let i = start; i < source.length; i += 1) {
    const ch = source[i];
    if (quote) {
      if (ch === quote && source[i - 1] !== "\\") quote = null;
    } else if (ch === '"' || ch === "'" || ch === "`") {
      quote = ch;
    } else if (ch === "{" || ch === "(") {
      depth += 1;
    } else if (ch === "}" || ch === ")") {
      depth -= 1;
    } else if (ch === ">" && depth === 0) {
      return source.slice(start, i);
    }
  }
  return source.slice(start);
}

/** The expression of `onChange={…}` inside a tag's attributes, or null. */
function onChangeExpression(tag: string): string | null {
  const at = tag.indexOf("onChange={");
  if (at === -1) return null;
  let depth = 0;
  for (let i = at + "onChange=".length; i < tag.length; i += 1) {
    const ch = tag[i];
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return tag.slice(at, i + 1);
    }
  }
  return tag.slice(at);
}

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (full.endsWith(".tsx") && !full.endsWith(".test.tsx")) {
      out.push(full);
    }
  }
  return out;
}

function castSites(): string[] {
  const sites: string[] = [];
  for (const file of walk(join(process.cwd(), "src"))) {
    const text = readFileSync(file, "utf8");
    let at = text.indexOf("<QuantityInput");
    while (at !== -1) {
      const tag = openingTag(text, at);
      const handler = onChangeExpression(tag);
      if (handler && CAST.test(handler) && !EMPTY_GUARD.test(handler)) {
        sites.push(relative(process.cwd(), file).split(sep).join("/"));
      }
      at = text.indexOf("<QuantityInput", at + 1);
    }
  }
  return sites;
}

describe("no QuantityInput onChange casts its text through Number()", () => {
  it("every QuantityInput keeps the text or asks for the committed number", () => {
    expect(
      castSites(),
      "QuantityInput consumers that cast the change report through " +
        "Number/parseInt/parseFloat. The empty report of the dot " +
        "step becomes 0 and rewrites the field mid-typing. Keep the text in " +
        "state, or switch to onQuantityChange and receive the parsed number " +
        "(null while the text is not one yet).",
    ).toEqual([]);
  });

  it("the sites the scan was born on still render QuantityInput", () => {
    // If these three stopped rendering the field — renamed, replaced by
    // another control — the scan above has fewer places to be right about,
    // and this check is the alarm: the cast class moved, update the scan.
    for (const rel of KNOWN_CONSUMERS) {
      const text = readFileSync(join(process.cwd(), rel), "utf8");
      expect(text.includes("<QuantityInput"), rel).toBe(true);
    }
  });

  it("the field still offers the committed-value API the cast-free path needs", () => {
    const text = readFileSync(join(process.cwd(), FIELD), "utf8");
    expect(text.includes("onQuantityChange")).toBe(true);
  });

  it("the one guarded cast the scan sanctions still guards the empty report", () => {
    // ConsumeDialog keeps its own text state and parses only to check it,
    // letting the empty report through as "" — the pattern the EMPTY_GUARD
    // exemption exists for. If that guard disappears, the exemption covers
    // a cast it was never meant to.
    const text = readFileSync(
      join(process.cwd(), "src/modules/inventory/components/ConsumeDialog.tsx"),
      "utf8",
    );
    expect(EMPTY_GUARD.test(text)).toBe(true);
  });
});
