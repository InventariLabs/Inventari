/** The baseline refresh, once per run.
 *
 * Workers drop what they observed into `node_modules/.cache/console-gate`
 * (see `consoleGate.ts`); this merges those files after every worker has
 * exited — the only moment when the whole run's record exists in one place.
 * A normal run touches nothing: the baseline changes only through
 *
 *     npm run test:console-baseline
 *
 * and always as a whole, so a scoped run cannot quietly shrink it.
 */
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";

import { OBSERVATIONS_DIR, type ConsoleBaseline } from "./consoleGate";

const BASELINE_PATH = resolve(process.cwd(), "src/test/console-baseline.json");

export default function consoleGateGlobalSetup() {
  rmSync(OBSERVATIONS_DIR, { recursive: true, force: true });

  return () => {
    if (!process.env.CONSOLE_BASELINE_WRITE) {
      rmSync(OBSERVATIONS_DIR, { recursive: true, force: true });
      return;
    }

    const entries: ConsoleBaseline = {};
    let signatures = 0;
    if (existsSync(OBSERVATIONS_DIR)) {
      for (const name of readdirSync(OBSERVATIONS_DIR)) {
        const parsed = JSON.parse(
          readFileSync(resolve(OBSERVATIONS_DIR, name), "utf8"),
        ) as { file: string; entries: string[] };
        if (!parsed.file) continue;
        const bucket = (entries[parsed.file] ??= []);
        for (const signature of parsed.entries) {
          if (!bucket.includes(signature)) bucket.push(signature);
          signatures += 1;
        }
      }
    }

    const sorted = Object.fromEntries(
      Object.entries(entries)
        .sort()
        .map(([file, names]) => [file, [...names].sort()]),
    );
    mkdirSync(resolve(process.cwd(), "src/test"), { recursive: true });
    writeFileSync(
      BASELINE_PATH,
      `${JSON.stringify({ generated: new Date().toISOString(), entries: sorted }, null, 2)}\n`,
    );
    rmSync(OBSERVATIONS_DIR, { recursive: true, force: true });
    console.log(
      `console baseline written: ${Object.keys(sorted).length} file(s), ${signatures} signature(s) → src/test/console-baseline.json`,
    );
  };
}
