import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { extractApiError } from "@/lib/errors";
import { equipmentAssignmentsApi } from "./equipment_assignments";

describe("fetchProtocolHtml — a refusal through the text transport", () => {
  it("hands the backend's sentence to extractApiError", async () => {
    // With responseType "text" the refusal body arrives as an unparsed JSON
    // string, and extractApiError reads no detail out of a string — the
    // sentence used to stop at this seam and the caller printed its canned
    // line. The API parses the body once, where the transport is known.
    server.use(
      http.get("*/equipment/assignments/:assignmentId/protocol/html", () =>
        HttpResponse.text(
          JSON.stringify({
            detail: {
              code: "PROTOCOL_ARCHIVED",
              message: "Protokół zarchiwizowany",
            },
          }),
          { status: 409 },
        ),
      ),
    );

    let thrown: unknown = null;
    try {
      await equipmentAssignmentsApi.fetchProtocolHtml("a-1");
    } catch (error) {
      thrown = error;
    }
    expect(thrown).not.toBeNull();
    expect(extractApiError(thrown, "canned fallback")).toBe(
      "Protokół zarchiwizowany",
    );
  });

  it("keeps the caller's fallback when the body is not JSON", async () => {
    server.use(
      http.get("*/equipment/assignments/:assignmentId/protocol/html", () =>
        HttpResponse.text("<html>gateway says no</html>", { status: 502 }),
      ),
    );

    let thrown: unknown = null;
    try {
      await equipmentAssignmentsApi.fetchProtocolHtml("a-1");
    } catch (error) {
      thrown = error;
    }
    expect(thrown).not.toBeNull();
    // A 5xx is written for the log, never for the screen — the fallback wins.
    expect(extractApiError(thrown, "canned fallback")).toBe("canned fallback");
  });
});
