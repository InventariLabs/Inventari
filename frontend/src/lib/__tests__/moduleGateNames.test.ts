import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A module gate names a module, and the name has to be one the backend can
 * actually hand back. `GET /modules/my` runs every name through a sanitiser
 * that keeps only always-on modules, registered backend modules and the
 * virtual toggleables — anything else is dropped on the way out. A gate on a
 * name outside that set is a door that never opens: the code behind it ships,
 * renders nowhere, and nothing says so.
 *
 * Two surfaces were sitting behind such a door when this gate was written.
 * `announcements` hid the notification bell and the announcement banner from
 * every organisation while notifications piled up unread; `grocy_importer`
 * hid an import preset behind a toast telling the user to enable a module
 * that does not exist in this product at all.
 *
 * The names are read from the backend's own source: the frontend container
 * mounts ./backend/app read-only precisely so naming gates like this one can
 * see it (see docker-compose.yml).
 */

const SRC = join(process.cwd(), "src");
const BACKEND = resolve(process.cwd(), "..", "backend", "app");
const MODULE_SAFETY = join(BACKEND, "core", "module_safety.py");
const MODULES_API = join(BACKEND, "api", "modules.py");
const BACKEND_MODULES = join(BACKEND, "modules");

function parsePythonStringCollection(file: string, name: string): string[] {
  const source = readFileSync(file, "utf8");
  const match = source.match(
    new RegExp(`${name}\\s*=\\s*(?:frozenset\\()?[{\\[]([\\s\\S]*?)[}\\]]`),
  );
  if (!match) throw new Error(`${name} not found in ${file}`);
  return Array.from(match[1].matchAll(/'([^']+)'/g)).map((m) => m[1]);
}

/** Every name `GET /modules/my` is able to return. */
function resolvableModuleNames(): Set<string> {
  const registered = readdirSync(BACKEND_MODULES, { withFileTypes: true })
    .filter(
      (entry) =>
        entry.isDirectory() &&
        existsSync(join(BACKEND_MODULES, entry.name, "manifest.json")),
    )
    .map((entry) => entry.name);

  return new Set([
    ...parsePythonStringCollection(MODULE_SAFETY, "ALWAYS_ON_MODULES"),
    ...parsePythonStringCollection(MODULE_SAFETY, "VIRTUAL_TOGGLEABLE_MODULES"),
    ...parsePythonStringCollection(MODULES_API, "_ALWAYS_ON_FRONTEND_ONLY"),
    ...registered,
  ]);
}

const GATE_PATTERNS = [
  /isModuleEnabled\(\s*"([a-z_]+)"\s*\)/g,
  /enabledModules\.includes\(\s*"([a-z_]+)"\s*\)/g,
];

/** A line that only documents the pattern is not a gate. */
function isComment(line: string): boolean {
  const trimmed = line.trim();
  return (
    trimmed.startsWith("//") ||
    trimmed.startsWith("*") ||
    trimmed.startsWith("/*")
  );
}

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__") continue;
      out.push(...walk(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue;
    out.push(full);
  }
  return out;
}

interface Gate {
  module: string;
  where: string;
}

function collectGates(): Gate[] {
  const gates: Gate[] = [];
  for (const file of walk(SRC)) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, index) => {
      if (isComment(line)) return;
      for (const pattern of GATE_PATTERNS) {
        for (const match of line.matchAll(pattern)) {
          gates.push({
            module: match[1],
            where: `${relative(process.cwd(), file)}:${index + 1}`,
          });
        }
      }
    });
  }
  return gates;
}

describe("module gates name modules the API can return", () => {
  const resolvable = resolvableModuleNames();
  const gates = collectGates();

  it("reads a real module list from the backend (the gate is not vacuous)", () => {
    expect(resolvable.has("announcements")).toBe(true);
    expect(resolvable.has("approvals")).toBe(true);
    expect(resolvable.size).toBeGreaterThan(10);
  });

  it("finds the gates it is meant to check (the scan is not vacuous)", () => {
    expect(gates.length).toBeGreaterThan(5);
    expect(gates.map((gate) => gate.module)).toContain("approvals");
  });

  it("has no gate on a name the sanitiser would drop", () => {
    const unreachable = gates.filter((gate) => !resolvable.has(gate.module));
    expect(
      unreachable.map((gate) => `${gate.where} gates on "${gate.module}"`),
    ).toEqual([]);
  });
});
