import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";

export interface LoggedRequest {
  method: string;
  /** Path below `/api/v1`, no query string. */
  path: string;
  query: Record<string, string>;
  /** The JSON body, or `undefined` when there was none (or it was a form). */
  body: unknown;
}

/**
 * Answer every API call with `reply` and keep what was sent.
 *
 * A hook test of the "this click calls that endpoint" kind needs the method,
 * the path, the query and the body, not a handler per route. `reply` can
 * return a different payload per request; the default is an empty object.
 */
export function recordRequests(
  reply: (request: LoggedRequest) => unknown = () => ({}),
): LoggedRequest[] {
  const log: LoggedRequest[] = [];
  server.use(
    http.all("/api/v1/*", async ({ request }) => {
      const url = new URL(request.url);
      let body: unknown;
      if ((request.headers.get("content-type") ?? "").includes("json")) {
        body = await request.json();
      }
      const entry: LoggedRequest = {
        method: request.method,
        path: url.pathname.replace(/^\/api\/v1/, ""),
        query: Object.fromEntries(url.searchParams),
        body,
      };
      log.push(entry);
      const payload = reply(entry);
      return payload === undefined
        ? new HttpResponse(null, { status: 204 })
        : HttpResponse.json(payload as never);
    }),
  );
  return log;
}
