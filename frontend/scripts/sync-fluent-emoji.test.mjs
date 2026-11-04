/**
 * The emoji sync script keeps the self-hosted SVGs and the manifest in step
 * with the keyword map. The network is replaced by a `fetch` stub preloaded
 * into the child process, so what is pinned is which emoji it decides to
 * download, what it writes, and when it fails — never GitHub.
 */
import { afterEach, describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { makeRepo, runGate } from "./gate-fixture.mjs";

const KEYWORD_MAP = "frontend/src/lib/categoryEmoji.ts";
const MANIFEST = "frontend/src/lib/fluent-emoji-manifest.ts";
const EGG = "frontend/public/emoji/egg_color.svg";
const MEAT = "frontend/public/emoji/cut_of_meat_color.svg";

/** Two mapped emoji, a duplicate, a multi-character keyword and plain text. */
const KEYWORDS = `export const KEYWORD_EMOJI_MAP = { egg: '🥚', "steak": "🥩", again: '🥚', "ice cream": "ab" };\n`;

let repo;
afterEach(() => repo?.cleanup());

/** A preload that answers every fetch with `status`, and logs the URLs asked for. */
const stubFetch = (status) =>
  `import { appendFileSync } from "node:fs";\n` +
  `globalThis.fetch = async (url) => {\n` +
  `  appendFileSync("fetched.log", url + "\\n");\n` +
  `  return { ok: ${status === 200}, status: ${status}, text: async () => "<svg/>" };\n` +
  `};\n`;

const run = ({ files = {}, args = [], status = 200 } = {}) => {
  repo = makeRepo();
  repo.write({
    [KEYWORD_MAP]: KEYWORDS,
    "frontend/stub-fetch.mjs": stubFetch(status),
    ...files,
  });
  return runGate(repo, "sync-fluent-emoji.mjs", {
    args,
    nodeArgs: [
      "--import",
      pathToFileURL(join(repo.frontend, "stub-fetch.mjs")).href,
    ],
  });
};

const fetched = () => {
  const log = join(repo.frontend, "fetched.log");
  return existsSync(log) ? readFileSync(log, "utf8").trim().split("\n") : [];
};

describe("sync-fluent-emoji --check", () => {
  it("passes when every emoji in the keyword map has its SVG", () => {
    const { status, stdout } = run({
      args: ["--check"],
      files: { [EGG]: "<svg/>", [MEAT]: "<svg/>" },
    });

    expect(status).toBe(0);
    expect(stdout).toContain("Found 2 distinct emoji in keyword map");
    expect(stdout).toContain("All SVGs present. OK.");
  });

  it("fails and names the SVG that is missing", () => {
    const { status, stderr } = run({
      args: ["--check"],
      files: { [EGG]: "<svg/>" },
    });

    expect(status).toBe(1);
    expect(stderr).toContain("MISSING: 🥩");
    expect(stderr).toContain("1 emoji SVG(s) missing");
    expect(stderr).toContain("npm run sync:emoji");
  });

  it("fails on an emoji with no CLDR mapping, which no download could fix", () => {
    const { status, stderr } = run({
      args: ["--check"],
      files: {
        [KEYWORD_MAP]: `export const M = { dragon: '🐲' };\n`,
      },
    });

    expect(status).toBe(1);
    expect(stderr).toContain("MISSING MAPPING: 🐲 — no CLDR entry");
  });

  it("never touches the network or the disk", () => {
    run({ args: ["--check"], files: { [EGG]: "<svg/>" } });

    expect(fetched()).toEqual([]);
    expect(existsSync(join(repo.root, MANIFEST))).toBe(false);
  });

  it("fails when the keyword map itself is gone", () => {
    repo = makeRepo();
    const { status, stderr } = runGate(repo, "sync-fluent-emoji.mjs", {
      args: ["--check"],
    });

    expect(status).toBe(1);
    expect(stderr).toContain("Cannot find");
  });
});

describe("sync-fluent-emoji --sync", () => {
  it("downloads only the SVGs that are missing, and writes the manifest", () => {
    const { status, stdout } = run({ files: { [EGG]: "<svg id=egg/>" } });

    expect(status).toBe(0);
    expect(stdout).toContain("downloaded=1 skipped=1 failed=0");
    expect(fetched()).toEqual([
      "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/Cut%20of%20meat/Color/cut_of_meat_color.svg",
    ]);
    expect(readFileSync(join(repo.root, EGG), "utf8")).toBe("<svg id=egg/>");
    expect(readFileSync(join(repo.root, MEAT), "utf8")).toBe("<svg/>");
  });

  it("writes a manifest that maps each emoji once, to its self-hosted file", () => {
    run({});
    const manifest = readFileSync(join(repo.root, MANIFEST), "utf8");

    expect(manifest).toContain("AUTO-GENERATED");
    expect(manifest).toContain('"🥚": "/emoji/egg_color.svg",');
    expect(manifest).toContain('"🥩": "/emoji/cut_of_meat_color.svg",');
    expect(manifest.match(/🥚/g)).toHaveLength(1);
  });

  it("exits 1 and names the emoji when the download fails", () => {
    const { status, stderr } = run({ status: 404 });

    expect(status).toBe(1);
    expect(stderr).toContain("FAILED: 🥚 (egg_color.svg) — HTTP 404");
    expect(existsSync(join(repo.root, EGG))).toBe(false);
  });

  it("exits 1 for an emoji with no CLDR mapping, and still writes the manifest for the rest", () => {
    const { status, stderr } = run({
      files: {
        [KEYWORD_MAP]: `export const M = { egg: '🥚', dragon: '🐲' };\n`,
        [EGG]: "<svg/>",
      },
    });

    expect(status).toBe(1);
    expect(stderr).toContain("FAILED: 🐲 — no CLDR mapping");
    const manifest = readFileSync(join(repo.root, MANIFEST), "utf8");
    expect(manifest).toContain("🥚");
    expect(manifest).not.toContain("🐲");
  });
});
