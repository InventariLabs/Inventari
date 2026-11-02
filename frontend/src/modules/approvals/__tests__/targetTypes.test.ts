import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { TFunction } from "i18next";
import { AVAILABLE_TARGET_TYPES, targetTypeLabel } from "../targetTypes";

/**
 * A workflow can only fire for a target type some module actually requests
 * approval for. That used to be asserted as a hand-written list of exceptions,
 * with a comment claiming purchase_orders and equipment "never call
 * approvals_api" — both untrue, and the list outlived the claim: the editor
 * offered one target type while two more had live integrations, so a purchase
 * order could never be routed through approvals from the UI.
 *
 * So the rule is read from the backend instead of restated here: whichever
 * target types the modules pass to `approvals_api.request_approval` are the
 * ones the editor offers. A new integration lands, this test fails, and the
 * list follows the code rather than a comment.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../../..");
const MODULES_ROOT = path.join(REPO_ROOT, "backend/app/modules");

/**
 * The approvals module is scanned too: it gates the warehouse's documents
 * itself and raises their requests. Its engine passes the target type on as
 * a variable, which the scan does not count.
 */
function pythonSources(dir: string): string[] {
  const found: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "__pycache__" || entry.name === "tests") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...pythonSources(full));
    } else if (entry.name.endsWith(".py")) {
      found.push(full);
    }
  }
  return found;
}

/**
 * Third positional argument of `approvals_api.request_approval(db, org, ...)`.
 * It is either a literal ('document') or a module-level constant
 * (`_TARGET_TYPE = 'equipment_checkout'`), so both are resolved.
 */
function requestedTargetTypes(source: string): string[] {
  const constants = new Map<string, string>();
  for (const [, name, value] of source.matchAll(
    /^(_?[A-Z_]+)\s*=\s*'([^']+)'/gm,
  )) {
    constants.set(name, value);
  }

  const types: string[] = [];
  for (const match of source.matchAll(
    /request_approval\(([\s\S]{0,400}?)\)/g,
  )) {
    const args = match[1].split(",").map((arg) => arg.trim());
    const third = args[2];
    if (!third) continue;
    const literal = third.match(/^'([^']+)'$/);
    if (literal) {
      types.push(literal[1]);
    } else if (constants.has(third)) {
      types.push(constants.get(third) as string);
    }
  }
  return types;
}

const integratedTargetTypes = [
  ...new Set(
    pythonSources(MODULES_ROOT).flatMap((file) =>
      requestedTargetTypes(fs.readFileSync(file, "utf8")),
    ),
  ),
].sort();

describe("approval target types", () => {
  it("finds the integrations it is supposed to read", () => {
    // Guards the scan itself: a rename that silently matches nothing would
    // otherwise turn this whole file into a test that always passes.
    expect(integratedTargetTypes.length).toBeGreaterThan(0);
  });

  it("offers exactly the target types some module requests approval for", () => {
    expect([...AVAILABLE_TARGET_TYPES].sort()).toEqual(integratedTargetTypes);
  });

  it("has a label for every offered target type", () => {
    const t = ((key: string) => `T(${key})`) as unknown as TFunction;
    for (const targetType of AVAILABLE_TARGET_TYPES) {
      expect(targetTypeLabel(t, targetType)).toBe(
        `T(workflows.targetType_${targetType})`,
      );
    }
  });

  it("falls back to the raw value for unknown target types", () => {
    const t = ((key: string) => key) as unknown as TFunction;
    expect(targetTypeLabel(t, "something_new")).toBe("something_new");
  });
});
