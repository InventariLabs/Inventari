import axios from "axios";

interface ApiErrorDetail {
  code: string;
  message: string;
  field?: string;
}

/**
 * Extracts a human-readable error message from an API error response.
 * Handles old format (detail as string), new format (detail as object),
 * and FastAPI validation errors (detail as an array of {loc, msg, type}).
 * For arrays, returns the first message — callers that need per-field
 * mapping should use parseApiValidationErrors from lib/validationErrors.
 */
export function extractApiError(error: unknown, fallback: string): string {
  const readable = readableErrorMessage(error);
  if (readable) return readable;
  if (axios.isAxiosError(error)) {
    // A 5xx `detail` is written for whoever reads the logs — an exception
    // message, a stack summary, the fault injector's own sentence. Handing it
    // to the person at the screen tells them nothing they can act on and, in a
    // debug build, shows them the inside of the machine. A business rule speaks
    // through a 4xx (AGENTS.md, "Error Handling Rules"), and that detail is a
    // translated sentence meant to be read.
    if ((error.response?.status ?? 0) >= 500) return fallback;

    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // A 422 array carries one entry per failing field. "Input should be
      // a valid string" on its own names nothing; the entry's last `loc`
      // segment does, so the reader knows which field to fix.
      const first = detail[0];
      if (first && typeof first === "object" && "msg" in first) {
        const msg = (first as { msg: unknown }).msg;
        if (typeof msg === "string") {
          const loc = (first as { loc?: unknown }).loc;
          const field =
            Array.isArray(loc) && loc.length > 0
              ? String(loc[loc.length - 1])
              : null;
          return field && field !== "body" ? `${field}: ${msg}` : msg;
        }
      }
      return fallback;
    }
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      return (detail as ApiErrorDetail).message;
    }
    return error.response?.data?.message || fallback;
  }
  return fallback;
}

/**
 * A failure whose message was already written for the reader.
 *
 * `extractApiError` deliberately refuses to show a raw `Error.message` — most
 * of them are meant for the log, and a `TypeError` on screen helps nobody.
 * This one says the opposite: the caller composed the sentence, in the
 * reader's language, and it should be shown. It is how an operation that
 * answered `200` while doing nothing ("every selected asset is still checked
 * out") reaches a dialog that only knows how to await a promise.
 */
export class ReadableError extends Error {}

/**
 * The session is over and the sign-in form follows. A readable sentence for
 * the toast of whatever request was waiting, that still answers to the status
 * the server gave: the auth store and the API client tell "the server refused"
 * from "the server went quiet" by it.
 */
export class SessionEndedError extends ReadableError {
  readonly status = 401;
}

/**
 * The sentence for a step that ran after the main write had already landed.
 *
 * An ended session's own sentence says the work was not saved, which is not
 * true once the record exists — a photo or an attachment going up after the
 * create must not tell the reader to start over (and make a duplicate). The
 * step's own failure sentence stands in; any other failure reads as usual.
 */
export function followUpError(error: unknown, fallback: string): string {
  return error instanceof SessionEndedError
    ? fallback
    : extractApiError(error, fallback);
}

/** The sentence a `ReadableError` carries, or null for anything else. */
export function readableErrorMessage(error: unknown): string | null {
  // ui-pattern: error-message-as-copy — this class exists to mark a message
  // that was composed for the reader rather than for the log, and something
  // has to be allowed to unwrap it
  return error instanceof ReadableError && error.message ? error.message : null;
}

/**
 * HTTP status of a failed request, or null when the failure never reached the
 * server (network, cancellation) or is not an API error at all.
 *
 * For screens that must tell "you may not" from "it broke": both arrive as a
 * rejected query, and a single message for the two of them sends the reader
 * looking for an outage that is not there.
 */
export function apiErrorStatus(error: unknown): number | null {
  if (error instanceof SessionEndedError) return error.status;
  if (!axios.isAxiosError(error)) return null;
  return error.response?.status ?? null;
}

/**
 * The request never got an answer — the server is down, the network dropped,
 * a proxy swallowed it. A cancelled request is not that: someone asked for it
 * to stop. For screens that print a failure in place of a list and must not
 * call an outage "An error occurred".
 *
 * A reverse proxy in front of a stopped backend does answer, with a 502, 503
 * or 504 whose body is its own page; for the reader that is the same outage.
 * The application's own 503 (a feature that is not configured) carries a
 * `detail` and stays an answer.
 */
export function isUnreachableError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  if (!error.response) return error.code !== axios.AxiosError.ERR_CANCELED;
  const { status, data } = error.response;
  return (
    (status === 502 || status === 503 || status === 504) &&
    !(typeof data === "object" && data !== null && "detail" in data)
  );
}

/**
 * The server answered and refused — a 4xx.
 *
 * A refusal is final: the credentials behind the request are no longer good,
 * and the only way on is the sign-in form. Anything else — a 5xx, a proxy
 * error, an ask that never arrived at all — is the question going unanswered,
 * and the credential may well still be good the moment the server returns;
 * throwing it away for an outage signs the reader out of a session that
 * signing in again cannot restore either.
 *
 * One definition, shared by the two layers that have to tell the cases apart:
 * the auth store, deciding whether a failed session check ends the session,
 * and the API client, deciding whether a failed silent refresh tears the
 * token down. They used to hold a copy each, and a drift between the two
 * would read one refusal as a session's end and the same refusal as an
 * outage in the other.
 */
export function isServerRefusal(error: unknown): boolean {
  const status = apiErrorStatus(error);
  return status !== null && status >= 400 && status < 500;
}

