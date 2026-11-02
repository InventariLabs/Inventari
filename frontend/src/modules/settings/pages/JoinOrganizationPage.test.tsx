import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import JoinOrganizationPage from "./JoinOrganizationPage";
import { logger } from "@/utils/logger";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import userEvent from "@testing-library/user-event";

/**
 * The join link is the one door into an existing organization for somebody
 * without an account, so what this page does with a dead code decides
 * whether the visitor ends up in the inviting organization or — the trap —
 * in one they minted themselves from /register.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const INVALID_LINK =
  "This invitation link is missing its invite code. Ask for a new invitation and open the full link.";

function renderJoin(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/join" element={<JoinOrganizationPage />} />
          <Route path="/join/:token" element={<JoinOrganizationPage />} />
          <Route
            path="/register"
            element={<div data-testid="register-landing" />}
          />
          <Route path="/" element={<div>home-stub</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JoinOrganizationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ isAuthenticated: false, isLoading: false });
  });

  it("shows the written message instead of the silent login redirect when the link carries no code", () => {
    // No code at all is a malformed link; redirecting it home used to end
    // signed-out readers on /login with no word about the link they came by.
    renderJoin("/join");

    expect(screen.getByText(INVALID_LINK)).toBeVisible();
    expect(screen.queryByText("home-stub")).not.toBeInTheDocument();
  });

  it("keeps a link that carries a live code out of the invalid-link card", async () => {
    server.use(
      http.get("/public/invitation/INVITE-123", () =>
        HttpResponse.json({ valid: true }),
      ),
    );

    renderJoin("/join?code=INVITE-123");

    // A code that checks out live never reads as an invalid link — and a
    // signed-out reader with a working invite is on their way to register.
    expect(screen.queryByText(INVALID_LINK)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("register-landing")).toBeInTheDocument();
    });
  });

  it("tells the reader a dead path-form link is dead instead of redirecting", async () => {
    // A dead link such as /join/QACFAKETOKEN123 used to fall through the
    // catch-all to "/" and, signed out, silently on to /login — where
    // registering mints an organization of one's own instead of joining.
    server.use(
      http.get("/public/invitation/QACFAKETOKEN123", () =>
        HttpResponse.json(
          { detail: "Invalid organization invitation" },
          { status: 404 },
        ),
      ),
    );

    renderJoin("/join/QACFAKETOKEN123");

    expect(
      await screen.findByText(
        "This invitation link is invalid or has already expired.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Link Not Found")).toBeInTheDocument();
    // Who issues the new link is named with the refusal, as on the public
    // attestation page.
    expect(
      screen.getByText(
        "Ask whoever sent you the invitation for a fresh link — the person who manages your organization.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps a live path-form link working: on to registration with the code", async () => {
    server.use(
      http.get("/public/invitation/GOODCODE", () =>
        HttpResponse.json({ valid: true }),
      ),
    );

    renderJoin("/join/GOODCODE");

    await waitFor(() => {
      expect(screen.getByTestId("register-landing")).toBeInTheDocument();
    });
  });

  it("still reads the code from the query the invitation mail sends", async () => {
    server.use(
      http.get("/public/invitation/QUERYCODE1", () =>
        HttpResponse.json({ valid: true }),
      ),
    );

    renderJoin("/join?code=QUERYCODE1");

    await waitFor(() => {
      expect(screen.getByTestId("register-landing")).toBeInTheDocument();
    });
  });

  it("answers a signed-in 404 with the card and exactly one join attempt", async () => {
    useAuthStore.setState({ isAuthenticated: true, isLoading: false });
    // The page logs the refusal before it classifies it; the log line is not
    // what this test is about, and the console gate is.
    vi.spyOn(logger, "error").mockImplementation(() => {});
    let joinAttempts = 0;
    server.use(
      http.post("/api/v1/organizations/join", async () => {
        joinAttempts += 1;
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json(
          { detail: "Organization not found" },
          { status: 404 },
        );
      }),
    );

    renderJoin("/join?code=STALECOD");

    expect(await screen.findByText("Link Not Found")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Ask whoever sent you the invitation for a fresh link — the person who manages your organization.",
      ),
    ).toBeInTheDocument();
    // The refusal must latch. A guard that re-arms on every failed mutation
    // fired this POST in an unbounded loop behind the card — 800+ requests
    // in ~15 s measured in the browser — until the endpoint's rate limit locked
    // the reader out for an hour. The card shows, but only ever one POST.
    // The handler delay is what makes the loop observable here: without it
    // pending and refused states land in one React commit, no effect
    // dependency ever changes, and the storm this test exists for does not
    // exist in this environment — a green that proved nothing.
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(joinAttempts).toBe(1);
  });

  it("tells a signed-in stranger the live link is for another address and offers to sign out", async () => {
    useAuthStore.setState({ isAuthenticated: true, isLoading: false });
    vi.spyOn(logger, "error").mockImplementation(() => {});
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ logout });
    server.use(
      http.post("/api/v1/organizations/join", () =>
        HttpResponse.json(
          {
            detail: {
              code: "INVITATION_OTHER_ADDRESS",
              message:
                "This invitation was issued for a different email address",
            },
          },
          { status: 409 },
        ),
      ),
    );

    renderJoin("/join?code=LIVECODE");

    expect(
      await screen.findByText("This link is for another address"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Link Not Found")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));
    expect(logout).toHaveBeenCalled();
  });

  it("answers a failed join with one message and a retry, not the bare title twice", async () => {
    useAuthStore.setState({ isAuthenticated: true, isLoading: false });
    vi.spyOn(logger, "error").mockImplementation(() => {});
    server.use(
      http.post("/api/v1/organizations/join", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderJoin("/join?code=LIVECODE");

    expect(
      await screen.findByText(/cannot tell whether the invitation was used/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("An error occurred")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("spends a code on one attempt even under StrictMode's double effect-invoke", async () => {
    // The app mounts inside React.StrictMode (main.tsx), which invokes the
    // effect twice per mount in the same commit — before any state has
    // moved. A latch read from mutation state sees an idle mutation on both
    // invocations and fires two POSTs: the first joins, the second is
    // judged dead, and the card then calls a working link invalid — measured
    // in review on a live code (POST join 404 then 200, dead-link card on
    // screen after the success). RTL does not wrap in StrictMode on its own,
    // so the count-of-one assertions above are green over a count the app
    // never produces; this render does wrap, and the ref latch has to hold
    // under it.
    useAuthStore.setState({ isAuthenticated: true, isLoading: false });
    vi.spyOn(logger, "error").mockImplementation(() => {});
    let joinAttempts = 0;
    server.use(
      http.post("/api/v1/organizations/join", async () => {
        joinAttempts += 1;
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json(
          { detail: "Organization not found" },
          { status: 404 },
        );
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/join?code=STRICTCODE1"]}>
            <Routes>
              <Route path="/join" element={<JoinOrganizationPage />} />
              <Route path="/join/:token" element={<JoinOrganizationPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>,
    );

    expect(await screen.findByText("Link Not Found")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(joinAttempts).toBe(1);
  });
  it("says the reader is already a member when the link is for their own organization", async () => {
    // The endpoint answers 200 either way (nothing is written and the code
    // stays unspent for a member), so the page compares the organization it
    // gets back with the one the reader already had.
    useAuthStore.setState({ isAuthenticated: true, isLoading: false });
    const own = { id: "org-own", name: "Own Org" };
    server.use(
      http.get("/api/v1/organizations/my", () => HttpResponse.json(own)),
      http.post("/api/v1/organizations/join", () => HttpResponse.json(own)),
    );

    renderJoin("/join?code=OWNCODE1");

    expect(await screen.findByText("home-stub")).toBeInTheDocument();
    expect(toast.info).toHaveBeenCalledWith(
      "You are already a member of this organization",
    );
    expect(toast.success).not.toHaveBeenCalled();
  });
});
