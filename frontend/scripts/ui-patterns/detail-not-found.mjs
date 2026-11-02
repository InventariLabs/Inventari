import { withoutComments } from "./lib.mjs";

/**
 * A detail screen that answers "this record is gone" with its own invention.
 *
 * Every detail route can be opened with an id that no longer resolves — a
 * deleted record, a stale bookmark, a link from someone else's organization.
 * The server's answer is the same 404 every time; the screens' answers were
 * not. Eleven of them had six different replies: a bare sentence with no way
 * out, a red block quoting the API's error text, "Failed to load" over a
 * record that loaded fine and simply is not there, and — the one that costs
 * the reader most — "Try again" on a request the server has already refused.
 *
 * The rule is three branches, in this order: loading, a failed request
 * (`QueryError`, retryable), and a record that is not there (`RecordNotFound`,
 * one way back to the list). Telling the second from the third is what
 * `isNotFoundError` is for; without it the error branch swallows the 404 and
 * the not-found branch below it is unreachable.
 */
export default {
  name: "detail-not-found",
  says:
    "A detail page that reads a record must tell a failed request from a " +
    "record that is not there: `isNotFoundError` to split them, " +
    "`RecordNotFound` to render the second.",
  advice:
    "  if (isLoading) return <LoadingSpinner />;\n" +
    "  if (isError && !isNotFoundError(error)) return <QueryError onRetry={…} />;\n" +
    '  if (!record) return <RecordNotFound title={…} backTo="/…" backLabel={…} />;\n\n' +
    "Retrying is not offered on the third branch: `shouldRetryQuery` already\n" +
    "stops repeating a 4xx, and a button that repeats a doomed request sends\n" +
    "the reader back to the same wall.",

  run(files) {
    // The candidate set used to be `pages/*Detail*.tsx` — a guess about what
    // somebody named the file, not about what it does. It missed
    // LinkedReceiptsPage, which reads a purchase order by route id and told
    // the reader it did not exist whenever the request failed, and it missed
    // both stock-take pages. Ask the question the rule is actually about:
    // does this page take an id off the route and read one record with it?
    const pages = files.filter(
      (file) =>
        /^modules\/[^/]+\/pages\/[^/]*\.tsx$/.test(file.path) &&
        !file.path.includes(".test."),
    );

    const considered = pages.filter((file) => {
      const text = withoutComments(file.text);

      // What the rule is actually about. No error guard here on purpose: a
      // page that renders "not found" without ever looking at the error is
      // precisely the defect, and LinkedReceiptsPage did not mention `error`
      // anywhere while telling readers their order did not exist.
      const readsRecordById =
        /useParams</.test(text) && /\(\s*id\s*(\?\?\s*""|[,)])/.test(text);
      if (readsRecordById) return true;

      // Union, not replacement: the name is still a signal, and dropping it
      // would have quietly let two maker pages out of a set they pass today
      // and would stop being checked tomorrow. It is a guess about what
      // somebody called the file, though, so it keeps the guard that stops it
      // claiming a page which reads no record at all.
      const namedDetail = /\/pages\/[^/]*Detail[^/]*\.tsx$/.test(file.path);
      return namedDetail && /\bisError\b|\berror\b/.test(text);
    });

    const findings = [];
    for (const file of considered) {
      const text = withoutComments(file.text);
      // Both halves matter and the old guard let one through: a page that
      // never mentions `error` was skipped, and a page that renders "not
      // found" without ever looking at the error is precisely the defect.
      //
      // `isNotFound` counts as well as `isNotFoundError`: the stock-take page
      // splits the two cases correctly, it just does the splitting inside its
      // hook and receives the answer as a flag. Insisting on one spelling
      // would make this a rule about style rather than about behaviour.
      const splitsTheCases = /\bisNotFound(Error)?\b/.test(text);
      if (splitsTheCases && text.includes("RecordNotFound")) {
        continue;
      }
      findings.push(file.path);
    }

    return { considered: considered.length, findings };
  },
};
