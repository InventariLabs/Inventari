import { lineAt, withoutComments } from "./lib.mjs";

/** Names that hold a failure rather than a payload. */
const FAILURE = /^(e|err|error)$/i;

/** `err.message`, `error?.message`, `mutation.error.message`. */
const READ = /([A-Za-z_$][\w$]*)\s*\??\.\s*message\b/g;

/** `(error as Error).message` — the cast hides the name from `READ`. */
const CAST = /\(\s*([A-Za-z_$][\w$]*)\s+as\s[^)]*\)\s*\??\.\s*message\b/g;

/**
 * The escape hatch, and the price of using it.
 *
 * One read of `error.message` is right: the one that decides whether this
 * error is the kind whose message was written for the reader. `ReadableError`
 * carries a sentence its thrower composed in the reader's language, and
 * something has to unwrap it. That is a reason, not a baseline, so it lives at
 * the site in the shape the other rules here use and has to be a sentence:
 *
 *   // ui-pattern: error-message-as-copy — this error carries a sentence
 *   // written for the reader rather than for the log
 */
const EXCEPTION =
  /ui-pattern:\s*error-message-as-copy\s*[—-]?\s*([^*\n]+(?:\n\s*(?:\/\/|\*)\s*[^*\n]+)*)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 400;

export default {
  name: "error-message-as-copy",
  corpus: "scripts",
  says:
    "`err.message` on a failed request is axios' own sentence — \"Request " +
    "failed with status code 400\" — not the server's. Rendering it puts an " +
    "English line from an HTTP library in front of a reader who is owed the " +
    "reason the backend already wrote and translated.",
  advice:
    "Use `extractApiError(err, t('…'))` (`@/lib/errors`): it reads the\n" +
    "response body's `detail`, handles the object and validation-array\n" +
    "shapes, and falls back to the translated sentence you pass. To branch on\n" +
    "*what* failed, read the status — `isNotFoundError(err)` — never a\n" +
    "substring of the library's message.",

  run(files) {
    const considered = files.filter((f) => /\.\s*message\b/.test(f.text));
    const findings = [];

    for (const file of considered) {
      const text = withoutComments(file.text);
      for (const pattern of [READ, CAST]) {
        pattern.lastIndex = 0;
        let match;
        while ((match = pattern.exec(text)) !== null) {
          if (!FAILURE.test(match[1])) continue;
          if (excused(file.text, match.index)) continue;
          findings.push(`${file.path}:${lineAt(text, match.index)}`);
        }
      }
    }

    return { considered: considered.length, findings: findings.sort() };
  },
};

/**
 * Whether the read at `index` carries the marker.
 *
 * The scan runs on the comment-stripped copy, which blanks comments in place
 * rather than removing them — every offset still points at the same character
 * of the original, which is where the reason itself survives.
 */
function excused(original, index) {
  const before = original.slice(Math.max(0, index - LOOKBEHIND), index);
  const reason = before.match(EXCEPTION)?.[1] ?? "";
  const words = reason
    .replace(/\/\/|\*/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return words.length >= MIN_REASON_WORDS;
}
