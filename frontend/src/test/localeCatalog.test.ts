import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  coverageFindings,
  coverageOf,
  enKeySet,
  flatLeafValues,
  listLanguages,
  listNamespaces,
  readCatalog,
  readCoverageDeclaration,
} from "./localeCatalog";

/**
 * The directory is the data. These fixtures prove the reading: a language
 * directory that appears is discovered without any list being edited, an
 * empty value counts as missing, and the coverage number moves with the
 * catalog — not with anything typed in code.
 */

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "locale-catalog-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function makeLanguage(name: string, files: Record<string, unknown>): void {
  mkdirSync(join(dir, name), { recursive: true });
  for (const [file, content] of Object.entries(files)) {
    writeFileSync(join(dir, name, `${file}.json`), JSON.stringify(content));
  }
}

describe("listLanguages", () => {
  it("discovers a language directory nobody typed into a list", () => {
    makeLanguage("en", { common: {} });
    makeLanguage("pl", { common: {} });
    expect(listLanguages(dir)).toEqual(["en", "pl"]);

    // A seventh language lands as a directory. No edit here, no edit there.
    makeLanguage("it", { common: {} });
    expect(listLanguages(dir)).toEqual(["en", "it", "pl"]);
  });

  it("reads directories only — loose files are not languages", () => {
    makeLanguage("en", { common: {} });
    writeFileSync(join(dir, "coverage.json"), "{}");
    expect(listLanguages(dir)).toEqual(["en"]);
  });

  it("is empty when the directory does not exist", () => {
    expect(listLanguages(join(dir, "missing"))).toEqual([]);
  });
});

describe("listNamespaces", () => {
  it("lists a language's json files without the suffix, others ignored", () => {
    makeLanguage("en", { common: {}, items: {} });
    writeFileSync(join(dir, "en", "notes.txt"), "not a namespace");
    expect(listNamespaces(dir, "en")).toEqual(["common", "items"]);
  });
});

describe("flatLeafValues", () => {
  it("walks to string leaves with dotted paths, arrays indexed", () => {
    const leaves = flatLeafValues({
      nav: { items: "Products", plural: ["a", "b"] },
      deep: { nested: { value: "" } },
    });
    expect(Object.fromEntries(leaves)).toEqual({
      "nav.items": "Products",
      "nav.plural.0": "a",
      "nav.plural.1": "b",
      "deep.nested.value": "",
    });
  });
});

describe("readCatalog", () => {
  it("returns null for a missing file and for a broken one", () => {
    expect(readCatalog(join(dir, "nope.json"))).toBeNull();
    writeFileSync(join(dir, "broken.json"), "{ not json");
    expect(readCatalog(join(dir, "broken.json"))).toBeNull();
  });
});

