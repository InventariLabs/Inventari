/**
 * A scratch `frontend/` tree for running a gate script the way `npm run`
 * does — as a process, from its own location.
 *
 * The gate entry points work out their root from `import.meta.url` and run
 * their whole body at import, so a spec cannot import them and point them at a
 * fixture. It can copy the script into `<tmp>/frontend/scripts/` and run it
 * there: the root becomes the scratch tree, and what is asserted is what the
 * gate does in CI — its exit code and what it prints.
 */
import { spawnSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const SCRIPTS = import.meta.dirname;

/** A fresh scratch repo: `<root>/frontend/` (where gates run) beside `<root>/backend/`. */
export function makeRepo() {
  const root = mkdtempSync(join(tmpdir(), "gate-"));
  mkdirSync(join(root, "frontend", "scripts"), { recursive: true });
  return {
    root,
    frontend: join(root, "frontend"),
    /** Write files, keyed by path relative to the repo root; strings or objects (as JSON). */
    write(files) {
      for (const [rel, content] of Object.entries(files)) {
        const target = join(root, rel);
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(
          target,
          typeof content === "string"
            ? content
            : `${JSON.stringify(content, null, 2)}\n`,
        );
      }
    },
    cleanup() {
      rmSync(root, { recursive: true, force: true });
    },
  };
}

/**
 * Copy `script` (and the sibling files it imports) next to the fixture and run it.
 *
 * `siblings` are files or directories under `scripts/`; test files are left out.
 * `patch` maps a path under `scripts/` to a function from its copied text to the
 * text the gate should run with — for a spec that needs a gate's input to differ
 * from what the repo ships (a detector that is report-only, say).
 */
export function runGate(
  repo,
  script,
  { args = [], siblings = [], nodeArgs = [], patch = {} } = {},
) {
  for (const name of [script, ...siblings]) {
    cpSync(join(SCRIPTS, name), join(repo.frontend, "scripts", name), {
      recursive: true,
      filter: (source) => !source.endsWith(".test.mjs"),
    });
  }
  for (const [name, edit] of Object.entries(patch)) {
    const target = join(repo.frontend, "scripts", name);
    writeFileSync(target, edit(readFileSync(target, "utf8")));
  }
  const result = spawnSync(
    process.execPath,
    [...nodeArgs, join(repo.frontend, "scripts", script), ...args],
    {
      cwd: repo.frontend,
      encoding: "utf8",
    },
  );
  return {
    status: result.status,
    stdout: result.stdout,
    stderr: result.stderr,
  };
}
