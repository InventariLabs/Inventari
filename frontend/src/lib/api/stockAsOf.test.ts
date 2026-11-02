/**
 * The as-of report is asked with a date and answered as a number of rows or
 * a file. A refusal for a date before the first movement is the answer, not
 * an error to swallow, so a file request must hand the sentence on even
 * though the body arrives as a Blob.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { AxiosError, type AxiosResponse } from "axios";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { api } from "./client";
import { stockAsOfApi } from "./stockAsOf";

// jsdom predates Blob.prototype.text(); the browser the app ships into has it.
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

afterEach(() => {
  vi.restoreAllMocks();
});

function refusedWith(body: string): AxiosError {
  return new AxiosError(
    "Bad Request",
    "ERR_BAD_REQUEST",
    undefined,
    undefined,
    {
      status: 400,
      data: new Blob([body]),
    } as AxiosResponse,
  );
}

describe("stockAsOfApi", () => {
  it("sends the date and leaves out the filters that are not set", async () => {
    const report = { rows: [] };
    let search = "";
    server.use(
      http.get("*/api/v1/stock-as-of", ({ request }) => {
        search = new URL(request.url).search;
        return HttpResponse.json(report);
      }),
    );

    expect(await stockAsOfApi.get({ as_of: "2026-01-31" })).toEqual(report);
    expect(search).toBe("?as_of=2026-01-31");
  });

  it("sends the location and the page when the screen asks for them", async () => {
    let search = "";
    server.use(
      http.get("*/api/v1/stock-as-of", ({ request }) => {
        search = new URL(request.url).search;
        return HttpResponse.json({});
      }),
    );

    await stockAsOfApi.get({
      as_of: "2026-01-31",
      location_id: "loc1",
      limit: 50,
      offset: 0,
    });

    expect(Object.fromEntries(new URLSearchParams(search))).toEqual({
      as_of: "2026-01-31",
      location_id: "loc1",
      limit: "50",
      offset: "0",
    });
  });

  it.each([
    ["exportXlsx", "xlsx"],
    ["exportPdf", "pdf"],
  ] as const)(
    "%s downloads the file from the %s route without a page, so the file carries every row",
    async (method, route) => {
      let search = "";
      server.use(
        http.get(`*/api/v1/stock-as-of/export/${route}`, ({ request }) => {
          search = new URL(request.url).search;
          return new HttpResponse("file-bytes");
        }),
      );

      const blob = await stockAsOfApi[method]({ as_of: "2026-01-31" });

      expect(blob).toBeInstanceOf(Blob);
      expect(blob.size).toBe("file-bytes".length);
      expect(search).toBe("?as_of=2026-01-31");
    },
  );

  it.each(["exportXlsx", "exportPdf"] as const)(
    "%s turns a refusal that arrived as a file into the server's sentence",
    async (method) => {
      const refusal = { detail: "No movements before 2025-03-01" };
      vi.spyOn(api, "get").mockRejectedValue(
        refusedWith(JSON.stringify(refusal)),
      );

      const error = await stockAsOfApi[method]({ as_of: "2020-01-01" }).catch(
        (e: unknown) => e,
      );

      expect((error as AxiosError).response?.data).toEqual(refusal);
    },
  );

  it("keeps a refusal that is not JSON as its text under detail, so the reader still gets a sentence", async () => {
    vi.spyOn(api, "get").mockRejectedValue(refusedWith("plain text refusal"));

    const error = await stockAsOfApi
      .exportPdf({ as_of: "2020-01-01" })
      .catch((e: unknown) => e);

    expect((error as AxiosError).response?.data).toEqual({
      detail: "plain text refusal",
    });
  });

  it("rethrows an error that is not an HTTP answer untouched", async () => {
    const failure = new Error("network down");
    vi.spyOn(api, "get").mockRejectedValue(failure);

    await expect(stockAsOfApi.exportXlsx({ as_of: "2026-01-31" })).rejects.toBe(
      failure,
    );
  });
});
