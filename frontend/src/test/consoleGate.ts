/**
 * A green run that printed React warnings is not a green run.
 *
 * The suite used to pass while React filled stderr with "each child in a list
 * should have a unique key" or "validateDOMNesting" — noise that buried the
 * warnings which were real defects, and taught everyone to skim past them.
 * This gate makes a `console.error` (or a React `console.warn`) fail the test
 * that caused it, with the message inside the failure where it cannot be
 * skimmed.
 *
 * The sources that are already there are not fixed in one change: they sit in
 * `console-baseline.json` as (test file, message signature, occurrence count).
 * The baseline is a ceiling, not an exemption — one more occurrence than it
 * recorded, or a signature that is not in it, fails the test. It is refreshed
 * only as a whole, from a full run:
 *
 *     npm run test:console-baseline
 *
 * the same rule as the other baselines in this tree: written from what a run
 * observed, never edited by hand.
 */
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";

/** One message that is not accounted for by the baseline. */
export interface ConsoleEntry {
  kind: "error" | "warn";
  signature: string;
  count: number;
}

/**
 * test file (repo-relative) → message signatures that file is allowed to print.
 *
 * A set, not a count: the suite's warnings are timing-dependent (the act
 * warning alone has been observed at 299 and at 301 in two full runs of the
 * same tree), so a count would make the gate flaky. A new *signature*, or a
 * signature under a new file, is what fails.
 */
export type ConsoleBaseline = Record<string, string[]>;

export type GateVerdict =
  /** Not gated at all — the caller prints it exactly as before. */
  | "pass"
  /** Recorded within the baseline — absorbed, the caller stays quiet. */
  | "absorbed"
  /** Beyond the baseline — recorded, printed, and failed at the end of the test. */
  | "unexpected";

/**
 * The one message the environment itself produces: vitest executes a
 * prebundled react-dom in a separate module context, where
 * `IS_REACT_ACT_ENVIRONMENT` is not visible, so that copy reports a
 * false-positive act warning for third-party async updates. Filtering this
 * exact string keeps genuine "not wrapped in act(...)" warnings from app
 * components surfacing as failures.
 */
const ENVIRONMENT_WARNINGS = [
  "The current testing environment is not configured to support act(...)",
];

/**
 * The message a console call stands for.
 *
 * React logs format strings ("An update to %s inside a test..."), which are
 * stable across runs — the interpolated component name is not. Preferring
 * `args[0]` therefore keeps the signature reproducible without replacing
 * anything by hand. Only the first line is kept: jsdom's "Uncaught [...]"
 * messages arrive with a stack glued on, and a stack's line numbers move with
 * every unrelated edit — a baseline that churns on those is a baseline nobody
 * trusts.
 */
export function signatureOf(args: unknown[]): string {
  const first = args[0];
  if (typeof first === "string") return first.split("\n", 1)[0] ?? first;
  if (first instanceof Error) return `${first.name}: ${first.message}`;
  if (first === undefined) return "(no message)";
  if (typeof first === "object") {
    try {
      return (JSON.stringify(first) ?? String(first)).split("\n", 1)[0] ?? "";
    } catch {
      return String(first);
    }
  }
  return String(first);
}

export function isGated(kind: "error" | "warn", args: unknown[]): boolean {
  const first = args[0];
  if (
    typeof first === "string" &&
    ENVIRONMENT_WARNINGS.some((known) => first.includes(known))
  ) {
    return false;
  }
  if (kind === "error") return true;
  // React reports some warnings through console.warn, and marks them with its
  // own "Warning:" prefix. Everything else on console.warn is another
  // library's business and stays as it was.
  return typeof args[0] === "string" && args[0].startsWith("Warning:");
}

/** The baseline key of a test file: repo-relative, `src/...`. */
export function baselineKey(path: string): string {
  const normalized = path.split("\\").join("/");
  const at = normalized.lastIndexOf("/src/");
  if (at >= 0) return normalized.slice(at + 1);
  if (normalized.startsWith("src/")) return normalized;
  return relative(process.cwd(), normalized).split("\\").join("/");
}

