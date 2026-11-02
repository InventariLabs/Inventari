import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { MOVE_SOURCE_DESTINATIONS } from "../moveSourceLink";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Every source a stock move can come from has a word in every language.
 *
 * The moves register printed "maker_production" in the SOURCE column, in a
 * table where every other row said a normal word. The translation existed —
 * under the key `production`, which nothing sends: the backend writes
 * `maker_production`, and `defaultValue` printed the raw identifier. Beside
 * it sat two keys, `manual` and `transfer`, that no code path has ever
 * written.
 *
 * So the vocabulary is read from the backend rather than restated here.
 * `StockMoveReferenceType` documents what actually lands in the column,
 * in the core contract a module imports it from; a value added there
 * fails this test until it has a label, and a label left behind fails it
 * until it is removed.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../../..");
const CONTRACTS = path.join(
  REPO_ROOT,
  "backend/app/core/contracts/_stock_dtos.py",
);

/** The string constants of `class StockMoveReferenceType`. */
function declaredReferenceTypes(): string[] {
  const source = fs.readFileSync(CONTRACTS, "utf8");
  const body = source.split("class StockMoveReferenceType")[1];
  expect(
    body,
    `StockMoveReferenceType not found in ${CONTRACTS}`,
  ).toBeDefined();
  const declaration = body.split(/\nclass /)[0];
  return [...declaration.matchAll(/^\s{4}[A-Z_]+ = '([a-z_]+)'$/gm)].map(
    (m) => m[1],
  );
}

function labels(lang: string): Record<string, string> {
  const file = path.join(HERE, "..", "i18n", `${lang}.json`);
  const catalogue = JSON.parse(fs.readFileSync(file, "utf8"));
  return catalogue.moves.source ?? {};
}

describe("the SOURCE column of the moves register", () => {
  it("reads a vocabulary the backend actually writes", () => {
    // A guard on the guard: a rename in the contract that this regex
    // stops matching would otherwise make the test below pass on an
    // empty list.
    expect(declaredReferenceTypes().length).toBeGreaterThanOrEqual(5);
  });

  it.each(MAINTAINED_LANGUAGES)(
    "names every source a move can have (%s)",
    (lang) => {
      const catalogue = labels(lang);

      for (const value of declaredReferenceTypes()) {
        expect(
          catalogue[value],
          `moves.source.${value} missing in ${lang}`,
        ).toBeTruthy();
      }
    },
  );

  it.each(MAINTAINED_LANGUAGES)("keeps no label nobody sends (%s)", (lang) => {
    const declared = declaredReferenceTypes();

    expect(Object.keys(labels(lang)).sort()).toEqual([...declared].sort());
  });

  it("decides for every source whether it leads anywhere", () => {
    // A sixth kind must not fall through as "leads nowhere" by omission:
    // the map is exhaustive, and `null` is a decision written down.
    expect(Object.keys(MOVE_SOURCE_DESTINATIONS).sort()).toEqual(
      [...declaredReferenceTypes()].sort(),
    );
  });
});
