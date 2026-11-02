/**
 * The core key answers to `locations`, and the old one does not come back.
 *
 * It was called `storages` until the key was changed before the first
 * release. A role stores the permission keys by name, so a screen still
 * asking `locations:write` would hide every button from an account the API
 * would happily let through — or offer buttons the API refuses. The
 * backend's half of this gate is
 * `backend/tests/unit/test_the_storages_key_is_called_locations.py`; this
 * is the half that reads the frontend tree.
 *
 * What keeps its name is what is internal: the query keys and the
 * `storagesApi` client. The REST paths, the `/inventory/locations` routes
 * and the `locations` i18n namespace moved after the key, together with the
 * request and response fields.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { FALLBACK_MODULES } from "@/contexts/ModulesContext";

const SRC = join(process.cwd(), "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    // This file names the old key on purpose, to look for it.
    if (entry.name === "theStoragesKeyIsCalledLocations.test.ts") return [];
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

describe("the storages key is called locations", () => {
  it("no source asks for a permission key under the old module name", () => {
    const found: string[] = [];
    const patterns = [
      /\bstorages:(?:read|write|manage|delete)\b/,
      /\buseCan(?:Write|Manage)\("storages"\)/,
      /\bmodule="storages"/,
    ];
    for (const path of sourceFiles(SRC)) {
      const text = readFileSync(path, "utf8");
      for (const pattern of patterns) {
        const match = pattern.exec(text);
        if (match) {
          const line = text.slice(0, match.index).split("\n").length;
          found.push(`${relative(process.cwd(), path)}:${line}: ${match[0]}`);
        }
      }
    }

    expect(found).toEqual([]);
  });

  it("the fallback module list names locations", () => {
    // The list shown before `/modules/my` answers mirrors a default
    // install; a stale name would hide the locations screens while loading.
    expect(FALLBACK_MODULES).toContain("locations");
    expect(FALLBACK_MODULES).not.toContain("storages");
  });
});
