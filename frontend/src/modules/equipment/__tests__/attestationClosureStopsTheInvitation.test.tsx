/**
 * regression: the public attestation page used to offer its
 * buttons on a link it already knew would refuse them — the equipment
 * returned, the campaign cancelled, the token expired. The GET now
 * carries ``closed_reason``, and the page tells it instead of inviting a
 * click that can only 409.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import AttestationPublicPage from "@/modules/equipment/pages/AttestationPublicPage";

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useParams: () => ({ token: "tok-1" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

function pendingResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: "resp-1",
    campaign_id: "camp-1",
    assignment_id: "asg-1",
    assignee_email: "anna@example.com",
    assignee_name: "Anna Kowalska",
    item_name: "Laptop A",
    serial_number: "SN-A",
    items: [
      {
        id: "item-1",
        response_id: "resp-1",
        assignment_id: "asg-1",
        item_id: "it-1",
        item_name: "Laptop A",
        serial_number: "SN-A",
        status: "PENDING" as const,
        dispute_type: null,
        dispute_reason: null,
      },
    ],
    status: "PENDING",
    responded_at: null,
    dispute_reason: null,
    dispute_type: null,
    email_sent_at: null,
    reminder_sent_at: null,
    created_at: "2026-08-01T00:00:00Z",
    closed_reason: null,
    ...overrides,
  };
}

function serve(body: Record<string, unknown>) {
  server.use(
    http.get("/public/attestation/tok-1", () => HttpResponse.json(body)),
  );
}

const confirmButton = () =>
  screen.queryByRole("button", { name: "I have this asset" });
const reportButton = () =>
  screen.queryByRole("button", { name: "Report Issue" });

describe("a closed attestation link says so instead of inviting a click", () => {
  it("a cancelled campaign shows the closure, not the buttons", async () => {
    serve(pendingResponse({ closed_reason: "campaign_closed" }));

    render(<AttestationPublicPage />);

    expect(await screen.findByText("Attestation Closed")).toBeInTheDocument();
    expect(
      screen.getByText(/your confirmation can no longer be saved/i),
    ).toBeInTheDocument();
    expect(confirmButton()).not.toBeInTheDocument();
    expect(reportButton()).not.toBeInTheDocument();
  });

  it("a returned assignment shows the closure, not the buttons", async () => {
    serve(pendingResponse({ closed_reason: "assignment_already_returned" }));

    render(<AttestationPublicPage />);

    expect(await screen.findByText("Already Returned")).toBeInTheDocument();
    expect(
      screen.getByText(/already been confirmed as returned/i),
    ).toBeInTheDocument();
    expect(confirmButton()).not.toBeInTheDocument();
    expect(reportButton()).not.toBeInTheDocument();
  });

  it("an expired token shows the expiry, not the buttons", async () => {
    serve(pendingResponse({ closed_reason: "expired" }));

    render(<AttestationPublicPage />);

    expect(await screen.findByText("Link Expired")).toBeInTheDocument();
    expect(confirmButton()).not.toBeInTheDocument();
    expect(reportButton()).not.toBeInTheDocument();
  });

  it("an answer already given still wins over a later closure", async () => {
    serve(
      pendingResponse({
        status: "CONFIRMED",
        responded_at: "2026-08-02T00:00:00Z",
        closed_reason: "campaign_closed",
      }),
    );

    render(<AttestationPublicPage />);

    expect(await screen.findByText("Confirmed")).toBeInTheDocument();
    expect(screen.queryByText("Campaign Closed")).not.toBeInTheDocument();
  });

  it("an open link keeps the buttons", async () => {
    serve(pendingResponse());

    render(<AttestationPublicPage />);

    expect(
      await screen.findByRole("button", { name: "I have this asset" }),
    ).toBeInTheDocument();
    expect(reportButton()).toBeInTheDocument();
  });
});
