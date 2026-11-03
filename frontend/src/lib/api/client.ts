import axios from "axios";
import type { InternalAxiosRequestConfig } from "axios";
import i18next from "i18next";

import { SessionEndedError, isServerRefusal } from "@/lib/errors";

const API_BASE_URL = "/api/v1";

// Access token stored in module memory only — never in localStorage.
// This prevents XSS attacks from stealing the token via localStorage.
// The refresh token is stored in an HttpOnly cookie by the backend.
let _accessToken: string | null = null;

export const tokenStore = {
  get: () => _accessToken,
  set: (token: string) => {
    _accessToken = token;
  },
  clear: () => {
    _accessToken = null;
  },
};

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  withCredentials: true,
});

/**
 * Auth, language, and the one header an upload must not carry.
 *
 * Exported so it can be tested directly: jsdom's XHR does not put a real
 * multipart body on the wire, so a round trip through the mock server
 * cannot answer the question this function exists for.
 */
export const applyRequestHeaders = <T extends InternalAxiosRequestConfig>(
  config: T,
): T => {
  const token = tokenStore.get();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  config.headers["Accept-Language"] = i18next.language || "en";

  // An upload leaves as an upload, whoever wrote the call. This instance
  // declares JSON, and axios reads that header before it looks at the body:
  // a FormData payload under a JSON content type is not sent as multipart at
  // all — it goes through `formDataToJSON` and posts an object, where a File
  // has no representation and the field simply vanishes. The server then
  // answers 422 about a file the user definitely picked, which is exactly
  // how the organization logo became impossible to upload from the
  // interface. Eleven of the twelve upload helpers remembered to pass the
  // header by hand and the twelfth did not, which is what remembering gets
  // you. Dropping it here lets the browser write the real one — boundary
  // included, which no hand-written `multipart/form-data` can carry anyway.
  if (config.data instanceof FormData) {
    config.headers.delete("Content-Type");
  }
  return config;
};

// Add auth token and language to requests
api.interceptors.request.use(applyRequestHeaders);

/**
 * A refusal that arrives as a file.
 *
 * `responseType: 'blob'` tells axios to read the body as a Blob whatever the
 * server sent it as, and a route that answers with a file refuses in JSON like
 * any other route: FastAPI writes `{"detail": {"code", "message"}}` — a
 * sentence translated into the language the request asked for — and it lands
 * in `error.response.data` as an opaque blob. Every reader of a failed request
 * (`extractApiError` and its field/rows siblings) looks for `detail` on an
 * object, finds none on a Blob, and hands the reader the caller's fallback.
 * Five screens had already wired the backend's sentence into their toast and
 * showed the generic one instead.
 *
 * So the body is un-wrapped here, once, rather than at each of the twelve call
 * sites that ask for a Blob today: a call site does not know its refusal could
 * arrive as a file, and the thirteenth would arrive believing a rejection has
 * nothing in it. Best-effort on purpose — a body that does not read as JSON
 * stays a Blob, where the caller's fallback is a better sentence than a parse
 * error, and a body whose media type is not JSON is not a sentence at all.
 */
async function readBlobRefusal(error: unknown): Promise<void> {
  if (!axios.isAxiosError(error)) return;
  const response = error.response;
  if (!response) return;

  const body: unknown = response.data;
  if (!(body instanceof Blob)) return;
  if (!body.type.includes("json")) return;

  try {
    response.data = JSON.parse(await body.text()) as unknown;
  } catch {
    // Left as it came in.
  }
}

// Queue for concurrent requests during refresh
let isRefreshing = false;
let failedQueue: {
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}[] = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token!);
    }
  });
  failedQueue = [];
};

/**
 * What a request that was waiting on the session is told when the session is
 * over: the sign-in form follows, and the toast that would have said "Failed
 * to add" says instead that the session ended — and, for a request that was
 * going to save something, that the work was not saved. A read saved nothing,
 * so the sentence it gets does not claim otherwise.
 */
function sessionEndedError(
  request: { method?: string } | undefined,
): SessionEndedError {
  const method = (request?.method ?? "get").toLowerCase();
  const reads = method === "get" || method === "head" || method === "options";
  return new SessionEndedError(
    i18next.t(
      reads ? "common:errors.sessionEndedRead" : "common:errors.sessionEnded",
    ),
  );
}