/**
 * Extracts a named string field from a structured error `detail` envelope
 * (e.g. the `product` extra attached to CORRECTION_ITEM_MISSING). Returns
 * null when the error or the field is absent.
 */
export function extractApiErrorField(
  error: unknown,
  field: string,
): string | null {
  if (!axios.isAxiosError(error)) return null;
  const body = error.response?.data as unknown;
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const value = (detail as Record<string, unknown>)[field];
  return typeof value === "string" ? value : null;
}

/**
 * Extracts a named list of rows from a structured error `detail` envelope
 * (e.g. the `over_cap_items` a stock take refuses to post on). Returns null
 * when the error, the field, or its row shape is absent — so a caller can
 * tell "the server named the offending rows" from "something else broke".
 */
export function extractApiErrorRows(
  error: unknown,
  field: string,
): Record<string, unknown>[] | null {
  if (!axios.isAxiosError(error)) return null;
  const body = error.response?.data as unknown;
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const value = (detail as Record<string, unknown>)[field];
  if (!Array.isArray(value)) return null;
  return value.filter(
    (row): row is Record<string, unknown> =>
      typeof row === "object" && row !== null,
  );
}

/**
 * Message a FastAPI 422 attributed to a single named body field, or null.
 *
 * The sibling of `parseApiValidationErrors` for forms with a handful of
 * named fields and no line structure: it answers "did the server object to
 * *this* field?" so the caller can put the message where the problem is
 * instead of in a toast with nothing to point at. The message is the
 * server's own sentence and therefore not translated — a form that knows
 * the rule should check it before sending and use its own catalogue.
 */
export function extractFieldValidationError(
  error: unknown,
  field: string,
): string | null {
  if (!axios.isAxiosError(error)) return null;
  const detail = error.response?.data?.detail;
  if (!Array.isArray(detail)) return null;
  for (const entry of detail) {
    if (!entry || typeof entry !== "object") continue;
    const loc = (entry as { loc?: unknown }).loc;
    const msg = (entry as { msg?: unknown }).msg;
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    if (loc[loc.length - 1] === field) return msg;
  }
  return null;
}

/**
 * Extracts the structured error `code` (e.g. "APPROVAL_REQUIRED") from an
 * API error response. Returns null when the response carries no code —
 * callers then fall back to the human-readable message.
 */
export function extractApiErrorCode(error: unknown): string | null {
  if (!axios.isAxiosError(error)) return null;
  const body = error.response?.data as unknown;
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      const code = (detail as { code: unknown }).code;
      return typeof code === "string" ? code : null;
    }
    const code = (body as { code?: unknown }).code;
    return typeof code === "string" ? code : null;
  }
  return null;
}

/**
 * A 422 the address caused: the id in the path is not an id.
 *
 * The server validates a path parameter before it looks anything up, so a
 * broken id never reaches the 404 — it comes back as a validation error whose
 * `loc` starts at "path". A 422 about the body is a different event entirely
 * (the form that was sent is wrong), and stays one.
 */
function isPathParameterRejection(
  error: unknown,
  places: readonly string[] = ["path"],
): boolean {
  if (!axios.isAxiosError(error) || error.response?.status !== 422)
    return false;
  const detail = (error.response?.data as { detail?: unknown } | undefined)
    ?.detail;
  if (!Array.isArray(detail)) return false;
  return detail.some((entry) => {
    const loc = (entry as { loc?: unknown } | null)?.loc;
    return Array.isArray(loc) && places.includes(String(loc[0]));
  });
}

/**
 * Whether a failed request means "this does not exist" rather than "we could
 * not ask".
 *
 * Detail screens used to render their not-found state for every failure, so a
 * dropped connection told the reader their document had been deleted. Only a
 * 404 says that; everything else deserves a retry.
 *
 * Everything except an id the server would not even read. These addresses are
 * UUIDs, and chat clients and mail readers cut them — a truncated link then
 * landed on "Something went wrong · Try again", a button that repeats a
 * request the server can only refuse again, on a screen with no way back to
 * the list. The reader's event is the same in both cases: what this address
 * names is not there.
 */
export function isNotFoundError(error: unknown): boolean {
  if (isPathParameterRejection(error)) return true;
  return axios.isAxiosError(error) && error.response?.status === 404;
}

/**
 * A 422 on an identifier the address named, whether the server read it from
 * the path or — for a screen that asks a list "which of these ids" — from the
 * query. Either way the reader's event is that what the address names is not
 * there, not that the request failed.
 */
export function isIdentifierRejection(error: unknown): boolean {
  return isPathParameterRejection(error, ["path", "query"]);
}

/**
 * A refusal, not a failure.
 *
 * "Try again" is a promise, and on a 403 it is a false one: the server
 * understood the request and answered no, so the same request will be refused
 * as often as it is sent. A screen that cannot tell the two apart either offers
 * a button that never works or reads the refusal as an empty list.
 */
export function isForbiddenError(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 403;
}

/**
 * Retry policy for React Query.
 *
 * ``retry: 1`` treated every failure as transient, so a detail screen opened
 * with a stale id fired the same doomed request twice before settling on its
 * not-found state. A 4xx is an answer, not a hiccup: the server understood the
 * request and said no. Only server errors and failures with no response at all
 * are worth a second attempt.
 */
export function shouldRetryQuery(
  failureCount: number,
  error: unknown,
): boolean {
  if (isServerRefusal(error)) return false;
  return failureCount < 1;
}
