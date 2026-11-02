import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { documentsApi } from "./documents";

/** What the work-items assign request puts on the wire. */
function captureAssign(bodies: unknown[]) {
  server.use(
    http.put(
      "*/warehouse/work-items/:kind/:id/assignee",
      async ({ request }) => {
        bodies.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      },
    ),
  );
}

describe("assignWorkItem", () => {
  it("claims a task for the reader only while nobody holds it", async () => {
    const bodies: unknown[] = [];
    captureAssign(bodies);

    await documentsApi.assignWorkItem("document", "doc-1", "user-me", {
      onlyIfUnassigned: true,
    });

    expect(bodies).toEqual([
      { assignee_id: "user-me", only_if_unassigned: true },
    ]);
  });

  it("leaves an ordinary assignment unconditional", async () => {
    const bodies: unknown[] = [];
    captureAssign(bodies);

    await documentsApi.assignWorkItem("document", "doc-1", "user-me");

    expect(bodies).toEqual([{ assignee_id: "user-me" }]);
  });
});
