import { render, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import { labelsApi } from "@/lib/api/labels";
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

// The camera is idle in tests; the ?code= URL param drives the same handler.
vi.mock("@/lib/api/labels", () => ({
  labelsApi: {
    scan: vi.fn(),
  },
}));

// Shorter than the test's own limit (`testTimeout` in vite.config.ts), so a
// redirect that really fails reports the spy's "called 0 times" and not
// "Test timed out": equal windows let the test-level timer win the race.
const ROUTE_LOADED_WITHIN = 12000;

// A printed QR label carries {base_url}/scan?code=<short_code> (the backend
// builds this URL in label_print_service). The legacy alias used to drop the
// query string in the redirect, so a scanned sticker opened an empty scanner
// — the code the app itself printed was unreachable from the one address the
// app printed it under.
describe("legacy /scan alias", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    // A token in the store keeps checkAuth() off the refresh endpoint, whose
    // default mock answers 401 — an in-memory token is the signed-in shortcut.
    tokenStore.set("test-token");
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: [],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    // The inventory module owns /inventory/scan; without it the alias lands
    // on a 404 before the scanner ever mounts.
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "inventory"]),
      ),
    );
  });

  it("hands the ?code= query parameter to the scanner page", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "unassigned",
      label_code: "STM-0001",
      message_key: "scan:result.labelReady",
      action: "show_quick_add",
    });

    // `App` mounts its own data router, so the address goes on the history
    // rather than to a router wrapper — a second `<Router>` is an invariant
    // violation, and this test's job is the redirect, not the router.
    // `App` mounts its own data router, so the address is handed to it as
    // the place to start rather than to a router wrapper — a second
    // `<Router>` is an invariant violation, and this test's job is the
    // redirect, not the router. (Writing the address on the history is not
    // the seam: this jsdom keeps `window.location` at `/` through
    // `replaceState`, which a browser router would read as its start.)
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={["/scan?code=STM-0001"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    // The route chunk and the module list load before the scanner mounts;
    // under the full suite that outlasts the default window.
    await waitFor(
      () => {
        expect(labelsApi.scan).toHaveBeenCalledWith("STM-0001");
      },
      { timeout: ROUTE_LOADED_WITHIN },
    );
  });
});

// Labels print {base_url}/s/<short_code> now: every byte of the address is a
// module on the label. The phone camera opens it in the browser, so the short
// address has to land on the same scanner the old one does.
describe("short /s/ scan address", () => {
  beforeEach(() => {
    tokenStore.set("test-token");
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: [],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "inventory"]),
      ),
    );
    vi.mocked(labelsApi.scan).mockReset();
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "unassigned",
      label_code: "STM-0001",
      message_key: "scan:result.labelReady",
      action: "show_quick_add",
    });
  });

  it.each([
    ["/s/STM-0001", "STM-0001"],
    // A document number keeps its slashes through the catch-all.
    ["/s/IN/2026/0001", "IN/2026/0001"],
    // The backend quotes what would otherwise end the path.
    ["/s/A%20B%231", "A B#1"],
  ])("hands %s to the scanner as %s", async (address, code) => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={[address]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    await waitFor(
      () => {
        expect(labelsApi.scan).toHaveBeenCalledWith(code);
      },
      { timeout: ROUTE_LOADED_WITHIN },
    );
  });
});
