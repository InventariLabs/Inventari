import { http, HttpResponse } from "msw";

import { server } from "./server";

/**
 * Error responses for tests.
 *
 * handlers.ts answers 175 routes and refuses only 4 of them, so a component
 * that swallows a 500 and renders an empty list instead of a message passes
 * every existing test. These helpers let a single test push one failure onto
 * a route without disturbing the rest of the suite — `server.resetHandlers()`
 * in the global afterEach undoes them either way.
 */

type Method = "get" | "post" | "put" | "patch" | "delete";

interface ErrorOptions {
  /** HTTP verb to fail. Defaults to GET, the shape a list page uses. */
  method?: Method;
  /** Structured error code, as the backend sends it under `detail`. */
  code?: string;
  /** Human-readable message; what extractApiError surfaces. */
  message?: string;
}

const DEFAULT_MESSAGES: Record<number, string> = {
  400: "Bad request",
  401: "Not authenticated",
  403: "Forbidden",
  404: "Not found",
  409: "Conflict",
  422: "Validation failed",
  500: "Internal server error",
};

function errorBody(status: number, options: ErrorOptions) {
  const message =
    options.message ?? DEFAULT_MESSAGES[status] ?? "Request failed";
  return options.code
    ? { detail: { code: options.code, message } }
    : { detail: message };
}

/**
 * Fail the **next** request to *path* with *status*, then fall back to the
 * default handler. Use this when the component retries or refetches and only
 * the first attempt should fail.
 */
export function errorOnce(
  path: string,
  status: number,
  options: ErrorOptions = {},
): void {
  const method = options.method ?? "get";
  server.use(
    http[method](
      path,
      () => HttpResponse.json(errorBody(status, options), { status }),
      { once: true },
    ),
  );
}

/**
 * Fail **every** request to *path* with *status* for the rest of the test.
 * The honest default for "the server is down" cases — a component that
 * refetches would otherwise recover behind the assertion's back.
 */
export function errorAlways(
  path: string,
  status: number,
  options: ErrorOptions = {},
): void {
  const method = options.method ?? "get";
  server.use(
    http[method](path, () =>
      HttpResponse.json(errorBody(status, options), { status }),
    ),
  );
}
