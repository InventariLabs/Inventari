/**
 * What must hold: a spec that still asks the screen for a text the catalogs
 * dropped fails the gate, and a spec the screen still satisfies does not —
 * a gate that cries over comments, identifiers or surviving labels gets
 * switched off.
 */
import { chmodSync } from "node:fs";
import { delimiter, join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { findStaleText } from "./check-e2e-catalog-text.mjs";
import { makeRepo, runGate } from "./gate-fixture.mjs";

const EN = "src/i18n/locales/en/labels.json";
const PL = "src/i18n/locales/pl/labels.json";
const SPEC = "tests/e2e/photo.spec.ts";

/** Findings for one catalog change (English unless `path` says otherwise). */
function find(old, now, spec, { path = EN, specPath = SPEC, also = {} } = {}) {
  return findStaleText({
    before: { [path]: old },
    after: { [path]: now, ...also },
    specs: { [specPath]: Array.isArray(spec) ? spec.join("\n") : spec },
  });
}

const renamed = (from, to, spec, options) =>
  find({ tab: from }, { tab: to }, spec, options);

describe("findStaleText", () => {
  it("names the spec line, the old text and the new one", () => {
    const spec = [
      "await page.goto('/items');",
      "await page.getByRole('tab', { name: /vision ai/i }).click();",
    ];
    expect(renamed("Vision AI", "From photo", spec)).toEqual([
      {
        spec: SPEC,
        line: 2,
        old: "Vision AI",
        next: "From photo",
        path: EN,
        key: "tab",
      },
    ]);
  });

  it("reports a removed key and a removed catalog file", () => {
    const spec = "page.getByText('Execute document');";
    const removed = find({ a: { title: "Execute document" } }, {}, spec);
    expect(removed).toMatchObject([{ key: "a.title", next: undefined }]);
    expect(
      findStaleText({
        before: { [EN]: { title: "Execute document" } },
        after: {},
        specs: { [SPEC]: spec },
      }),
    ).toHaveLength(1);
  });

  it("is quiet while some key of that language still holds the text", () => {
    const spec = "page.getByRole('button', { name: 'Confirm & complete' });";
    const old = { a: "Confirm & complete" };
    const other = "src/modules/warehouse/i18n/en.json";
    expect(
      find(old, { a: "Post" }, spec, {
        also: { [other]: { b: "Confirm & Complete" } },
      }),
    ).toEqual([]);
    // Another language holding it does not keep it on the English screen.
    expect(
      find(old, { a: "Post" }, spec, {
        also: { [PL]: { b: "Confirm & complete" } },
      }),
    ).toHaveLength(1);
  });

  it("reads no comment and no identifier", () => {
    const spec = [
      "// the row reads Checked in",
      "/* Checked in, then out */",
      "const checked = receipt.ordered;",
      "const url = 'https://example.com'; // Ordered",
      "const rows = `got ${receipt.ordered} of ${count({ a: 1 }.ordered)}`;",
    ];
    expect(find({ a: "Checked in", b: "Ordered" }, {}, spec)).toEqual([]);
  });

  it("reads no test title and no error message", () => {
    const spec = [
      'test("a batch is put on hold", async () => {});',
      'test.describe("put on hold", () => {});',
      "await test.step(",
      "  'put on hold',",
      "  async () => {},",
      ");",
      "throw new Error(`could not put on hold: ${reason}`);",
    ];
    expect(renamed("Put on hold", "Quarantine", spec)).toEqual([]);
    // A method that happens to be called `test` is not a test.
    expect(
      renamed("Put on hold", "Quarantine", "pattern.test('put on hold');"),
    ).toHaveLength(1);
  });

  it("searches the longest literal fragment of an interpolated text", () => {
    const spec = [
      "expect(row).toContainText('Ordered 6');",
      "expect(row).toContainText(`6 units`);",
    ];
    expect(
      renamed("Ordered <0>{{quantity}}</0>", "Still due {{quantity}}", spec),
    ).toMatchObject([{ line: 1 }]);
  });

  it("is quiet when only the variable names or the letter case changed", () => {
    const spec = "page.getByText('Delete Add Product');";
    expect(
      find(
        { a: "Delete {{name}}", b: "Add Product" },
        { a: "Delete {{item}}", b: "Add product" },
        spec,
      ),
    ).toEqual([]);
  });

  it("stops at word boundaries", () => {
    const spec = [
      "page.getByText('Removed');",
      "page.getByTestId('photo-remove');",
    ];
    expect(renamed("Remove", "Delete", spec)).toEqual([]);
  });

  it("reads no address, selector or machine value", () => {
    const spec = [
      'await page.goto("/inventory/items");',
      "await expect(page).toHaveURL(/\\/inventory\\/items$/);",
      "await request.get(`/api/v1/items?items=${count}&sort=items`);",
      "page.locator('#items, .items, [items=true]');",
      'const email = "e2e@items.example.com";',
      'expect(body).toEqual({ kind: "items" });',
      "import { seed } from './items.ts';",
    ];
    expect(renamed("Items", "Products", spec)).toEqual([]);
  });

  it("still reads the one word a selector shows", () => {
    const spec = [
      "page.getByRole('link', { name: 'Items' });",
      "page.getByRole('link', { name: /items/i });",
      "page.getByText('Items.');",
      "page.getByText('All items');",
      "page.getByRole('link', { name: /^(items|products-list)$/ });",
    ];
    expect(
      renamed("Items", "Goods", spec).map((finding) => finding.line),
    ).toEqual([1, 2, 3, 4, 5]);
  });

  it("excuses a literal that asks for a longer text the catalogs hold", () => {
    const spec = [
      "page.getByLabel('Qty per batch');",
      "page.getByRole('button', { name: /^Qty per/ });",
    ];
    const old = { cost: "per batch" };
    const held = { qty: "Qty per batch" };
    expect(find(old, held, spec[0])).toEqual([]);
    // The part a selector spells of a held text, anchors aside.
    expect(find({ cost: "Qty" }, held, spec[1])).toEqual([]);
  });

  it("holds an extended text against the spec that spells only the old one", () => {
    const old = "{{n}} of {{total}} lines picked";
    const now = "{{n}} of {{total}} lines picked in full";
    expect(
      renamed(old, now, "toContainText('1 of 2 lines picked')"),
    ).toHaveLength(1);
    expect(
      renamed(old, now, "toContainText('1 of 2 lines picked in full')"),
    ).toEqual([]);
  });

  it("names a phrase of a removed text that no catalog still holds", () => {
    const old = "{{form}} holds unsaved changes. Leave anyway?";
    const now = "{{form}} has changes you have not saved. Leave?";
    const spec = "page.getByText(/holds unsaved changes/i);";
    expect(renamed(old, now, spec)).toMatchObject([{ line: 1, old }]);
    // A phrase some catalog still holds is still on a screen.
    expect(
      renamed(old, now, spec, {
        also: {
          "src/modules/warehouse/i18n/en.json": {
            b: "The form holds unsaved changes",
          },
        },
      }),
    ).toEqual([]);
  });

  it("takes only a phrase of two words, whole words, for a removed text", () => {
    const old = "This place holds unsaved changes";
    const spec = [
      "page.getByText('unsaved');",
      "page.getByText('holds unsaved chang');",
      "page.getByText('1 2');",
    ];
    expect(renamed(old, "Saved", spec)).toEqual([]);
  });

  it("holds a quoted phrase to the catalog's letter case, a regex to none", () => {
    const old = "Enable in the App Store";
    expect(renamed(old, "Enable it", "const name = 'App store';")).toEqual([]);
    expect(
      renamed(old, "Enable it", "page.getByText('App Store');"),
    ).toHaveLength(1);
    expect(
      renamed(old, "Enable it", "page.getByText(/app store/i);"),
    ).toHaveLength(1);
  });

  it("reads a text through the escapes of a regex or a string", () => {
    const spec = [
      "name: /add \\(new\\)/i",
      "getByText('Don\\'t ask')",
      "name: /\\bCheck in\\b/",
    ];
    expect(
      find({ a: "Add (new)", b: "Don't ask", c: "Check in" }, {}, spec),
    ).toMatchObject([{ line: 1 }, { line: 2 }, { line: 3 }]);
  });

  it("reports the line inside a literal that spans several", () => {
    const spec = "const text = `first\nVision AI`;";
    expect(renamed("Vision AI", "From photo", spec)).toMatchObject([
      { line: 2 },
    ]);
  });

  it("searches Polish in the Polish spec alone, English everywhere else", () => {
    const polish = "tests/e2e/polish-ui.spec.ts";
    const spec = "page.getByText('Dokumenty');";
    const options = { path: PL };
    expect(renamed("Dokumenty", "Papiery", spec, options)).toEqual([]);
    expect(
      renamed("Dokumenty", "Papiery", spec, { ...options, specPath: polish }),
    ).toHaveLength(1);
    expect(
      renamed("Documents", "Papers", "'Documents'", { specPath: polish }),
    ).toEqual([]);
  });
});

describe("the gate as a process", () => {
  let repo;
  afterEach(() => {
    vi.unstubAllEnvs();
    repo.cleanup();
  });

  /**
   * Run the gate on a tree whose base held `base` in the English catalog. The
   * frontend container has no git, so a stand-in answers the three questions.
   */
  function run(base, { gitFails = false } = {}) {
    repo = makeRepo();
    repo.write({
      [`frontend/${EN}`]: { tab: "From photo" },
      "frontend/src/modules/inventory/i18n/en.json": { title: "Products" },
      [`frontend/${SPEC}`]:
        "await page.getByRole('tab', { name: /vision ai/i }).click();\n",
      "bin/git": [
        `#!${process.execPath}`,
        `const [command] = process.argv.slice(2);`,
        gitFails
          ? `console.error("fatal: Not a valid object name"); process.exit(128);`
          : `process.stdout.write({`,
        ...(gitFails
          ? []
          : [
              `  "merge-base": "abc123\\n",`,
              `  diff: ${JSON.stringify(`${EN}\n`)},`,
              `  show: ${JSON.stringify(JSON.stringify(base))},`,
              `}[command]);`,
            ]),
      ].join("\n"),
    });
    chmodSync(join(repo.root, "bin", "git"), 0o755);
    vi.stubEnv(
      "PATH",
      `${join(repo.root, "bin")}${delimiter}${process.env.PATH}`,
    );
    return runGate(repo, "check-e2e-catalog-text.mjs", {
      siblings: ["source-text.mjs"],
    });
  }

  it("exits 1 on a renamed text a spec clicks", () => {
    const result = run({ tab: "Vision AI" });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain(
      `frontend/${SPEC}:1  "Vision AI" -> "From photo"`,
    );
  });

  it("exits 0 when no spec spells what changed", () => {
    expect(run({ tab: "Take a picture" }).status).toBe(0);
  });

  it("exits 2, not 0, when the base cannot be read", () => {
    const result = run({}, { gitFails: true });
    expect(result.status).toBe(2);
    expect(result.stderr).toContain("Not a valid object name");
  });
});