export function failureMessage(entries: ConsoleEntry[]): string {
  const lines = entries.map((e) => `  console.${e.kind}: ${e.signature}`);
  return [
    `console gate: ${entries.length} unexpected message(s) — a green test that prints React warnings hides the real ones.`,
    ...lines,
    "",
    "Fix the cause. When the warning is deliberate, refresh the baseline from a full run:",
    "  npm run test:console-baseline",
  ].join("\n");
}

export function assertNoUnexpected(entries: ConsoleEntry[]): void {
  if (entries.length > 0) throw new Error(failureMessage(entries));
}

export interface ConsoleGate {
  /** Record one console call; the caller decides what to do with the verdict. */
  record(kind: "error" | "warn", args: unknown[]): GateVerdict;
  /** A test begins: subsequent messages are blamed on it. */
  beginTest(path: string): void;
  /** The unexpected messages this test produced. */
  endTest(): ConsoleEntry[];
  /** What was recorded before the first test of the file. */
  endFile(): ConsoleEntry[];
  /** Everything this process recorded, for a baseline refresh. */
  observations(): ConsoleBaseline;
}

export function createConsoleGate(baseline: ConsoleBaseline = {}): ConsoleGate {
  const seen: ConsoleBaseline = {};
  const counts = new Map<string, number>();
  let file = "";
  let inTest = false;
  let testUnexpected: ConsoleEntry[] = [];
  let moduleUnexpected: ConsoleEntry[] = [];

  function record(kind: "error" | "warn", args: unknown[]): GateVerdict {
    const first = args[0];
    if (
      typeof first === "string" &&
      ENVIRONMENT_WARNINGS.some((known) => first.includes(known))
    ) {
      // Absorbed: the run never printed it before, and still must not.
      return "absorbed";
    }
    if (!isGated(kind, args)) return "pass";
    const signature = signatureOf(args);
    const perFile = (seen[file] ??= []);
    if (!perFile.includes(signature)) perFile.push(signature);
    if (baseline[file]?.includes(signature)) return "absorbed";
    const occurrences = (counts.get(`${file}\u0000${signature}`) ?? 0) + 1;
    counts.set(`${file}\u0000${signature}`, occurrences);
    const entry = {
      kind,
      signature,
      count: occurrences,
    } satisfies ConsoleEntry;
    (inTest ? testUnexpected : moduleUnexpected).push(entry);
    return "unexpected";
  }

  return {
    record,
    beginTest(path: string) {
      file = baselineKey(path);
      inTest = true;
      testUnexpected = [];
    },
    endTest() {
      inTest = false;
      const entries = testUnexpected;
      testUnexpected = [];
      return entries;
    },
    endFile() {
      const entries = moduleUnexpected;
      moduleUnexpected = [];
      return entries;
    },
    observations() {
      const merged: ConsoleBaseline = {};
      for (const [key, signatures] of Object.entries(seen)) {
        // A message logged while a test module was imported belongs to that
        // file; the empty key is its bucket before the first test began.
        const target = key === "" ? file : key;
        const bucket = (merged[target] ??= []);
        for (const signature of signatures) {
          if (!bucket.includes(signature)) bucket.push(signature);
        }
      }
      return merged;
    },
  };
}

/** Where a write-mode run drops what each worker observed, before the merge. */
export const OBSERVATIONS_DIR = resolve(
  process.cwd(),
  "node_modules/.cache/console-gate",
);

/**
 * Drop one file's observations for the baseline refresh.
 *
 * The workers cannot write the baseline itself: they run in parallel and each
 * would overwrite the others. Each writes its own file here, and the global
 * setup merges them once every worker has exited.
 */
export function writeObservations(observations: ConsoleBaseline): void {
  if (Object.keys(observations).length === 0) return;
  mkdirSync(OBSERVATIONS_DIR, { recursive: true });
  for (const [fileKey, entries] of Object.entries(observations)) {
    const name = createHash("sha1").update(fileKey).digest("hex");
    writeFileSync(
      resolve(OBSERVATIONS_DIR, `${name}.json`),
      `${JSON.stringify({ file: fileKey, entries }, null, 2)}\n`,
    );
  }
}
