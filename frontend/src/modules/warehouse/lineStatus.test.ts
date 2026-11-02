import { describe, expect, it } from "vitest";
import { getDocumentLineStatus } from "./lineStatus";

describe("getDocumentLineStatus", () => {
  it("reads wire quantities numerically, not lexicographically", () => {
    // The API ships decimal strings, and for lines without the backend's
    // own line_status this function decides: "3.000" >= "10.000" is true
    // read as text, which crowned a line done 3 of 10 as DONE.
    const line = {
      quantity: "10.000",
      expected_quantity: "10.000",
      done_quantity: "3.000",
    } as unknown as Parameters<typeof getDocumentLineStatus>[0];

    expect(getDocumentLineStatus(line, "COMPLETED")).toBe("PARTIAL");
  });

  it("calls a fully executed line done", () => {
    const line = {
      quantity: "10.000",
      expected_quantity: "10.000",
      done_quantity: "10.000",
    } as unknown as Parameters<typeof getDocumentLineStatus>[0];

    expect(getDocumentLineStatus(line, "COMPLETED")).toBe("DONE");
  });
});
