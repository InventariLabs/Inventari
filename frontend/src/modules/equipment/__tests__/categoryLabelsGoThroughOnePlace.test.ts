import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * A category name is an English literal persisted when the module was
 * installed — "Other Equipment" reads that way in a Polish interface. One
 * helper turns the code into a translation, and it kept being forgotten:
 * five screens rendered the stored name, so one category appeared in four
 * shapes on four screens.
 *
 * This scan is the gate the next one hits before review does.
 */

const MODULE_ROOT = join(process.cwd(), "src", "modules", "equipment");

/** Where the raw name is the honest answer. */
const ALLOWED = [
  // The helper itself, and the type that carries the field.
  "components/assetUtils.ts",
  // Selecting a category to *edit* shows the stored value, not a label.
  "components/CategoryFieldsEditor.tsx",
];

/**
 * A JSX expression rendering the raw name. A doubled brace is not one: the
 * protocol editor names its `{{category_name}}` symbol in a string, and that
 * token is what a template author types, not a category on the screen.
 */
const RAW_NAME =
  /(?<!\{)\{\s*[\w.?]*(category\.name|category_name|category\?\.name)\s*\}(?!\})/;

/**
 * The shape the pattern above cannot see: a message that interpolates the
 * raw name into a `categories.*` sentence. The delete dialog asked "delete
 * **Desktop Computer**?" under a row reading "Komputer stacjonarny" — the
 * name never stood in JSX braces, and the confirmation exists so the reader
 * can check that they are deleting what they meant to. A
 * `getCategoryLabel(` between the key and the interpolation marks the call
 * as going through the helper.
 */
const RAW_TEMPLATE_NAME =
  /t\(\s*["']categories\.[\w.]+["']\s*,\s*\{(?:(?!getCategoryLabel)[\s\S])*?name:\s*[\w.]*\.name\b/;

/** `key={cat.category_name}` is React bookkeeping, not text on a screen. */
const NOT_RENDERED = /(key|alt|title|aria-label|data-testid)=\{/;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__") continue;
      out.push(...walk(full));
      continue;
    }
    if (entry.endsWith(".tsx") || entry.endsWith(".ts")) out.push(full);
  }
  return out;
}

describe("category names in the equipment module", () => {
  it("are rendered through getCategoryLabel, never straight from the row", () => {
    const offenders: string[] = [];

    for (const file of walk(MODULE_ROOT)) {
      const rel = relative(MODULE_ROOT, file);
      if (ALLOWED.includes(rel)) continue;
      const source = readFileSync(file, "utf8");
      for (const [index, line] of source.split("\n").entries()) {
        if (NOT_RENDERED.test(line)) continue;
        if (RAW_NAME.test(line)) offenders.push(`${rel}:${index + 1}`);
      }
      const template = RAW_TEMPLATE_NAME.exec(source);
      if (template) {
        const line = source.slice(0, template.index).split("\n").length;
        offenders.push(`${rel}:${line} (message interpolates the raw name)`);
      }
    }

    expect(offenders).toEqual([]);
  });

  it("tells a rendered name from a template symbol that spells it", () => {
    expect(RAW_NAME.test("<span>{asset.category_name}</span>")).toBe(true);
    expect(RAW_NAME.test("<td>{row.category?.name}</td>")).toBe(true);
    expect(
      RAW_NAME.test('{ key: "{{category_name}}", descriptionKey: "x" },'),
    ).toBe(false);
  });

  it("would catch the raw name the delete dialog interpolated", () => {
    const preFix =
      'message: t("categories.confirmDelete", { name: cat.name }),';
    const fixed = [
      'message: t("categories.confirmDelete", {',
      "  name: getCategoryLabel(t, { code: cat.code, name: cat.name }),",
      "}),",
    ].join("\n");

    expect(RAW_TEMPLATE_NAME.test(preFix)).toBe(true);
    expect(RAW_TEMPLATE_NAME.test(fixed)).toBe(false);
  });
});
