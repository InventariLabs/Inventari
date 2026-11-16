import { describe, expect, it } from "vitest";
import { resolve } from "node:path";
import {
  declaredLanguages,
  maintainedLanguages,
} from "./maintained-languages.mjs";
import { MAINTAINED_LANGUAGES } from "../src/test/languageClasses";

describe("maintained-languages", () => {
  it("separates the community entries from the maintained ones", () => {
    const text = `export const LANGUAGES = [
      { code: "en", name: "EN", fullName: "English", flag: "x" },
      { code: "xx", name: "XX", fullName: "Xish", flag: "y", community: true },
    ] as const;`;
    expect(declaredLanguages(text)).toEqual([
      { code: "en", community: false },
      { code: "xx", community: true },
    ]);
  });

  it("agrees with the runtime's own split of the shipped declaration", () => {
    const root = resolve(import.meta.dirname, "..");
    expect(maintainedLanguages(root)).toEqual([...MAINTAINED_LANGUAGES]);
  });
});
