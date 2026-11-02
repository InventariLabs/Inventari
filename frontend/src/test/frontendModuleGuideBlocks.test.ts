import { afterAll, beforeAll, describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { typecheckScratch } from "./typecheckScratch";

/**
 * docs/FRONTEND_MODULE_GUIDE.md's code blocks, pasted into a module as written.
 *
 * Its "Typed slots (recommended)" example registered a typed component bare,
 * and pasted into a package it failed `tsc --noEmit` with TS2322: the registry
 * keeps every slot's component under one erased type, and only
 * `slotComponent()` puts a narrower one there. Each block preceded by
 * `<!-- typecheck: <file> -->` is written to that path of a scratch module
 * inside the frontend and the module is type-checked with the project's
 * compiler settings.
 *
 * Its "Example test" imported `vi` without using it (TS6133 under the
 * project's settings), so it is held to the same rule.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "../..");
const REPO_ROOT =
  process.env.INVENTARI_REPO_ROOT ?? path.resolve(FRONTEND, "..");
const SCRATCH = path.join(FRONTEND, ".frontend-module-guide");

const BLOCK = /<!-- typecheck: (\S+) -->\s*```\w+\n([\s\S]*?)\n```/g;

const files = new Map(
  [
    ...fs
      .readFileSync(
        path.join(REPO_ROOT, "docs", "FRONTEND_MODULE_GUIDE.md"),
        "utf8",
      )
      .matchAll(BLOCK),
  ].map((m) => [m[1], m[2]]),
);

beforeAll(() => {
  fs.rmSync(SCRATCH, { recursive: true, force: true });
  for (const [name, source] of files) {
    const target = path.join(SCRATCH, name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, `${source}\n`);
  }
});

afterAll(() => {
  fs.rmSync(SCRATCH, { recursive: true, force: true });
});

describe("FRONTEND_MODULE_GUIDE code blocks", () => {
  it("marks the page, its test, the registration and the typed slots", () => {
    expect([...files.keys()]).toEqual(
      expect.arrayContaining([
        "pages/IndexPage.tsx",
        "pages/IndexPage.test.tsx",
        "module.ts",
        "components/ExtraFields.tsx",
        "components/GradeField.tsx",
      ]),
    );
  });

  it("type-checks as written", () => {
    expect(typecheckScratch(FRONTEND, SCRATCH, [...files.keys()])).toEqual([]);
  }, 120_000);
});
