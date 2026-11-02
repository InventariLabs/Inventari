/**
 * A baseline that carries the moment it was written changes on every
 * `--write-baseline`, so two branches that each touch the same baseline
 * conflict on that line even when they froze different findings. Nothing
 * reads the stamp; the snapshots must stay a pure function of the tree.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const files = readdirSync(HERE);

describe("baseline snapshots", () => {
  const baselines = files.filter((name) => name.endsWith("-baseline.json"));

  it("finds the baselines it is meant to guard", () => {
    expect(baselines.length).toBeGreaterThan(10);
  });

  it.each(baselines)("%s carries no generation timestamp", (name) => {
    const body = JSON.parse(readFileSync(resolve(HERE, name), "utf8"));
    expect(Object.keys(body)).not.toContain("generated");
  });

  const writers = files.filter(
    (name) => /^check-.*\.mjs$/.test(name) && !name.endsWith(".test.mjs"),
  );

  it.each(writers)("%s writes no generation timestamp", (name) => {
    const source = readFileSync(resolve(HERE, name), "utf8");
    expect(source).not.toMatch(/generated:\s*new Date\(/);
  });
});
