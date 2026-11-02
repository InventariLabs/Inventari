/**
 * regression: a failed confirm/dispute on the public attestation page
 * must say so on screen. The visitor arrives from an email link with no
 * account, so a silent failure reads as "confirmed" and nobody ever sees
 * the console error.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import AttestationPublicPage from "@/modules/equipment/pages/AttestationPublicPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useParams: () => ({ token: "tok-1" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

const pendingResponse = {
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
};

describe(" attestation failure has an addressee", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
    server.use(
      http.get("/public/attestation/tok-1", () =>
        HttpResponse.json(pendingResponse),
      ),
    );
  });

  it("a failed confirm tells the visitor why", async () => {
    server.use(
      http.post("/public/attestation/tok-1/confirm", () =>
        HttpResponse.json(
          { detail: "Attestation link has expired" },
          { status: 400 },
        ),
      ),
    );

    render(<AttestationPublicPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "I have this asset" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Yes, I have it" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Attestation link has expired"),
    );
    // Not resolved: the action stays on offer instead of a silent "confirmed".
    expect(
      screen.getByRole("button", { name: "Yes, I have it" }),
    ).toBeInTheDocument();
  });

  it("a failed dispute falls back to a visible message", async () => {
    server.use(
      http.post("/public/attestation/tok-1/dispute", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    render(<AttestationPublicPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Report Issue" }),
    );
    fireEvent.click(screen.getByRole("combobox", { name: /issue type/i }));
    fireEvent.click(await screen.findByRole("option", { name: /^Other$/ }));
    fireEvent.change(
      screen.getByPlaceholderText("Please describe the issue in detail…"),
      { target: { value: "The laptop is not with me anymore" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit Report" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Something went wrong. Please try again — if it keeps failing, ask whoever sent you this link for a new one.",
      ),
    );
  });

  it("a server failure is not reported as a dead link", async () => {
    server.use(
      http.get("/public/attestation/tok-1", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    render(<AttestationPublicPage />);

    expect(
      await screen.findByText("Could not load this page"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Link Not Found")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("a 404 is still a dead link", async () => {
    server.use(
      http.get("/public/attestation/tok-1", () =>
        HttpResponse.json({ detail: "nope" }, { status: 404 }),
      ),
    );
    render(<AttestationPublicPage />);

    expect(await screen.findByText("Link Not Found")).toBeInTheDocument();
  });
});
