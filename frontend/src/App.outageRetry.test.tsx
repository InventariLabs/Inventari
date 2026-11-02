import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import App from "./App";

vi.mock("html5-qrcode", () => {
  // A class on purpose: the hook constructs this with `new`, and vitest 5
  // refuses a mock built from an arrow implementation — the construction
  // throws into the hook's catch and prints "Camera start error:".
  class MockHtml5Qrcode {
    isScanning = true;
    start() {
      return Promise.resolve();
    }
    stop() {
      return Promise.resolve();
    }
    pause() {
      return Promise.resolve();
    }
    resume() {
      return Promise.resolve();
    }
    clear() {}
  }
  return {
    Html5Qrcode: MockHtml5Qrcode,
    Html5QrcodeSupportedFormats: {
      QR_CODE: 0,
      EAN_13: 1,
      EAN_8: 2,
      UPC_A: 3,
      UPC_E: 4,
      CODE_128: 5,
      CODE_39: 6,
    },
  };
});

/**
 * The retry on the outage screen reports itself where it was pressed.
 *
 * Measured before the fix, in a Polish interface: the reader answered "the
 * session is still open" by pressing Try again, and the whole screen — message
 * and button with it — was replaced by the loading screen for as long as the
 * ask lasted. The button's busy state existed but could never be seen, because
 * the gate above it unmounted the screen it belonged to.
 */
describe("the retry on the outage screen", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    tokenStore.set("test-token");
    useAuthStore.setState({
      user: null,
      isAuthenticated: true,
      isLoading: false,
      authUnavailable: false,
    });
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    server.use(
      http.get("*/api/v1/modules/my", () => HttpResponse.json(["core"])),
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({ applied: false, focus_module: null }),
      ),
    );
  });

  it("keeps the outage on screen and the button busy while it runs", async () => {
    // Phase one: the session check gets no answer at all.
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.error()));

    // `App` mounts its own data router, so the address is handed to it as
    // the place to start rather than to a router wrapper — a second
    // `<Router>` is an invariant violation, and this test's job is the
    // outage screen, not the router.
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={["/"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    const outage = await screen.findByRole("alert");
    expect(outage).toHaveTextContent("Cannot reach the server");

    // Phase two: the reader presses Try again, and the ask hangs unanswered.
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("*/api/v1/auth/me", async () => {
        await gate;
        return HttpResponse.json({
          id: "1",
          email: "test@example.com",
          full_name: "Test User",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      }),
    );

    const retry = screen.getByRole("button", { name: "Try again" });
    retry.click();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled();
    });
    // The message the reader is answering is still there, and the boot
    // spinner has not taken the screen.
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Cannot reach the server",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    release();
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });
});

/**
 * A boot with no token and a server that does not answer leaves the store in
 * "not authenticated" and "outage" at the same time: the refresh probe fails
 * unanswered, and nobody's credentials were refuted by anyone. The route gate
 * has to read the outage first.
 *
 * That pair is the one the two conditions can disagree about, and nothing
 * measured it: the retry test above runs with a signed-in reader, where the
 * sign-in redirect would never fire anyway. Swap the two conditions and the
 * reader the outage screen exists for — whose session could not even be asked
 * about — lands on a form that fails for the very same reason. Measured, not
 * assumed: with `!isAuthenticated` above `authUnavailable` this test fails
 * because the sign-in form arrives instead of the alert.
 */
describe("a reader the server could not be asked about", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    tokenStore.clear();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      authUnavailable: true,
    });
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    server.use(
      // The boot probe gets no answer, so the store keeps the "outage"
      // reading — a refusal here would legitimately clear it and send the
      // reader to the sign-in form.
      http.post("*/api/v1/auth/refresh", () => HttpResponse.error()),
      http.get("*/api/v1/modules/my", () => HttpResponse.json(["core"])),
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({ applied: false, focus_module: null }),
      ),
    );
  });

  it("stays on the outage screen instead of the sign-in form", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={["/"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    const outage = await screen.findByRole("alert");
    expect(outage).toHaveTextContent("Cannot reach the server");

    // The boot probe's own failure has settled; the reader is still here and
    // the sign-in form never arrived.
    await waitFor(() => {
      expect(useAuthStore.getState().isLoading).toBe(false);
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Cannot reach the server",
    );
    expect(
      screen.queryByText("Sign in to your account"),
    ).not.toBeInTheDocument();
  });
});
