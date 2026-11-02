import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, describe, expect, it } from "vitest";

import { collectOffenders, lineOffends } from "./check-en-spelling.mjs";

/**
 * The gate is a one-word rule; what is worth pinning is that it reads every
 * casing of the British spelling, stays silent about words that merely
 * contain the same letters ("organization" itself), and that the scan names
 * the offending file and line.
 */
describe("lineOffends", () => {
  it("flags the British spelling in any casing", () => {
    expect(
      lineOffends('"subtitle": "What each role in this organisation may do."'),
    ).toBe(true);
    expect(lineOffends('"name": "Organisation Settings"')).toBe(true);
    expect(lineOffends("ORGANISATION")).toBe(true);
  });

  it("stays silent about the product spelling and unrelated words", () => {
    expect(
      lineOffends('"subtitle": "What each role in this organization may do."'),
    ).toBe(false);
    expect(lineOffends('"hint": "reorganize your shelves"')).toBe(false);
    expect(lineOffends('"note": "Organize imports on save"')).toBe(false);
  });
});

describe("collectOffenders", () => {
  const dir = mkdtempSync(join(tmpdir(), "en-spelling-"));
  const clean = join(dir, "clean.json");
  const dirty = join(dir, "dirty.json");
  writeFileSync(
    clean,
    '{\n  "a": "Ask an administrator of your organization."\n}\n',
  );
  writeFileSync(
    dirty,
    '{\n  "a": "all good",\n  "b": "What each role in this organisation may do."\n}\n',
  );

  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  it("names the file and line of every offender and skips clean files", () => {
    const offenders = collectOffenders([clean, dirty]);
    expect(offenders).toHaveLength(1);
    expect(offenders[0]).toContain(dirty);
    expect(offenders[0]).toMatch(/:3: /);
    expect(offenders[0]).toContain("organisation");
  });

  it("returns nothing for a set of clean files", () => {
    expect(collectOffenders([clean, clean])).toEqual([]);
  });
});
