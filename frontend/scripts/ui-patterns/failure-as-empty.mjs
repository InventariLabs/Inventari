import { withoutComments } from "./lib.mjs";

/**
 * A list whose failed read is rendered as an empty one.
 *
 * `const { data: rules = [] } = useReorderRules()` is not a formatting
 * preference — the default array is the mechanism. It converts every outcome
 * the query can have into the same value, and the screen below then says
 * "nothing here yet" about a request that never arrived. No second mistake is
 * needed on top: writing that line and never reading `isError` is the whole
 * defect.
 *
 * It cost fifteen surfaces across four modules before anybody counted them,
 * and the sentences it produced were not blanks but claims — "0 of the 0
 * modules offered here are switched on", "EMAIL CONFIGURATION: NOT CONFIGURED", an offer to create the first of
 * six webhooks. Each was fixed one at a time, which is why this rule exists:
 * the sixteenth would have looked exactly like the first fifteen.
 *
 * The rule is narrow on purpose. A default array feeding a picker is right —
 * `options={items.map(…)}` over nothing renders an empty dropdown and says
 * nothing false. What is claimed here is the pair: a defaulted array, and an
 * empty state rendered over *that same* array — or over an array the
 * component builds out of it, whose every row came from the read — with
 * nothing anywhere in the file that looks at whether the read succeeded.
 *
 * What it deliberately does not see is the shape across files: the default
 * `= []` unpacked in one component, the `EmptyState` rendered in a child that
 * receives the list as a prop (`InvitationsSection` → `InvitationsList`). The
 * read and the claim live in different files, and this rule reads one file at
 * a time; a cross-file data-flow analysis is a different machine, not a
 * wider regex. The parent still qualifies the ordinary way the moment it
 * unpacks with a default — the child's prop is data by then, not a query
 * outcome this rule could reason about.
 */

/**
 * `data = []` and `data: rules = []`, capturing the name it lands under.
 *
 * Two of them, and deliberately: a `/g/` regex carries `lastIndex` between
 * calls, so using the same object for `test` and `matchAll` lets every second
 * file slip past the candidate filter unseen. The spec pins this down.
 */
const HAS_DEFAULT = /\bdata\s*(?::\s*\w+)?\s*=\s*\[\]/;
const DEFAULTED = /\bdata\s*(?::\s*(\w+))?\s*=\s*\[\]/g;

/** Any of the ways a file can be seen to look at the outcome. */
const LOOKS_AT_THE_OUTCOME = /\bisError\b|QueryError|QueryFailure|QueryResult/;

/**
 * An array the component builds itself: `const events = []` and
 * `const events: TimelineEvent[] = []`.
 *
 * A `useState` destructure does not match — `const [lines, setLines] =
 * useState([])` opens with `[`, not a name — so the component's own state
 * stays out, which is the point: an empty state over state the read never
 * fed says nothing false.
 */
const BUILT_HERE = /\bconst\s+(\w+)\s*(?::[^=;\n]+)?=\s*\[\]/g;

export default {
  name: "failure-as-empty",
  says:
    "A query unpacked as `data = []` and rendered through an empty state " +
    "turns a failed read into `nothing here yet`. Read `isError` and render " +
    "`QueryFailure`.",
  advice:
    "  const { data: rules = [], isLoading, isError, error, refetch } = useRules();\n" +
    "  …\n" +
    "  {isError ? (\n" +
    "    <QueryFailure error={error} onRetry={() => refetch()} />\n" +
    "  ) : isLoading ? (\n" +
    "    <LoadingSpinner />\n" +
    "  ) : rules.length === 0 ? (\n" +
    "    <EmptyState … />\n" +
    "  ) : (\n" +
    "    …\n" +
    "  )}\n\n" +
    "`QueryFailure` also separates a refusal from a malfunction, and withholds\n" +
    "the retry button on a 403.",

  run(files) {
    const considered = files.filter(
      (file) =>
        file.path.endsWith(".tsx") &&
        !file.path.includes(".test.") &&
        HAS_DEFAULT.test(withoutComments(file.text)),
    );

    const findings = [];
    for (const file of considered) {
      const text = withoutComments(file.text);
      if (LOOKS_AT_THE_OUTCOME.test(text)) continue;

      const names = [];
      for (const match of text.matchAll(DEFAULTED)) {
        names.push(match[1] ?? "data");
      }

      const empties = (name) =>
        new RegExp(`\\b${name}\\.length\\s*===\\s*0`).test(text);

      let claimed = names.some(empties);

      // The empty state may also sit over an array the component builds out
      // of the reads — `events` pushed up from `assignments` and `logs`.
      // That still claims something about a request the file never asked
      // about, provided the reads are actually consumed here: a read the
      // file unpacks and never touches fed nothing, so its default cannot
      // be the mechanism.
      if (!claimed) {
        // Twice, not once: the declaration itself carries the name, so a
        // second occurrence is the read being consumed somewhere below it.
        const consumed = names.some(
          (name) =>
            [...text.matchAll(new RegExp(`\\b${name}\\b`, "g"))].length > 1,
        );
        if (consumed) {
          for (const match of text.matchAll(BUILT_HERE)) {
            const built = match[1];
            if (names.includes(built)) continue;
            // Rendered, not computed: `built.length === 0 ?` or
            // `{built.length === 0 && (` is an empty state over the built
            // array. A bare `return built.length === 0` is a boolean the
            // code asked for — a tag-balance check, a validation result —
            // and claims nothing about the read.
            if (
              new RegExp(`\\b${built}\\.length\\s*===\\s*0\\s*(\\?|&&)`).test(
                text,
              )
            ) {
              claimed = true;
              break;
            }
          }
        }
      }

      if (claimed) findings.push(file.path);
    }

    return { considered: considered.length, findings };
  },
};
