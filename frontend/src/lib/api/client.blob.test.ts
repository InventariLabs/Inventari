/**
 * A refusal written for a reader survives a route that answers with a file.
 *
 * `responseType: 'blob'` tells axios to read the body as a Blob whatever the
 * server sent it as, and the routes that answer with a file refuse in JSON
 * like every other route: FastAPI writes `{"detail": {"code", "message"}}` —
 * a sentence translated into the language the request asked for — and it
 * lands in `error.response.data` as an opaque Blob. Every reader of a failed
 * request (`extractApiError` and its field/rows siblings) looks for `detail`
 * on an object, finds nothing on a Blob, and answers with the caller's
 * fallback. Five screens had already wired the backend's sentence into their
 * toast and showed the generic one instead; the exports that never wired it
 * were the same defect at a different address.
 *
 * The un-wrapping belongs to the shared instance, not to the twelve call
 * sites that ask for a Blob today: a call site does not know its refusal
 * could arrive as a file, and a thirteenth would arrive believing a
 * rejection has nothing in it. So these tests go through the real client
 * and the mock server, and the assertion is what a screen would show.
 */
import { describe, expect, it } from "vitest";
import type { AxiosError } from "axios";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { extractApiError } from "@/lib/errors";
import { api } from "./client";

/** The sentence a screen shows when nothing in the body can be read. */
const FALLBACK = "Błąd podczas pobierania etykiet";

const REFUSAL = {
  detail: {
    code: "VALIDATION_ERROR",
    message: "Lokalizacja nie ma krótkiego kodu. Wygeneruj go najpierw.",
  },
};

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("the request was expected to be refused");
}

// jsdom 24 predates `Blob.prototype.text()`, and vitest runs this spec inside
// that realm — a Blob there carries no way to read itself, while the browser
// the app ships into has had the method since 2019. The gap is the test
// environment's, so it is filled here rather than worked around in the
// transport whose whole job is reading a body the caller cannot.
if (typeof Blob.prototype.text !== "function") {
  Blob.prototype.text = function (this: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

describe("a refusal that arrives as a blob", () => {
  it("reaches the screen as the sentence the backend wrote", async () => {
    server.use(
      http.get("*/api/v1/locations/:id/print", () =>
        HttpResponse.json(REFUSAL, { status: 400 }),
      ),
    );

    const error = await rejection(
      api.get("/locations/loc-1/print", { responseType: "blob" }),
    );

    expect(extractApiError(error, FALLBACK)).toBe(REFUSAL.detail.message);
    expect((error as AxiosError).response?.data).toEqual(REFUSAL);
  });

  it("leaves a body that is not JSON where it is", async () => {
    server.use(
      http.get(
        "*/api/v1/locations/:id/print",
        () =>
          new HttpResponse("<html>the gateway said no</html>", {
            status: 400,
            headers: { "Content-Type": "text/html" },
          }),
      ),
    );

    const error = await rejection(
      api.get("/locations/loc-1/print", { responseType: "blob" }),
    );
    const body = (error as AxiosError).response?.data;

    expect(body).toBeInstanceOf(Blob);
    expect(await (body as Blob).text()).toContain("the gateway said no");
    expect(extractApiError(error, FALLBACK)).toBe(FALLBACK);
  });

  it("leaves a body alone that announced JSON and is not JSON", async () => {
    server.use(
      http.get(
        "*/api/v1/locations/:id/print",
        () =>
          new HttpResponse('{"detail": {"message": "cut off', {
            status: 400,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );

    const error = await rejection(
      api.get("/locations/loc-1/print", { responseType: "blob" }),
    );

    expect((error as AxiosError).response?.status).toBe(400);
    expect((error as AxiosError).response?.data).toBeInstanceOf(Blob);
    expect(extractApiError(error, FALLBACK)).toBe(FALLBACK);
  });

  it("leaves a successful download the Blob it asked for", async () => {
    server.use(
      http.get(
        "*/api/v1/locations/:id/print",
        () =>
          new HttpResponse("PNG-BYTES", {
            status: 200,
            headers: { "Content-Type": "image/png" },
          }),
      ),
    );

    const response = await api.get<Blob>("/locations/loc-1/print", {
      responseType: "blob",
    });

    expect(response.data).toBeInstanceOf(Blob);
    expect(response.data.type).toBe("image/png");
    expect(await response.data.text()).toBe("PNG-BYTES");
  });

  it("says nothing about a failure that never reached the server", async () => {
    server.use(
      http.get("*/api/v1/locations/:id/print", () => HttpResponse.error()),
    );

    const error = await rejection(
      api.get("/locations/loc-1/print", { responseType: "blob" }),
    );

    expect((error as AxiosError).response).toBeUndefined();
    expect(extractApiError(error, FALLBACK)).toBe(FALLBACK);
  });
});
