import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";

import AttestationPublicPage from "./AttestationPublicPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useParams: () => ({ token: "tok-ok" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

const pending = {
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

beforeEach(() => {
  server.use(
    http.get("/public/attestation/tok-ok", () => HttpResponse.json(pending)),
  );
});

/**
 * The public attestation page answers once and then shows the answer it
 * saved. The failures caught: a confirmation or report that went through
 * while the page keeps offering the buttons (a second answer would follow),
 * a report sent without the issue type or the reason chosen, and a Cancel
 * that sends one.
 */
describe("AttestationPublicPage — the answer it saves", () => {
  it("shows the confirmation once the server has it", async () => {
    server.use(
      http.post("/public/attestation/tok-ok/confirm", () =>
        HttpResponse.json({ ...pending, status: "CONFIRMED" }),
      ),
    );
    render(<AttestationPublicPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "I have this asset" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Yes, I have it" }),
    );

    expect(await screen.findByText("Confirmed")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "I have this asset" }),
    ).not.toBeInTheDocument();
  });

  it("sends the report with its reason and shows it as reported", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post("/public/attestation/tok-ok/dispute", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ...pending, status: "DISPUTED" });
      }),
    );
    render(<AttestationPublicPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Report Issue" }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: /Issue Type/ }));
    await userEvent.click(
      await screen.findByRole("option", { name: /^Damaged/ }),
    );
    fireEvent.change(
      screen.getByPlaceholderText("Please describe the issue in detail…"),
      { target: { value: "The screen is cracked" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit Report" }));

    expect(await screen.findByText("Issue Reported")).toBeInTheDocument();
    expect(body).toMatchObject({
      dispute_type: "DAMAGED",
      reason: "The screen is cracked",
    });
    expect(
      screen.queryByRole("button", { name: "Submit Report" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the other assets open after a report on one of several", async () => {
    const second = {
      ...pending.items[0],
      id: "item-2",
      assignment_id: "asg-2",
      item_id: "it-2",
      item_name: "Laptop B",
      serial_number: "SN-B",
    };
    const reported = {
      ...pending,
      assignment_id: null,
      items: [
        {
          ...pending.items[0],
          status: "DISPUTED" as const,
          dispute_type: "DAMAGED",
          dispute_reason: "Screen cracked",
        },
        second,
      ],
    };
    server.use(
      http.post("/public/attestation/tok-ok/dispute", () =>
        HttpResponse.json(reported),
      ),
    );
    render(<AttestationPublicPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Report Issue" }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: /Issue Type/ }));
    await userEvent.click(
      await screen.findByRole("option", { name: /^Damaged/ }),
    );
    fireEvent.change(
      screen.getByPlaceholderText("Please describe the issue in detail…"),
      { target: { value: "Screen cracked" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit Report" }));

    expect(
      await screen.findByText(/Your report is saved\. Assets you have not/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Issue Reported")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "I have this asset" }),
    ).toBeInTheDocument();
  });

  it("closes the report on Cancel and offers the two answers again", async () => {
    const reported = vi.fn();
    server.use(
      http.post("/public/attestation/tok-ok/dispute", () => {
        reported();
        return HttpResponse.json(pending);
      }),
    );
    render(<AttestationPublicPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Report Issue" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      screen.getByRole("button", { name: "I have this asset" }),
    ).toBeInTheDocument();
    expect(reported).not.toHaveBeenCalled();
  });

  it("asks again after a server failure and shows the page once it answers", async () => {
    let attempts = 0;
    server.use(
      http.get("/public/attestation/tok-ok", () => {
        attempts++;
        return attempts === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 503 })
          : HttpResponse.json(pending);
      }),
    );
    render(<AttestationPublicPage />);

    fireEvent.click(await screen.findByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "I have this asset" }),
      ).toBeInTheDocument(),
    );
  });

  it("says a 429 is a pause, not a dead link, and lets the visitor retry", async () => {
    let attempts = 0;
    server.use(
      http.get("/public/attestation/tok-ok", () => {
        attempts++;
        return attempts === 1
          ? HttpResponse.json(
              {
                detail: {
                  code: "RATE_LIMIT_EXCEEDED",
                  message: "Too many requests. Try again later.",
                  limit: "30 per 1 minute",
                },
              },
              { status: 429 },
            )
          : HttpResponse.json(pending);
      }),
    );
    render(<AttestationPublicPage />);

    expect(
      await screen.findByText("Too many requests. Try again later."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Link Not Found")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "I have this asset" }),
      ).toBeInTheDocument(),
    );
  });
});
