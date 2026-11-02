/**
 * Anti-regression test: ``trackingFields.ts`` is deleted and no
 * module under ``modules/spaces`` may import from it. If you find yourself
 * needing vertical-specific fields on a storage screen, add them to
 * ``Category.field_definitions`` instead and merge at item-form render time.
 */

import { describe, it, expect } from "vitest";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SPACES_DIR = join(process.cwd(), "src/modules/spaces");

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (/\.(ts|tsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

describe("trackingFields.ts deletion", () => {
  it("the legacy trackingFields.ts file no longer exists", () => {
    const target = join(SPACES_DIR, "utils/trackingFields.ts");
    expect(existsSync(target)).toBe(false);
  });

  it("no module under src/modules/spaces imports from trackingFields", () => {
    const offenders: { file: string; line: number; text: string }[] = [];
    const importPattern = /from\s+["'][^"']*trackingFields[^"']*["']/g;

    for (const file of walk(SPACES_DIR)) {
      // Skip the anti-regression test file itself.
      if (file.endsWith("trackingFields.deleted.test.ts")) continue;
      const text = readFileSync(file, "utf8");
      const lines = text.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (importPattern.test(line)) {
          offenders.push({ file, line: i + 1, text: line.trim() });
        }
        importPattern.lastIndex = 0;
      }
    }

    expect(offenders).toEqual([]);
  });

  it("no module under src/modules/spaces calls getTrackingFields", () => {
    // The function name itself is a smoking gun — even if the import path
    // changes, the name ties back to the deleted module.
    const offenders: { file: string; line: number; text: string }[] = [];

    for (const file of walk(SPACES_DIR)) {
      const text = readFileSync(file, "utf8");
      const lines = text.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (/\bgetTrackingFields\s*\(/.test(line)) {
          offenders.push({ file, line: i + 1, text: line.trim() });
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
