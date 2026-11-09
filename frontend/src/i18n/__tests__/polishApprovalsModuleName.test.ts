/**
 * The approvals module is "Zatwierdzenia" in Polish (docs/MODULE_NAMES.md),
 * never "Akceptacje". Its launcher tile, store card and settings tab say so;
 * a sentence that names the module as a module ("Moduł Akceptacje jest
 * wyłączony", "przy wyłączonym module Akceptacji") has to say the same, or
 * the reader hunts the launcher for a module that does not exist.
 *
 * Only the module's name is asserted. "akceptacja" as the act of accepting
 * ("Akceptacja zgłoszeń", "próg akceptacji") is ordinary Polish and stays.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

/** "moduł Akceptacje", "modułu Akceptacji", "w module Akceptacje"… */
const MODULE_AS_AKCEPTACJE = /modu\p{L}*\s+Akceptacj/iu;

function polishCatalogueFiles(): string[] {
  const files: string[] = [];
  const core = join(SRC, "i18n", "locales", "pl");
  for (const entry of readdirSync(core)) {
    if (entry.endsWith(".json")) files.push(join(core, entry));
  }
  const modulesDir = join(SRC, "modules");
  for (const moduleName of readdirSync(modulesDir)) {
    const path = join(modulesDir, moduleName, "i18n", "pl.json");
    if (existsSync(path)) files.push(path);
  }
  return files;
}

function namesModuleAkceptacje(
  node: unknown,
  path: string[] = [],
): Array<{ key: string; value: string }> {
  if (typeof node === "string") {
    return MODULE_AS_AKCEPTACJE.test(node)
      ? [{ key: path.join("."), value: node }]
      : [];
  }
  if (Array.isArray(node)) {
    return node.flatMap((entry, i) =>
      namesModuleAkceptacje(entry, [...path, String(i)]),
    );
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([key, value]) =>
      namesModuleAkceptacje(value, [...path, key]),
    );
  }
  return [];
}

describe("no Polish string calls the approvals module Akceptacje", () => {
  it("says Zatwierdzenia in every catalogue", () => {
    const hits = polishCatalogueFiles().flatMap((file) =>
      namesModuleAkceptacje(JSON.parse(readFileSync(file, "utf8"))).map(
        (hit) => `${file.slice(SRC.length + 1)} :: ${hit.key} :: ${hit.value}`,
      ),
    );
    expect(hits).toEqual([]);
  });

  it("would catch the module under its retired name", () => {
    expect(
      namesModuleAkceptacje({ a: "Moduł Akceptacje jest wyłączony" }),
    ).toHaveLength(1);
    expect(
      namesModuleAkceptacje({ a: "Przy wyłączonym module Akceptacji" }),
    ).toHaveLength(1);
  });

  it("leaves the act of accepting alone", () => {
    expect(
      namesModuleAkceptacje({
        a: "Akceptacja zgłoszeń",
        b: "Moduł Zatwierdzenia jest wyłączony, wyczyść próg akceptacji",
      }),
    ).toEqual([]);
  });
});
