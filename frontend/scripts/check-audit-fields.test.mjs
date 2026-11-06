/**
 * The gate that compares what the backend writes into audit snapshots with
 * what the five catalogues can say about it.
 *
 * Two things it has to get right, and both are the reason the forty English
 * fields went unnoticed for so long: it has to see a gap at all, and it has
 * to see one that is missing in a single language. A gate that only reads
 * `en` calls a key translated into English and Polish clean while the German
 * reader is still looking at `old_quantity`.
 */
import { afterAll, describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { catalogKeys, gaps } from "./check-audit-fields.mjs";

const ROOT = join(
  dirname(fileURLToPath(import.meta.url).replace(/^\/@fs/, "")),
  "..",
);

describe("check-audit-fields", () => {
  it("sees a key no catalogue names", () => {
    const found = gaps(
      ["barcode", "a_field_nobody_named"],
      new Map([
        ["en", new Set(["barcode"])],
        ["pl", new Set(["barcode"])],
      ]),
    );

    expect(found).toEqual([
      { language: "en", key: "a_field_nobody_named" },
      { language: "pl", key: "a_field_nobody_named" },
    ]);
  });

  it("sees a key one catalogue is missing, not only a key all of them are", () => {
    const found = gaps(
      ["barcode"],
      new Map([
        ["en", new Set(["barcode"])],
        ["pl", new Set(["barcode"])],
        ["de", new Set()],
        ["fr", new Set(["barcode"])],
        ["es", new Set(["barcode"])],
      ]),
    );

    expect(found).toEqual([{ language: "de", key: "barcode" }]);
  });

  it("is quiet when every catalogue names every declared key", () => {
    expect(
      gaps(
        ["barcode"],
        new Map([
          ["en", new Set(["barcode"])],
          ["pl", new Set(["barcode"])],
        ]),
      ),
    ).toEqual([]);
  });

  it("reads the tree's own catalogues", () => {
    const perLanguage = catalogKeys();

    expect([...perLanguage.keys()]).toEqual(["en", "pl", "de", "fr", "es"]);
    // The catalogs the journal reads are the ones the app ships, so a
    // renamed namespace fails here rather than in production.
    expect(perLanguage.get("pl").size).toBeGreaterThan(100);
  });

  it("names every declared key in every catalogue, today", () => {
    const declared = JSON.parse(
      readFileSync(join(ROOT, "scripts/audit-snapshot-keys.json"), "utf8"),
    ).keys;

    expect(gaps(declared)).toEqual([]);
  });

  it("names every target type the backend declares in every catalogue, today", () => {
    const declared = JSON.parse(
      readFileSync(join(ROOT, "scripts/audit-snapshot-keys.json"), "utf8"),
    )["target-types"];

    expect(declared.length).toBeGreaterThan(20);
    expect(gaps(declared, catalogKeys(undefined, "targetTypes"))).toEqual([]);
  });

  it("writes and reloads a baseline without losing a gap", () => {
    // The baseline is the escape hatch for a key that was already untranslated
    // when the gate arrived. If it silently loses entries, "no gap beyond the
    // baseline" starts meaning "no gap at all" — which is a green gate over
    // the exact defect it was built for.
    const dir = mkdtempSync(join(tmpdir(), "audit-baseline-"));
    const file = join(dir, "baseline.json");
    try {
      const recorded = [
        { language: "pl", key: "old_quantity" },
        { language: "de", key: "old_quantity" },
      ];
      writeFileSync(file, JSON.stringify({ gaps: recorded }));
      const reloaded = JSON.parse(readFileSync(file, "utf8")).gaps;

      expect(reloaded).toHaveLength(2);
      expect(reloaded).toEqual(recorded);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("check-audit-fields label gaps", () => {
  // The teeth of the label half, run as the Makefile runs the gate: one
  // catalogue key removed and the gate has to fall *and name the field*.
  // Forty keys reached the journal in English with nothing set up to notice
  // — this is the noticing.
  const dir = mkdtempSync(join(tmpdir(), "audit-labels-"));
  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  it("falls and names the field when one catalogue key is removed", () => {
    for (const language of ["en", "pl", "de", "fr", "es"]) {
      mkdirSync(join(dir, language), { recursive: true });
      const json = JSON.parse(
        readFileSync(
          join(ROOT, `src/i18n/locales/${language}/common.json`),
          "utf8",
        ),
      );
      delete json.settings.audit.fields.barcode;
      writeFileSync(join(dir, language, "common.json"), JSON.stringify(json));
    }

    const { status, stdout, stderr } = spawnSync(
      "node",
      ["scripts/check-audit-fields.mjs"],
      {
        cwd: ROOT,
        encoding: "utf8",
        env: { ...process.env, AUDIT_LOCALES_DIR: dir },
      },
    );
    const output = `${stdout}${stderr}`;

    expect(status).toBe(1);
    expect(output).toContain("en: barcode");
    expect(output).toContain("pl: barcode");
    expect(output).toContain("settings.audit.fields.barcode");
  });
});

describe("check-audit-fields target-type gaps", () => {
  // Same teeth as the field labels: a type removed from the catalogues has to
  // fail the gate and be named, in the section it belongs to.
  const dir = mkdtempSync(join(tmpdir(), "audit-target-types-"));
  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  it("falls and names the type when one catalogue entry is removed", () => {
    for (const language of ["en", "pl", "de", "fr", "es"]) {
      mkdirSync(join(dir, language), { recursive: true });
      const json = JSON.parse(
        readFileSync(
          join(ROOT, `src/i18n/locales/${language}/common.json`),
          "utf8",
        ),
      );
      if (language !== "fr") delete json.settings.audit.targetTypes.stock_lot;
      writeFileSync(join(dir, language, "common.json"), JSON.stringify(json));
    }

    const { status, stdout, stderr } = spawnSync(
      "node",
      ["scripts/check-audit-fields.mjs", "--baseline"],
      {
        cwd: ROOT,
        encoding: "utf8",
        env: { ...process.env, AUDIT_LOCALES_DIR: dir },
      },
    );
    const output = `${stdout}${stderr}`;

    expect(status).toBe(1);
    expect(output).toContain("en: stock_lot (targetTypes)");
    expect(output).toContain("de: stock_lot (targetTypes)");
    expect(output).not.toContain("fr: stock_lot");
    expect(output).toContain("settings.audit.targetTypes.stock_lot");
  });
});

/**
 * The other half of the gate: the artefact has to be the one the backend is
 * writing now.
 *
 * `enabled_modules` reached the journal's snapshots, the saved artefact went
 * on holding the 122 keys it was generated with, and the label half called the
 * journal clean while a reader was looking at the raw field name on screen. A
 * gate that reads an input nobody refreshes is green about a tree that no
 * longer exists — so the fixture here is exactly that state, and the check is
 * that it comes back red.
 */
describe("check-audit-fields --freshness", () => {
  const dir = mkdtempSync(join(tmpdir(), "audit-freshness-"));

  function artifact(path, keys, declarationsRead, uncovered = []) {
    writeFileSync(
      path,
      JSON.stringify({
        "declarations-read": declarationsRead ?? 4,
        "uncovered-writer-files": uncovered,
        "key-count": keys.length,
        keys,
      }),
    );
    return path;
  }

  /** The gate as the Makefile runs it: both artefacts handed in by path. */
  function runGate(savedPath, freshPath) {
    const env = { ...process.env, AUDIT_KEYS: savedPath };
    if (freshPath) env.AUDIT_KEYS_FRESH = freshPath;
    const { status, stdout, stderr } = spawnSync(
      "node",
      ["scripts/check-audit-fields.mjs", "--freshness", "--baseline"],
      { cwd: ROOT, encoding: "utf8", env },
    );
    return { status, output: `${stdout}${stderr}` };
  }

  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  it("fails when the artefact has not kept up with the writers", () => {
    const saved = artifact(join(dir, "saved.json"), [
      "barcode",
      "old_quantity",
    ]);
    const fresh = artifact(join(dir, "fresh.json"), [
      "barcode",
      "old_quantity",
      "enabled_modules",
    ]);

    const { status, output } = runGate(saved, fresh);

    expect(status).toBe(1);
    expect(output).toContain("missing: enabled_modules");
    expect(output).toContain("make sync-audit-fields");
  });

  it("fails when the artefact holds a key the writers dropped", () => {
    const saved = artifact(join(dir, "saved-extra.json"), [
      "barcode",
      "a_field_the_writers_dropped",
    ]);
    const fresh = artifact(join(dir, "fresh-narrower.json"), ["barcode"]);

    const { status, output } = runGate(saved, fresh);

    expect(status).toBe(1);
    expect(output).toContain("no longer declared: a_field_the_writers_dropped");
  });

  it("fails when the artefact has not kept up with the target types", () => {
    const withTypes = (path, types) => {
      writeFileSync(
        path,
        JSON.stringify({
          "declarations-read": 4,
          "uncovered-writer-files": [],
          keys: ["barcode"],
          "target-types": types,
        }),
      );
      return path;
    };
    const saved = withTypes(join(dir, "saved-types.json"), ["item"]);
    const fresh = withTypes(join(dir, "fresh-types.json"), ["item", "label"]);

    const { status, output } = runGate(saved, fresh);

    expect(status).toBe(1);
    expect(output).toContain("missing: label");
    expect(output).toContain("make sync-audit-fields");
  });

  it("fails when a writer lost its declaration at the same keys", () => {
    // The declarations-read counter exists so a writer without its
    // declaration shows as a fall, not as no writer: keys can stay identical
    // (a duplicate pair elsewhere) while a writer went unread. Comparing
    // keys alone is how a renamed declaration once passed the gate.
    const saved = artifact(join(dir, "saved-declared.json"), ["barcode"], 4);
    const fresh = artifact(join(dir, "fresh-undeclared.json"), ["barcode"], 3);

    const { status, output } = runGate(saved, fresh);

    expect(status).toBe(1);
    expect(output).toContain(
      "declarations-read moved — saved 4, the backend declares 3 today",
    );
  });

  it("fails when a funnel writer loses its declaration file", () => {
    // uncovered-writer-files is the artefact naming the writers it could not
    // read. Saved and exported have to agree on it, or a new undeclared
    // writer ships behind a regenerated-looking artefact.
    const saved = artifact(join(dir, "saved-covered.json"), ["barcode"], 4, []);
    const fresh = artifact(join(dir, "fresh-uncovered.json"), ["barcode"], 4, [
      "app.services.thing_config",
    ]);

    const { status, output } = runGate(saved, fresh);

    expect(status).toBe(1);
    expect(output).toContain("uncovered-writer-files");
    expect(output).toContain("app.services.thing_config");
  });

  it("says nothing when the artefact is the one just exported", () => {
    const same = ["barcode", "old_quantity"];
    const saved = artifact(join(dir, "saved-same.json"), same);
    const fresh = artifact(join(dir, "fresh-same.json"), same);

    const { status, output } = runGate(saved, fresh);

    expect(status).toBe(0);
    expect(output).toContain("matches the 2 key(s) the backend declares today");
  });

  it("refuses when it was handed no freshly exported artefact", () => {
    // A gate that cannot say what it looked at is a gate nobody can trust:
    // asking for the mode without the export is a usage error, not a pass.
    const saved = artifact(join(dir, "saved-lonely.json"), ["barcode"]);

    const { status, output } = runGate(saved, null);

    expect(status).toBe(2);
    expect(output).toContain("AUDIT_KEYS_FRESH is not set");
  });
});
