import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import AppStore from "./AppStore";
import { server } from "@/test/mocks/server";
import { tFor } from "@/test/mocks/i18n";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

/**
 * A community module whose frontend never installed used to draw an ordinary
 * card: activate it and it reported ✓ ENABLED while existing in no launcher,
 * no navigation and under no route. The registry knew — it records whether the
 * screens landed — and the store had three badge patterns already built for
 * telling somebody what a module is missing.
 */

const mockAuthState = {
  user: { role: "admin", is_superuser: false },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

const t = tFor("common");

function moduleWith(frontend_state: string | undefined) {
  return {
    name: "shelf_labels",
    display_name: "Shelf Labels",
    description: "Prints shelf-edge labels.",
    icon: "box",
    requires: [],
    version: "1.0.0",
    requires_api_key: false,
    ...(frontend_state ? { frontend_state } : {}),
  };
}

function serveModule(frontend_state: string | undefined) {
  server.use(
    http.get("/api/v1/modules/available", () =>
      HttpResponse.json(onePage([moduleWith(frontend_state)])),
    ),
  );
}

describe("a module the store cannot show screens for", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("says the screens are missing before anyone switches it on", async () => {
    serveModule("incomplete");

    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText(t("appStore.screensMissing")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(t("appStore.screensMissingHint")),
    ).toBeInTheDocument();
  });

  it("distinguishes a module that never claimed to have any", async () => {
    serveModule("headless");

    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText(t("appStore.noScreens")),
    ).toBeInTheDocument();
    // Nothing went wrong here, so nothing tells the reader to reinstall.
    expect(
      screen.queryByText(t("appStore.screensMissingHint")),
    ).not.toBeInTheDocument();
  });

  it("stays quiet about a module that has its screens", async () => {
    serveModule("present");

    render(<AppStore />, { wrapper: Wrapper });

    expect(await screen.findByText("Shelf Labels")).toBeInTheDocument();
    expect(screen.queryByText(t("appStore.noScreens"))).not.toBeInTheDocument();
    expect(
      screen.queryByText(t("appStore.screensMissing")),
    ).not.toBeInTheDocument();
  });

  it("stays quiet when the field is absent, as an older backend sends it", async () => {
    serveModule(undefined);

    render(<AppStore />, { wrapper: Wrapper });

    expect(await screen.findByText("Shelf Labels")).toBeInTheDocument();
    expect(
      screen.queryByText(t("appStore.screensMissing")),
    ).not.toBeInTheDocument();
  });
});
