import axios from "axios";
import { describe, it, expect } from "vitest";
import {
  extractApiError,
  isNotFoundError,
  isServerRefusal,
  isUnreachableError,
  shouldRetryQuery,
} from "./errors";

describe("extractApiError", () => {
  it("returns fallback for non-axios errors", () => {
    expect(extractApiError(new Error("generic"), "fallback")).toBe("fallback");
  });

  it("returns fallback for null", () => {
    expect(extractApiError(null, "fallback")).toBe("fallback");
  });

  it("returns fallback for string", () => {
    expect(extractApiError("some string", "fallback")).toBe("fallback");
  });

  it("returns detail from axios response", () => {
    const err = new axios.AxiosError();
    err.response = { data: { detail: "Not found" } } as typeof err.response;
    expect(extractApiError(err, "fallback")).toBe("Not found");
  });

  it("returns message from axios response when no detail", () => {
    const err = new axios.AxiosError();
    err.response = {
      data: { message: "Unauthorized" },
    } as typeof err.response;
    expect(extractApiError(err, "fallback")).toBe("Unauthorized");
  });

  it("returns fallback when axios response has no detail or message", () => {
    const err = new axios.AxiosError();
    err.response = { data: {} } as typeof err.response;
    expect(extractApiError(err, "fallback")).toBe("fallback");
  });

  it("never shows a 500's detail — that sentence is for the logs", () => {
    // A server error's detail is an exception message, a stack summary, or in
    // a debug build the fault injector's own words. The reader can act on none
    // of them, and half the screens in the inventory were printing it verbatim.
    const err = new axios.AxiosError();
    err.response = {
      status: 500,
      data: { detail: "QA fault injection: forced 500" },
    } as typeof err.response;
    expect(extractApiError(err, "fallback")).toBe("fallback");
  });

  it("still shows a 403's detail — that one is written to be read", () => {
    const err = new axios.AxiosError();
    err.response = {
      status: 403,
      data: { detail: "You do not have permission to perform this action" },
    } as typeof err.response;
    expect(extractApiError(err, "fallback")).toBe(
      "You do not have permission to perform this action",
    );
  });

  it("returns fallback when axios error has no response", () => {
    const err = new axios.AxiosError();
    expect(extractApiError(err, "fallback")).toBe("fallback");
  });

  it("never prints the API key of the field a 422 speaks about", () => {
    // The key is an English snake_case word ("count: Muss kleiner oder
    // gleich 500 sein"), the one untranslated part of an otherwise
    // translated sentence. The server's message stands on its own.
    const error = {
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          detail: [
            {
              loc: ["body", "api_base_url"],
              msg: "Input should be a valid string",
              type: "string_type",
            },
          ],
        },
      },
    };
    expect(extractApiError(error, "fallback")).toBe(
      "Input should be a valid string",
    );
  });
});

describe("isServerRefusal", () => {
  const refusal = (status: number) => {
    const err = new axios.AxiosError();
    err.response = { status } as typeof err.response;
    return err;
  };

  it("says yes to a 4xx — the server answered and refused", () => {
    expect(isServerRefusal(refusal(400))).toBe(true);
    expect(isServerRefusal(refusal(401))).toBe(true);
    expect(isServerRefusal(refusal(499))).toBe(true);
  });

  it("says no just below the range", () => {
    expect(isServerRefusal(refusal(399))).toBe(false);
  });

  it("says no to a 5xx — the server's own failure, not a refusal", () => {
    expect(isServerRefusal(refusal(500))).toBe(false);
    expect(isServerRefusal(refusal(503))).toBe(false);
  });

  it("says no to a request that was never answered", () => {
    expect(isServerRefusal(new axios.AxiosError())).toBe(false);
    expect(isServerRefusal(new Error("offline"))).toBe(false);
  });
});

describe("shouldRetryQuery", () => {
  const axiosError = (status: number) =>
    Object.assign(new Error(`status ${status}`), {
      isAxiosError: true,
      response: { status },
      toJSON: () => ({}),
    });

  it("does not retry a 404 — the resource is missing, not unreachable", () => {
    expect(shouldRetryQuery(0, axiosError(404))).toBe(false);
  });

  it("does not retry any other client error either", () => {
    expect(shouldRetryQuery(0, axiosError(403))).toBe(false);
    expect(shouldRetryQuery(0, axiosError(422))).toBe(false);
  });

  it("retries a server error once", () => {
    expect(shouldRetryQuery(0, axiosError(500))).toBe(true);
    expect(shouldRetryQuery(1, axiosError(500))).toBe(false);
  });

  it("retries a network failure once", () => {
    expect(shouldRetryQuery(0, new Error("Network Error"))).toBe(true);
  });
});

describe("isNotFoundError", () => {
  const axiosError = (status: number, data: unknown) => {
    const err = new axios.AxiosError();
    err.response = { status, data } as typeof err.response;
    return err;
  };

  it("says yes to a record that is not there", () => {
    expect(isNotFoundError(axiosError(404, { detail: "Not found" }))).toBe(
      true,
    );
  });

  // The id in a shared link gets cut by chat clients and mail readers, and the
  // server answers a broken one with 422, not 404. To the reader both are the
  // same event: the thing this address names is not there. A screen that told
  // them apart offered "Try again" on a request that can only ever be refused.
  it("says yes to an id in the address that is not an id", () => {
    const rejected = axiosError(422, {
      detail: [
        {
          type: "uuid_parsing",
          loc: ["path", "doc_id"],
          msg: "Must be a valid identifier",
        },
      ],
    });

    expect(isNotFoundError(rejected)).toBe(true);
  });

  it("says no to a 422 about what was sent, not about the address", () => {
    const rejected = axiosError(422, {
      detail: [
        { type: "missing", loc: ["body", "name"], msg: "Field required" },
      ],
    });

    expect(isNotFoundError(rejected)).toBe(false);
  });

  it("says no to a request that could not be asked at all", () => {
    expect(isNotFoundError(axiosError(500, { detail: "boom" }))).toBe(false);
    expect(isNotFoundError(new Error("offline"))).toBe(false);
  });
});

describe("isUnreachableError", () => {
  const answered = (status: number, data?: unknown) => {
    const err = new axios.AxiosError();
    err.response = { status, data } as typeof err.response;
    return err;
  };

  it("says yes to a request nothing answered", () => {
    expect(isUnreachableError(new axios.AxiosError("Network Error"))).toBe(
      true,
    );
  });

  it("says no to a cancelled request", () => {
    const err = new axios.AxiosError("cancelled");
    err.code = axios.AxiosError.ERR_CANCELED;
    expect(isUnreachableError(err)).toBe(false);
  });

  it("says yes to a proxy's gateway answer, which has no detail", () => {
    for (const status of [502, 503, 504]) {
      expect(isUnreachableError(answered(status, "<html>gateway</html>"))).toBe(
        true,
      );
    }
  });

  it("says no to the application's own 503 and to its 500", () => {
    expect(
      isUnreachableError(answered(503, { detail: "No AI provider" })),
    ).toBe(false);
    expect(isUnreachableError(answered(500, "oops"))).toBe(false);
  });
});
