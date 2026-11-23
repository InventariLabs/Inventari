/**
 * The measurements of the raw-machine-values gate: each shape is planted in a
 * snippet no baseline holds and has to be found, and each shape the app does
 * right has to pass. The passes the gate comes from: the Columns menu that
 * built `table.columns.assigned_to` against a catalogue key `assignedTo`, and
 * a Polish screen printing `13.8 g` beside `0,0 dni`.
 */
import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  diffBaseline,
  dynamicKeysIn,
  isScanned,
  missingEnumerated,
  rawNumbersIn,
} from "./check-raw-machine-values.mjs";

const ROOT = join(
  dirname(fileURLToPath(import.meta.url).replace(/^\/@fs/, "")),
  "..",
);

describe("a translation key built from an id", () => {
  it("is found when nothing enumerates it", () => {
    const found = dynamicKeysIn("<th>{t(`table.columns.${key}`)}</th>");

    expect(found).toEqual([
      { line: 1, template: "table.columns.${key}", enumerated: null },
    ]);
  });

  it("is found when written as a concatenation", () => {
    const found = dynamicKeysIn('t("table.columns." + col.id)');

    expect(found).toHaveLength(1);
    expect(found[0].enumerated).toBeNull();
  });

  it("reads the enumeration on the line above", () => {
    const [found] = dynamicKeysIn(
      "// i18n-keys: name | assignedTo\nt(`table.columns.${key}`)",
    );

    expect(found.enumerated).toEqual(["name", "assignedTo"]);
  });

  it("leaves a literal key alone", () => {
    expect(dynamicKeysIn('t("table.columns.name")')).toEqual([]);
  });

  it("is found when the key is held in a variable first", () => {
    const found = dynamicKeysIn(
      "const key = `items:fields.${field.key}`;\nconst out = tDyn(key);",
    );

    expect(found).toEqual([
      { line: 2, template: "items:fields.${field.key}", enumerated: null },
    ]);
  });

  it("reads the enumeration above the call that uses a held key", () => {
    const [found] = dynamicKeysIn(
      "const key = `table.columns.${id}`;\n// i18n-keys: name\nt(key);",
    );

    expect(found.enumerated).toEqual(["name"]);
  });

  it("leaves a variable that holds a literal key alone", () => {
    expect(dynamicKeysIn('const key = `table.name`;\nt(key);')).toEqual([]);
    expect(dynamicKeysIn("t(key);")).toEqual([]);
  });

  it("fails an enumeration that names a key one catalogue lacks", () => {
    const [found] = dynamicKeysIn(
      "// i18n-keys: name | assigned_to\nt(`table.columns.${key}`)",
    );
    const catalogs = new Map([
      ["en", new Set(["table.columns.name", "table.columns.assignedTo"])],
      ["pl", new Set(["table.columns.name"])],
    ]);

    expect(missingEnumerated(found, catalogs)).toEqual([
      "en:table.columns.assigned_to",
      "pl:table.columns.assigned_to",
    ]);
  });

  it("passes an enumeration every catalogue carries", () => {
    const [found] = dynamicKeysIn(
      "// i18n-keys: name\nt(`items:table.columns.${key}`)",
    );
    const catalogs = new Map([["en", new Set(["table.columns.name"])]]);

    expect(missingEnumerated(found, catalogs)).toEqual([]);
  });
});

describe("a number or a date outside the reader's locale", () => {
  it("finds toFixed inside a template hole", () => {
    expect(rawNumbersIn("const s = `${(a / b).toFixed(1)} g`;")).toEqual([
      { line: 1, what: "toFixed" },
    ]);
  });

  it("finds a numeric field in a sentence", () => {
    expect(rawNumbersIn("<b>{`${day.carbs_g} g`}</b>")).toEqual([
      { line: 1, what: "number" },
    ]);
  });

  it("finds a literal locale", () => {
    expect(
      rawNumbersIn('new Intl.DateTimeFormat("en-US").format(d)'),
    ).toHaveLength(1);
    expect(rawNumbersIn("d.toLocaleDateString()")).toHaveLength(1);
  });

  it("leaves a locale taken from the reader alone", () => {
    expect(rawNumbersIn("d.toLocaleDateString(i18n.language)")).toEqual([]);
  });

  it("leaves a rounded value turned back into a number alone", () => {
    expect(rawNumbersIn("const q = Number((x * y).toFixed(4));")).toEqual([]);
  });

  it("leaves a template with no sentence around the field alone", () => {
    expect(rawNumbersIn("const k = `${row.unit_price}`;")).toEqual([]);
  });
});

describe("the gate over the tree", () => {
  it("does not scan the formatters it points at", () => {
    expect(isScanned("utils/formatters.ts")).toBe(false);
    expect(isScanned("modules/x/Card.tsx")).toBe(true);
    expect(isScanned("modules/x/Card.test.tsx")).toBe(false);
  });

  it("counts only what is above the baseline", () => {
    expect(
      diffBaseline({ "a.tsx::toFixed": 2 }, { "a.tsx::toFixed": 2 }),
    ).toEqual([]);
    expect(
      diffBaseline({ "a.tsx::toFixed": 3 }, { "a.tsx::toFixed": 2 }),
    ).toEqual([{ key: "a.tsx::toFixed", was: 2, now: 3 }]);
    expect(diffBaseline({ "b.tsx::number": 1 }, {})).toHaveLength(1);
  });

  it("is green on the tree against its baseline", () => {
    const run = spawnSync(
      "node",
      ["scripts/check-raw-machine-values.mjs", "--baseline"],
      {
        cwd: ROOT,
        encoding: "utf8",
      },
    );

    expect(run.status, run.stderr).toBe(0);
  });
});