describe("coverageOf", () => {
  beforeEach(() => {
    makeLanguage("en", {
      common: { save: "Save", cancel: "Cancel", nav: { home: "Home" } },
      items: { one: "One item" },
    });
    makeLanguage("pl", {
      common: { save: "Zapisz", cancel: "", nav: { home: "Start" } },
      items: { one: "Jeden", extra: "Dodatkowy" },
    });
  });

  it("counts non-empty values against en and names what is missing", () => {
    const enKeys = enKeySet(dir, ["common", "items"]);
    const coverage = coverageOf(dir, "pl", ["common", "items"], enKeys);
    // empty string and absent key are both missing; the extra key does not
    // count. Keys are namespace-qualified — i18next's own identity.
    expect(enKeys).toEqual([
      "common:cancel",
      "common:nav.home",
      "common:save",
      "items:one",
    ]);
    expect(coverage).toMatchObject({
      present: 3,
      total: 4,
      percent: 75,
      missing: ["common:cancel"],
      extra: ["items:extra"],
    });
  });

  it("does not let a key in one namespace answer a miss in another", () => {
    makeLanguage("en", {
      common: { title: "Common title", shared: "Shared" },
      items: { title: "Items title", shared: "Shared" },
    });
    makeLanguage("lt", {
      common: { title: "Bendras", shared: "Bendras" },
      items: { title: "", shared: "" },
    });
    const enKeys = enKeySet(dir, ["common", "items"]);
    const coverage = coverageOf(dir, "lt", ["common", "items"], enKeys);
    // `common:*` answers only common. Without the namespace in the key the
    // same names under items hid behind common's values and this language
    // read as complete — green while two items keys reached the screen raw.
    expect(coverage).toMatchObject({
      present: 2,
      total: 4,
      percent: 50,
      missing: ["items:shared", "items:title"],
    });
  });

  it("gives zero when the language's file for a namespace is absent", () => {
    const enKeys = enKeySet(dir, ["common", "items"]);
    const coverage = coverageOf(dir, "de", ["common", "items"], enKeys);
    expect(coverage).toMatchObject({ present: 0, total: 4, percent: 0 });
    expect(coverage.missing).toHaveLength(4);
  });

  it("floors to one decimal, never rounds a near-complete language up", () => {
    const thousand: Record<string, string> = {};
    for (let i = 0; i < 1000; i += 1) thousand[`key${i}`] = `Value ${i}`;
    rmSync(join(dir, "en"), { recursive: true });
    makeLanguage("en", { common: thousand });
    const nearly: Record<string, string> = {
      ...thousand,
      key998: "",
      key999: "",
    };
    makeLanguage("big", { common: nearly });
    const enOnly = enKeySet(dir, ["common"]);
    const coverage = coverageOf(dir, "big", ["common"], enOnly);
    // 998 of 1000 → 99.8 floored, though ordinary rounding would say 99.8
    // and optimistic rounding 100: a near-complete language may not pass
    // itself off as complete.
    expect(coverage.percent).toBe(99.8);
  });
});

describe("readCoverageDeclaration", () => {
  it("returns null for a missing or malformed file", () => {
    expect(readCoverageDeclaration(join(dir, "nope.json"))).toBeNull();
    writeFileSync(join(dir, "bad.json"), "not json");
    expect(readCoverageDeclaration(join(dir, "bad.json"))).toBeNull();
    writeFileSync(join(dir, "array.json"), "[]");
    expect(readCoverageDeclaration(join(dir, "array.json"))).toBeNull();
  });

  it("returns the declared numbers", () => {
    writeFileSync(join(dir, "cov.json"), JSON.stringify({ pl: 100, it: 42.5 }));
    expect(readCoverageDeclaration(join(dir, "cov.json"))).toEqual({
      pl: 100,
      it: 42.5,
    });
  });
});

describe("coverageFindings", () => {
  const namespaces = ["common"];

  /** English, a maintained language and a community one, all complete. */
  function complete(): void {
    const catalog = { a: "A", b: "B" };
    makeLanguage("en", { common: catalog });
    makeLanguage("pl", { common: catalog });
    makeLanguage("pt", { common: catalog });
  }

  function findings(
    language: string,
    community: boolean,
    declaredKeys: number,
  ) {
    const enKeys = enKeySet(dir, namespaces);
    return coverageFindings(coverageOf(dir, language, namespaces, enKeys), {
      community,
      declaredKeys,
    });
  }

  it("is satisfied by complete languages of either class", () => {
    complete();

    expect(findings("pl", false, 2)).toEqual([]);
    expect(findings("pt", true, 2)).toEqual([]);
  });

  it("lets a string added in English and the maintained languages leave a community language green", () => {
    complete();
    // The change adds `c` to en and pl only; pt stays at 2 of 3 keys.
    makeLanguage("en", { common: { a: "A", b: "B", c: "C" } });
    makeLanguage("pl", { common: { a: "A", b: "B", c: "C" } });

    expect(findings("pl", false, 2)).toEqual([]);
    expect(findings("pt", true, 2)).toEqual([]);
  });

  it("fails a maintained language that lacks the new string, whatever it declared", () => {
    complete();
    makeLanguage("en", { common: { a: "A", b: "B", c: "C" } });

    expect(findings("pl", false, 2)).toEqual(["missing common:c"]);
  });

  it("fails a community language that drops below the number it declared", () => {
    complete();
    makeLanguage("pt", { common: { a: "A", b: "" } });

    expect(findings("pt", true, 2)).toEqual([
      "holds 1 keys, below the 2 it declared",
    ]);
  });
});
