import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";
import { BrowserRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LoginPage from "./LoginPage";
import { useAuthStore } from "../store/authStore";
import type { AuthState } from "../store/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe("LoginPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: true, demo_inbox_url: null }),
      ),
    );
    useAuthStore.setState({ signOutReason: null });
  });

  const renderLogin = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <LoginPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

  it("should render login form", () => {
    renderLogin();

    expect(screen.getByLabelText(/Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Sign in/i }),
    ).toBeInTheDocument();
  });

  it("carries exactly one first-level heading tag", () => {
    // A DOM count, and only that: jsdom applies no CSS, so it cannot say
    // which heading a viewport actually shows — tests/e2e/auth-heading.spec.ts
    // measures the accessibility tree at phone and desktop width. What this
    // one pins is the markup contract: one h1 tag, and the desktop
    // panel's brand carries the heading role instead of a second tag — two
    // level-1 roles in the tree here, exactly one of them visible anywhere
    // real.
    const { container } = renderLogin();

    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(container.querySelector("h1")).toHaveTextContent("Inventari");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(2);
  });

  it("fills in the address a new account was just made with", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            { pathname: "/login", state: { email: "owner@example.com" } },
          ]}
        >
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/Email/i)).toHaveValue("owner@example.com");
  });

  it("should call login and navigate on success", async () => {
    const loginMock = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      login: loginMock as unknown as AuthState["login"],
    });

    renderLogin();

    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/Password/i), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign in/i }));

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith("test@example.com", "password");
    });
  });

  const rejectWith = (status: number) => {
    const error = new AxiosError("failed", "ERR_BAD_REQUEST", undefined, null, {
      status,
      statusText: "",
      data: {},
      headers: new AxiosHeaders(),
      config: { headers: new AxiosHeaders() },
    });
    useAuthStore.setState({
      login: vi.fn().mockRejectedValue(error) as unknown as AuthState["login"],
    });
  };

  const submitLogin = () => {
    renderLogin();
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "wrong@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/Password/i), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign in/i }));
  };

  it("should show error toast on rejected credentials", async () => {
    rejectWith(401);
    const { toast } = await import("sonner");

    submitLogin();

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Invalid email or password");
    });
  });

  it("does not call a rate-limited attempt a wrong password", async () => {
    // The catch-all used to send a reader blocked by the limiter off to
    // change a password that was correct all along.
    rejectWith(429);
    const { toast } = await import("sonner");

    submitLogin();

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Too many sign-in attempts"),
      );
    });
    expect(toast.error).not.toHaveBeenCalledWith("Invalid email or password");
  });

  it("gives the inline links a 44px touch target on a phone", async () => {
    renderLogin();

    const register = await screen.findByRole("link", {
      name: /request access/i,
    });
    expect(register).toHaveClass("min-h-11");
    const forgot = document.querySelector('a[href="/forgot-password"]');
    expect(forgot).toHaveClass("min-h-11");
  });

  it("links to the access request on an initialized installation", async () => {
    renderLogin();

    expect(
      await screen.findByRole("link", { name: /request access/i }),
    ).toHaveAttribute("href", "/register");
  });

  it("links to the privacy page from its footer", async () => {
    renderLogin();

    const privacy = await screen.findByRole("link", { name: "Privacy" });
    expect(privacy).toHaveAttribute("href", "/privacy");
    expect(privacy).toHaveClass("min-h-11");
  });

  it("names the first-account bootstrap on an empty installation", async () => {
    // /register offers the "Create new account" form there, so the login
    // page must not promise a "request" the destination does not offer.
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: false, demo_inbox_url: null }),
      ),
    );

    renderLogin();

    expect(
      await screen.findByRole("link", { name: /create new account/i }),
    ).toHaveAttribute("href", "/register");
    expect(screen.queryByRole("link", { name: /request access/i })).toBeNull();
  });

  it("points a demo visitor at the public inbox", async () => {
    // The demo sends no real mail; the inbox beside it is where a visitor
    // reads the purchase order or invitation that would have gone out.
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({
          is_initialized: true,
          demo_inbox_url: "https://demo.test/mailpit/",
        }),
      ),
    );

    renderLogin();

    const link = await screen.findByRole("link", {
      name: /open the demo inbox/i,
    });
    expect(link).toHaveAttribute("href", "https://demo.test/mailpit/");
    expect(screen.getByText(/public demo/i)).toBeInTheDocument();
  });

  it("shows no inbox notice on an ordinary install", async () => {
    renderLogin();

    expect(
      await screen.findByRole("link", { name: /request access/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /demo inbox/i })).toBeNull();
    expect(screen.queryByText(/public demo/i)).toBeNull();
  });

  it("says the password was changed when that is why the session ended", () => {
    useAuthStore.setState({ signOutReason: "passwordChanged" });
    renderLogin();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Your password has been changed. Sign in with the new one",
    );
  });

  it("says nothing about a password on an ordinary sign-in", () => {
    renderLogin();

    expect(screen.queryByText(/password has been changed/)).toBeNull();
  });
});

