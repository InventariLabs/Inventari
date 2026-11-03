/**
 * The bundle budget gate reads a built `dist/` the way a browser does. These
 * specs lay out a miniature `dist/` — an entry, the chunks it imports, the
 * lazy App chunk, a language file — and judge the gate by its exit code and
 * the sentence it prints. Random bytes stand in for code that does not
 * compress, so a chunk's gzip size is about its byte size.
 */
import { randomBytes } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";

import { makeRepo, runGate } from "./gate-fixture.mjs";

const KIB = 1024;
/** A chunk of about `kib` KiB gzip, optionally importing sibling chunks. */
const chunk = (kib, imports = []) =>
  `${imports.map((f) => `import "./${f}";`).join("")}/*${randomBytes(kib * KIB).toString("base64")}*/\n`;

const PHONE_BUDGET = {
  screens: { receive: { chunks: ["Receive"], budget: { jsKiB: 400 } } },
};

const dist = (extra = {}) => ({
  "frontend/dist/index.html":
    '<html><head><script type="module" src="/assets/index-aaa.js"></script>' +
    '<link rel="modulepreload" href="/assets/shared-bbb.js">' +
    '<link rel="stylesheet" href="/assets/index-aaa.css"></head></html>',
  "frontend/dist/assets/index-aaa.js": chunk(10, ["shared-bbb.js"]),
  "frontend/dist/assets/shared-bbb.js": chunk(10),
  "frontend/dist/assets/index-aaa.css": "body{}",
  "frontend/dist/assets/App-ccc.js": chunk(20),
  "frontend/dist/assets/i18n-pl-ddd.js": chunk(5),
  "frontend/dist/assets/i18n-en-eee.js": chunk(2),
  "frontend/dist/assets/Receive-fff.js": chunk(10),
  "frontend/scripts/phone-budget.json": PHONE_BUDGET,
  ...extra,
});

let repo;
afterEach(() => repo?.cleanup());

const run = (files) => {
  repo = makeRepo();
  repo.write(files);
  return runGate(repo, "check-bundle-budget.mjs");
};

describe("check-bundle-budget", () => {
  it("passes a small build and reports initial, first paint and the heaviest language", () => {
    const { status, stdout } = run(dist());

    expect(status).toBe(0);
    expect(stdout).toMatch(/ok\s+initial\s+\d+\.\d KiB gz\s+\(budget 245\)/);
    expect(stdout).toMatch(
      /ok\s+appFirstPaint\s+\d+\.\d KiB gz\s+\(budget 390\)/,
    );
    expect(stdout).toContain("heaviest language: i18n-pl-ddd.js");
    expect(stdout).toMatch(/ok\s+receive/);
  });

  it("counts the entry's static closure: a chunk the entry imports is paid for", () => {
    const withShared = run(dist());
    const initialWith = Number(
      /initial\s+(\d+\.\d)/.exec(withShared.stdout)[1],
    );
    repo.cleanup();

    const withoutShared = run(
      dist({
        "frontend/dist/index.html":
          '<script type="module" src="/assets/index-aaa.js"></script>',
        "frontend/dist/assets/index-aaa.js": chunk(10),
      }),
    );
    const initialWithout = Number(
      /initial\s+(\d+\.\d)/.exec(withoutShared.stdout)[1],
    );

    expect(initialWith).toBeGreaterThan(initialWithout + 8);
  });

  it("charges a screen only for what first paint has not already paid", () => {
    const { stdout } = run(
      dist({
        "frontend/dist/assets/Receive-fff.js": chunk(10, ["shared-bbb.js"]),
      }),
    );
    const kib = (label) =>
      Number(new RegExp(`${label}\\s+(\\d+\\.\\d)`).exec(stdout)[1]);

    // shared-bbb.js is 10 KiB and is already in `initial`; the screen's own
    // chunk adds about 10 more, not 20.
    expect(kib("receive") - kib("appFirstPaint")).toBeLessThan(15);
    expect(kib("receive") - kib("appFirstPaint")).toBeGreaterThan(8);
  });

  it("fails when the startup path outgrows its budget, and says to find the import", () => {
    const { status, stderr } = run(
      dist({ "frontend/dist/assets/shared-bbb.js": chunk(250) }),
    );

    expect(status).toBe(1);
    expect(stderr).toMatch(/initial \d+\.\d > 245 KiB gz/);
    expect(stderr).toContain("find the import that walked in");
  });

  it("fails when the signed-in first paint outgrows its budget", () => {
    const { status, stderr } = run(
      dist({ "frontend/dist/assets/App-ccc.js": chunk(400) }),
    );

    expect(status).toBe(1);
    expect(stderr).toMatch(/appFirstPaint \d+\.\d > 390 KiB gz/);
  });

  it("fails when a phone screen's own chunks push it over its budget", () => {
    const { status, stderr } = run(
      dist({
        "frontend/scripts/phone-budget.json": {
          screens: { receive: { chunks: ["Receive"], budget: { jsKiB: 20 } } },
        },
      }),
    );

    expect(status).toBe(1);
    expect(stderr).toContain("phone budget");
    expect(stderr).toMatch(/receive \d+\.\d > 20 KiB gz/);
  });

  it("fails when a screen names a chunk the build does not have", () => {
    const { status, stderr } = run(
      dist({
        "frontend/scripts/phone-budget.json": {
          screens: { ghost: { chunks: ["Nowhere"], budget: { jsKiB: 999 } } },
        },
      }),
    );

    expect(status).toBe(1);
    expect(stderr).toContain("ghost: no Nowhere-*.js chunk in dist/assets");
  });

  it("exits 2, not green, when there is no build to measure", () => {
    const { status, stderr } = run({
      "frontend/scripts/phone-budget.json": PHONE_BUDGET,
    });

    expect(status).toBe(2);
    expect(stderr).toContain("index.html not found — build first");
  });

  it("exits 2 when the build has no App chunk to measure", () => {
    const files = dist();
    delete files["frontend/dist/assets/App-ccc.js"];

    const { status, stderr } = run(files);

    expect(status).toBe(2);
    expect(stderr).toContain("no App-*.js chunk in dist/assets");
  });
});
