import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

/**
 * A session sheet records work as it goes, but where that work lands
 * differs: a recipe scan moves stock the moment it is read, while a WMS
 * scan writes onto the document's lines and the stock moves when the
 * session completes. Either way, closing the sheet (×, Escape, the
 * backdrop) is not a decision about that work, so it must not cancel the
 * session: what was picked stays picked, and the next open hands the
 * caller their own active session back (the backend's start resumes it).
 * The
 * alternative was measured in the wild: "×" put the rice back on the shelf
 * a second after "Picked 200 g" said it left, with no question and no
 * sentence on any screen. The named Cancel button is the one path that
 * puts things back, and it announces what it did.
 *
 * This gate keeps that class from coming back: no session component's
 * close handler may call a session cancel. A sheet that wants "close asks,
 * then cancels on confirmation" is a reader decision and legitimate — add
 * it to ALLOWED_ASKING with the reason a reviewer can judge.
 *
 * The scan is a heuristic, and says so: it reads handlers named
 * `handleClose`, the name every session sheet in the tree uses, so a
 * future sheet naming its close handler differently slips past it. The
 * KNOWN_SHEETS check below is the answer — the sheets the gate is known to
 * cover are named, so one that stops matching fails instead of going
 * quiet.
 */

/** Calls that end a session server-side. */
const CANCEL_CALL = /cancelSession\s*\(|cancelPicking\s*\(|\/cancel\b/;
/** A close handler, in the shape prettier writes for these components. */
const CLOSE_HANDLER =
  /const handleClose = (?:\([^)]*\))?\s*=>\s*\{([\s\S]*?)\n {2}\};/;

/**
 * The session sheets this gate covers. Each must still define a
 * `handleClose` the scan can read — renaming it would leave the gate
 * guarding nothing while reading as covered.
 */
const KNOWN_SHEETS = [
  "src/modules/recipes/components/PickingView.tsx",
  "src/modules/warehouse/components/picking/WmsPickingView.tsx",
  "src/modules/warehouse/components/receiving/WmsReceivingView.tsx",
];

/**
 * Sheets whose close handler cancels on purpose, with the reason. An entry
 * here is a reviewed decision, not an exemption from one.
 */
const ALLOWED_ASKING: Record<string, string> = {};

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (full.endsWith(".tsx") && !full.endsWith(".test.tsx")) {
      out.push(full);
    }
  }
  return out;
}

function closeHandlerBodies(text: string): string[] {
  // The regex is global-less on purpose: repeated exec over one text with
  // lastIndex state is a trap; matchAll keeps each pass independent.
  return [...text.matchAll(new RegExp(CLOSE_HANDLER.source, "g"))].map(
    (m) => m[1],
  );
}

describe("closing a session sheet never cancels the session", () => {
  it("no close handler in the module tree calls a session cancel", () => {
    const offending: string[] = [];
    for (const file of walk(join(process.cwd(), "src/modules"))) {
      const rel = relative(process.cwd(), file).split(sep).join("/");
      if (ALLOWED_ASKING[rel]) continue;
      const bodies = closeHandlerBodies(readFileSync(file, "utf8"));
      if (bodies.some((body) => CANCEL_CALL.test(body))) {
        offending.push(rel);
      }
    }

    expect(
      offending,
      "Close handlers found that cancel a session server-side. Closing a " +
        "sheet (×, Escape, backdrop) must leave it resumable — the next open " +
        "hands the caller their own session back. Cancelling is the named " +
        "Cancel button's job (session-close-gate.test.ts); wire the ask " +
        "there, or record the reviewed decision in ALLOWED_ASKING.",
    ).toEqual([]);
  });

  it("the sheets the gate is known to cover still match its scan", () => {
    // A renamed close handler or a moved sheet would leave ALLOWED_ASKING
    // and this list guarding nothing — each named sheet must still expose a
    // readable handleClose.
    for (const rel of KNOWN_SHEETS) {
      const text = readFileSync(join(process.cwd(), rel), "utf8");
      expect(closeHandlerBodies(text), rel).not.toHaveLength(0);
    }
  });

  it("the survey's entries all point at sheets the scan still sees", () => {
    // A stale ALLOWED_ASKING entry (sheet deleted, handler renamed) reads
    // as a standing decision while deciding nothing.
    for (const rel of Object.keys(ALLOWED_ASKING)) {
      const text = readFileSync(join(process.cwd(), rel), "utf8");
      expect(
        closeHandlerBodies(text).some((body) => CANCEL_CALL.test(body)),
        rel,
      ).toBe(true);
    }
  });
});