describe("LoginPage on the public demo", () => {
  // The store's own implementation, kept before any test replaces it.
  const realOpenDemoSandbox = useAuthStore.getState().openDemoSandbox;
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    useAuthStore.setState({
      isAuthenticated: false,
      openDemoSandbox: realOpenDemoSandbox,
    });
  });

  // Where the page sends the visitor, read off the screen they land on.
  const renderOn = (isDemo: boolean) => {
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({
          is_initialized: true,
          is_demo: isDemo,
          demo_inbox_url: null,
        }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/login"]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/launcher" element={<p>landed on the launcher</p>} />
            <Route path="/" element={<p>landed on the home route</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  };

  it("offers no demo outside one", async () => {
    renderOn(false);

    await screen.findByRole("button", { name: /Sign in/i });
    expect(screen.queryByRole("button", { name: "Try the demo" })).toBeNull();
  });

  it("links the demo's way in to the privacy page", async () => {
    renderOn(true);

    await screen.findByRole("button", { name: "Try the demo" });
    expect(screen.getByRole("link", { name: "Privacy" })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });

  it("offers no request-access link to a visitor", async () => {
    // A request is stored where only an instance superuser could read it,
    // and a demo has no superuser: the visitor would be told it had been
    // submitted and wait for an answer that cannot come. The one-click
    // sandbox is the way in.
    renderOn(true);

    await screen.findByRole("button", { name: "Try the demo" });
    expect(screen.queryByRole("link", { name: /request access/i })).toBeNull();
  });

  // StrictMode replays every effect in development; the visitor must land in
  // the same place the production build sends them, not wherever the replay
  // finds the page's memory already cleared.
  it.each([
    ["in the production build", false],
    ["under development StrictMode", true],
  ])(
    "opens the visitor's own organization on the launcher in one click %s",
    async (_where, strict) => {
      const openDemoSandbox = vi.fn().mockImplementation(async () => {
        useAuthStore.setState({ isAuthenticated: true });
      });
      useAuthStore.setState({
        openDemoSandbox:
          openDemoSandbox as unknown as AuthState["openDemoSandbox"],
      });
      server.use(
        http.get("/api/v1/auth/init-status", () =>
          HttpResponse.json({
            is_initialized: true,
            is_demo: true,
            demo_inbox_url: null,
          }),
        ),
      );
      // What App does on sign-in: it holds a spinner while the organization's
      // modules register, then builds the router again — so the sign-in page
      // that sends the visitor on is a new instance, not the one clicked.
      const Shell = () => {
        const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
        return (
          <MemoryRouter
            key={isAuthenticated ? "signed-in" : "signed-out"}
            initialEntries={["/login"]}
          >
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/launcher" element={<p>landed on the launcher</p>} />
              <Route path="/" element={<p>landed on the home route</p>} />
            </Routes>
          </MemoryRouter>
        );
      };
      const app = (
        <QueryClientProvider client={queryClient}>
          <Shell />
        </QueryClientProvider>
      );
      render(strict ? <StrictMode>{app}</StrictMode> : app);

      fireEvent.click(
        await screen.findByRole("button", { name: "Try the demo" }),
      );

      expect(
        await screen.findByText("landed on the launcher"),
      ).toBeInTheDocument();
      expect(screen.queryByText("landed on the home route")).toBeNull();
      expect(openDemoSandbox).toHaveBeenCalledTimes(1);
    },
  );

  it("says plainly that the day's copies are gone, and stays on the page", async () => {
    server.use(
      http.post("/api/v1/demo/sandbox", () =>
        HttpResponse.json(
          {
            detail: {
              code: "DEMO_SANDBOX_CAP_REACHED",
              message: "The demo has handed out all its copies for today.",
            },
          },
          { status: 429 },
        ),
      ),
    );
    renderOn(true);

    fireEvent.click(
      await screen.findByRole("button", { name: "Try the demo" }),
    );

    expect(
      await screen.findByText(/handed out all its copies for today/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try the demo" })).toBeEnabled();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("tells a visitor to wait a minute while new copies are prepared", async () => {
    server.use(
      http.post("/api/v1/demo/sandbox", () =>
        HttpResponse.json(
          { detail: { code: "DEMO_SANDBOX_POOL_EMPTY", message: "x" } },
          { status: 503 },
        ),
      ),
    );
    renderOn(true);

    fireEvent.click(
      await screen.findByRole("button", { name: "Try the demo" }),
    );

    expect(
      await screen.findByText(/Try again in a minute/),
    ).toBeInTheDocument();
  });

  describe("continuing to the address asked for", () => {
    const signInFrom = async (from: unknown) => {
      useAuthStore.setState({
        isAuthenticated: false,
        login: vi
          .fn()
          .mockResolvedValue(undefined) as unknown as AuthState["login"],
      });
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[{ pathname: "/login", state: { from } }]}
          >
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/s/*" element={<p>landed on the label</p>} />
              <Route path="/" element={<p>landed on the home route</p>} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      );
      fireEvent.change(await screen.findByLabelText(/Email/i), {
        target: { value: "a@b.co" },
      });
      fireEvent.change(screen.getByLabelText(/Password/i), {
        target: { value: "secret-pass" },
      });
      fireEvent.click(screen.getByRole("button", { name: /Sign in/i }));
      await act(async () => {
        useAuthStore.setState({ isAuthenticated: true });
      });
    };

    it("opens the label the reader came for", async () => {
      await signInFrom("/s/STM-0001");
      expect(
        await screen.findByText("landed on the label"),
      ).toBeInTheDocument();
    });

    it("keeps the demo launcher ahead of the address asked for", async () => {
      const openDemoSandbox = vi.fn().mockImplementation(async () => {
        useAuthStore.setState({ isAuthenticated: true });
      });
      useAuthStore.setState({
        isAuthenticated: false,
        openDemoSandbox:
          openDemoSandbox as unknown as AuthState["openDemoSandbox"],
      });
      server.use(
        http.get("/api/v1/auth/init-status", () =>
          HttpResponse.json({
            is_initialized: true,
            is_demo: true,
            demo_inbox_url: null,
          }),
        ),
      );
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[{ pathname: "/login", state: { from: "/s/X" } }]}
          >
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/s/*" element={<p>landed on the label</p>} />
              <Route path="/launcher" element={<p>landed on the launcher</p>} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      );
      fireEvent.click(
        await screen.findByRole("button", { name: "Try the demo" }),
      );
      expect(
        await screen.findByText("landed on the launcher"),
      ).toBeInTheDocument();
    });

    it("ignores an address that leaves the app", async () => {
      await signInFrom("//evil.example/s/x");
      expect(
        await screen.findByText("landed on the home route"),
      ).toBeInTheDocument();
    });
  });
});
