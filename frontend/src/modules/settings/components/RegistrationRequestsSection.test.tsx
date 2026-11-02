import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { toast } from "sonner";
import { MemoryRouter, useNavigate } from "react-router-dom";
import RegistrationRequestsSection from "./RegistrationRequestsSection";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));
const toastMock = vi.mocked(toast);

const pendingRequest = {
  id: "req-1",
  email: "new@example.com",
  full_name: "New User",
  preferred_language: "pl",
  created_at: "2026-08-20T10:00:00Z",
  accepted_at: null,
  rejected_at: null,
  is_rejected: false,
};

function HashLink() {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate("/settings#registration-requests")}>
      go
    </button>
  );
}

function renderSection(withHashLink = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings"]}>
        <RegistrationRequestsSection />
        {withHashLink && <HashLink />}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RegistrationRequestsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says the requests could not be loaded instead of hiding the section", async () => {
    server.use(
      http.get(
        "*/auth/registration-requests",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderSection();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing when the queue is empty", async () => {
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    const { container } = renderSection();

    await waitFor(() =>
      expect(screen.queryByText("Registration requests")).toBeNull(),
    );
    expect(container.firstChild).toBeNull();
  });

  it("lists a pending request and approves it, emailing the link", async () => {
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([pendingRequest])),
      ),
      http.post("*/auth/registration-requests/req-1/approve", () =>
        HttpResponse.json({
          message: "ok",
          registration_token: "tok",
          registration_link: "/register?token=tok",
          email_sent: true,
        }),
      ),
    );
    renderSection();

    await screen.findByText("New User");
    await userEvent.click(
      screen.getByRole("button", { name: "Approve New User" }),
    );

    await waitFor(() =>
      expect(toastMock.success).toHaveBeenCalledWith(
        expect.stringMatching(/approved/i),
      ),
    );
    // The email went out — no manual link fallback.
    expect(screen.queryByText(/register\?token/)).toBeNull();
  });

  it("shows the registration link when no email could be sent", async () => {
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([pendingRequest])),
      ),
      http.post("*/auth/registration-requests/req-1/approve", () =>
        HttpResponse.json({
          message: "ok",
          registration_token: "tok",
          registration_link: "/register?token=tok",
          email_sent: false,
        }),
      ),
    );
    renderSection();

    await screen.findByText("new@example.com");
    await userEvent.click(
      screen.getByRole("button", { name: "Approve New User" }),
    );

    // Without SMTP the link is the only thing that reaches the user.
    expect(
      await screen.findByText(/http:\/\/localhost.*\/register\?token=tok/),
    ).toBeInTheDocument();
  });

  it("keeps the link on screen after the last request is approved", async () => {
    let approved = false;
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage(approved ? [] : [pendingRequest])),
      ),
      http.post("*/auth/registration-requests/req-1/approve", () => {
        approved = true;
        return HttpResponse.json({
          message: "ok",
          registration_token: "tok",
          registration_link: "/register?token=tok",
          email_sent: false,
        });
      }),
    );
    renderSection();

    await screen.findByText("New User");
    await userEvent.click(
      screen.getByRole("button", { name: "Approve New User" }),
    );

    // The list refetches empty once the request is approved; the one copy of
    // the link must not go with it.
    await waitFor(() => expect(approved).toBe(true));
    await waitFor(() =>
      expect(screen.queryByText("New User")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/http:\/\/localhost.*\/register\?token=tok/),
    ).toBeInTheDocument();
  });

  it("rejects a request", async () => {
    let rejectedId: string | null = null;
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([pendingRequest])),
      ),
      http.post("*/auth/registration-requests/:id/reject", ({ params }) => {
        rejectedId = params.id as string;
        return HttpResponse.json({ message: "ok" });
      }),
    );
    renderSection();

    await screen.findByText("New User");
    await userEvent.click(
      screen.getByRole("button", { name: "Reject New User" }),
    );

    // The click only asks; nothing is sent until the dialog is confirmed.
    const dialog = await screen.findByRole("alertdialog");
    expect(rejectedId).toBeNull();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Reject" }),
    );

    await waitFor(() => expect(rejectedId).toBe("req-1"));
    expect(toastMock.success).toHaveBeenCalledWith(
      expect.stringMatching(/rejected/i),
    );
  });

  it("marks an approved request and offers a new link instead of a second approval", async () => {
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(
          onePage([{ ...pendingRequest, accepted_at: "2026-08-20T11:00:00Z" }]),
        ),
      ),
    );
    renderSection();

    await screen.findByText("New User");
    expect(
      screen.getByText("Approved — waiting for registration"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New link for New User" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve New User" }),
    ).toBeNull();
  });

  it("scrolls to the section when only the hash changes", async () => {
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([pendingRequest])),
      ),
    );
    renderSection(true);

    await screen.findByText("New User");
    expect(scroll).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
    // Same hash again (the notification clicked a second time) scrolls again.
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(2));
  });
});
