/**
 * The languages every change must carry in full, read from the one
 * declaration of them: `src/i18n/languages.ts`.
 *
 * The gate scripts are plain Node and cannot import that TypeScript module
 * (it pulls a JSON file in through the bundler), so this reads its text: one
 * `{ code: "xx", … }` entry per language, a `community: true` marking the ones
 * that ship below full coverage. A language added as maintained is then
 * checked by every gate the moment it is declared, instead of being skipped by
 * a five-code list copied into each script.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** Every declared language as `{ code, community }`, in declaration order. */
export function declaredLanguages(declarationText) {
  const entries = [
    ...declarationText.matchAll(/\{\s*code:\s*"([a-z]{2,3})"[^}]*\}/g),
  ];
  return entries.map((entry) => ({
    code: entry[1],
    community: /community:\s*true/.test(entry[0]),
  }));
}

/** The maintained languages of the tree rooted at `root` (`frontend/`). */
export function maintainedLanguages(root) {
  const text = readFileSync(resolve(root, "src/i18n/languages.ts"), "utf-8");
  const codes = declaredLanguages(text)
    .filter((language) => !language.community)
    .map((language) => language.code);
  if (!codes.includes("en")) {
    throw new Error(
      "maintained-languages: no English entry found in src/i18n/languages.ts",
    );
  }
  return codes;
}