// Handle 401 errors with Silent Refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Before any branch below reads the error: a refusal behind a file route
    // is JSON inside a Blob, and no reader downstream should have to know.
    await readBlobRefusal(error);
    const originalRequest = error.config;

    // Prevent infinite loop if refresh endpoint itself returns 401
    if (originalRequest.url === "/auth/refresh") {
      return Promise.reject(error);
    }

    // A 401 from the sign-in form is the answer to the credentials just
    // typed: there is no session behind it to refresh. Probing anyway added
    // a second failed request to every failed sign-in and replaced the
    // form's own "invalid credentials" sentence with the probe's refusal.
    if (originalRequest.url === "/auth/login") {
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise<string>((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          })
          .catch((err) => {
            // The sentence is worded by what this request was doing, not by
            // what the request that started the refresh was.
            return Promise.reject(
              err instanceof SessionEndedError
                ? sessionEndedError(originalRequest)
                : err,
            );
          });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // Bare axios on purpose: this call must not re-enter the 401
        // machinery above. It still has to speak the app's language — its
        // refusal (an expired session, a revoked refresh token) surfaces in
        // toasts of the queued requests — so the header the request
        // interceptor would have added is added by hand.
        const { data } = await axios.post<{ access_token?: string }>(
          `${API_BASE_URL}/auth/refresh`,
          {},
          {
            withCredentials: true,
            headers: { "Accept-Language": i18next.language || "en" },
          },
        );
        const access_token = data?.access_token;
        if (!access_token) {
          // 204: the server answered that there is no session to refresh.
          // The 401 that led here is final — end the session the same way a
          // refusal does: the catch below reads this error as one and is the
          // only place that clears the token and announces the sign-out.
          throw sessionEndedError(originalRequest);
        }
        tokenStore.set(access_token);
        // Notify long-lived consumers (WebSocket bridge) that the access
        // token rotated so they can rebuild their connection with the new
        // token instead of staying attached to the expired one.
        window.dispatchEvent(new CustomEvent("auth:token-refreshed"));
        processQueue(null, access_token);
        originalRequest.headers.Authorization = `Bearer ${access_token}`;
        return api(originalRequest);
      } catch (caught) {
        // The server's own refusal ends the session; the caller whose request
        // started this reads it as that, not as the refusal's raw sentence or
        // as its own generic failure.
        const refreshError = isServerRefusal(caught)
          ? sessionEndedError(originalRequest)
          : caught;
        processQueue(refreshError, null);
        // A refresh that never got an answer is an outage, not a session's
        // end: the token may still be good the moment the server returns,
        // and only the server's own refusal (4xx) says otherwise. Clearing
        // on an unanswered ask sent a reader whose session was fine to the
        // sign-in form, exactly when the outage screen had promised not to.
        if (isServerRefusal(caught)) {
          tokenStore.clear();
          window.dispatchEvent(new CustomEvent("auth:logout"));
        }
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }
    return Promise.reject(error);
  },
);

/**
 * The offset envelope a list endpoint answers with — `PaginatedResponse` in
 * `backend/app/schemas/pagination.py`, described in
 * `docs/subsystems/PAGINATION.md`.
 */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** The largest page a list endpoint serves (`le=200` on its `limit`). */
const PAGE_LIMIT = 200;

/**
 * Every row of a paged list, read one page after another.
 *
 * For the readers that need the whole set — a picker, a settings table, the
 * location list a tree is drawn from. They read a bare array before the lists
 * moved to the envelope, and the first page alone would quietly cut them at
 * the default page size. A screen that shows one page at a time reads the
 * envelope itself instead.
 */
export async function getEveryPage<T>(
  url: string,
  params?: object,
): Promise<T[]> {
  const rows: T[] = [];
  for (;;) {
    const { data } = await api.get<Page<T>>(url, {
      params: { ...params, limit: PAGE_LIMIT, offset: rows.length },
    });
    rows.push(...data.items);
    if (!data.has_more || data.items.length === 0) return rows;
  }
}
