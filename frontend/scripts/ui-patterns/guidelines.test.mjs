import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BLOCKING, DETECTORS } from "./index.mjs";

// Resolved from the working directory: under vitest `import.meta.url` is not a file URL.
const frontend = process.cwd();
const guidelines = readFileSync(`${frontend}/UI_GUIDELINES.md`, "utf8");

/**
 * Two kinds of error the guidelines collected more than once, each held here.
 *
 * A component the text names that the code does not have — the layer table
 * named a `StorageEditSheet` and a `StorageReorgModal`, and a reader looking
 * for either found nothing. Every multi-word PascalCase name in the guide must
 * occur somewhere in `src/`, `scripts/` or the ESLint config. The few names
 * below are placeholders of a code sample, never meant to exist.
 */
const SAMPLE_PLACEHOLDERS = new Set([
  "HistoryPanel",
  "InfoPanel",
  "MyModulePage",
  "TabType",
]);

const PASCAL = /\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b/g;

function namesInTheCode() {
  const known = new Set();
  const read = (file) => {
    for (const name of readFileSync(file, "utf8").match(PASCAL) ?? []) {
      known.add(name);
    }
  };
  for (const dir of ["src", "scripts"]) {
    for (const entry of readdirSync(`${frontend}/${dir}`, {
      recursive: true,
      withFileTypes: true,
    })) {
      // This file quotes the missing names in its own comments.
      if (entry.name === "guidelines.test.mjs") continue;
      if (entry.isFile() && /\.(tsx?|mjs|js)$/.test(entry.name)) {
        read(`${entry.parentPath}/${entry.name}`);
      }
    }
  }
  read(`${frontend}/eslint.config.js`);
  return known;
}

// A paragraph, or one item of a list: list items are not separated by blank lines.
function paragraphs(text) {
  return text.split(/\n\s*\n|\n(?=\s*[-*] )/);
}

describe("UI_GUIDELINES.md against the code", () => {
  it("names only components and types the frontend has", () => {
    const known = namesInTheCode();
    const named = new Set(guidelines.match(PASCAL) ?? []);
    const missing = [...named].filter(
      (name) => !known.has(name) && !SAMPLE_PLACEHOLDERS.has(name),
    );
    expect(missing).toEqual([]);
  });

  /**
   * A detector cited by the gate that does not run it — `scan:ui` was said to
   * "enforce" `hover-only-reveal` and to "report rather than block"
   * `destructive-as-neutral`, while both sit in BLOCKING and only `lint:ui`
   * fails on them; `scan:ui` never fails anything. A paragraph that names a
   * detector names the command that acts on it: `lint:ui` for a blocking one,
   * and not `lint:ui` for one that only reports.
   */
  it("cites each detector with the command that acts on it", () => {
    const wrong = [];
    for (const paragraph of paragraphs(guidelines)) {
      for (const { name } of DETECTORS) {
        if (!paragraph.includes(`\`${name}\``)) continue;
        const saysLint = paragraph.includes("lint:ui");
        if (BLOCKING.has(name) && !saysLint) {
          wrong.push(`${name} blocks, but its paragraph does not name lint:ui`);
        }
        if (!BLOCKING.has(name) && saysLint) {
          wrong.push(`${name} only reports, but its paragraph names lint:ui`);
        }
        if (BLOCKING.has(name) && /reports rather than blocks/.test(paragraph)) {
          wrong.push(`${name} blocks, but its paragraph says it only reports`);
        }
      }
    }
    expect(wrong).toEqual([]);
  });
});
