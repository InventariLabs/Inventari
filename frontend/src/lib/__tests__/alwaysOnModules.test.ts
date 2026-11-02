import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { FALLBACK_MODULES } from "@/contexts/ModulesContext";
import "@/modules/printing/module";

/**
 * Always-on parity guard.
 *
 * A module the backend forces on for every organisation is a promise the
 * frontend has to keep: `getRoutes()` registers routes only for enabled
 * modules, so a module missing from the shell's own view of "always on" ships
 * dead routes. `printing` was the case that made this a test — printed QR
 * stickers point at `/labels/scan/:code`, and no product profile listed the
 * module, so every fresh organisation resolved those stickers to a 404.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../..");
const MODULE_SAFETY = path.join(REPO_ROOT, "backend/app/core/module_safety.py");
const MODULES_API = path.join(REPO_ROOT, "backend/app/api/modules.py");

function parsePythonStringCollection(file: string, name: string): string[] {
  const source = fs.readFileSync(file, "utf8");
  const match = source.match(
    new RegExp(`${name}\\s*=\\s*[{\\[]([\\s\\S]*?)[}\\]]`),
  );
  if (!match) throw new Error(`${name} not found in ${file}`);
  return Array.from(match[1].matchAll(/'([^']+)'/g)).map((m) => m[1]);
}

const backendAlwaysOn = [
  ...parsePythonStringCollection(MODULE_SAFETY, "ALWAYS_ON_MODULES"),
  ...parsePythonStringCollection(MODULES_API, "_ALWAYS_ON_FRONTEND_ONLY"),
];

describe("modules the backend forces on", () => {
  it("are all covered by the shell's fallback list", () => {
    const missing = backendAlwaysOn.filter(
      (name) => !FALLBACK_MODULES.includes(name),
    );
    expect(missing).toEqual([]);
  });

  it("include the module owning the printed-label scan route", () => {
    const paths = moduleRegistry.getRoutes(backendAlwaysOn).map((r) => r.path);
    expect(paths).toContain("/labels/scan/:code");
  });
});
