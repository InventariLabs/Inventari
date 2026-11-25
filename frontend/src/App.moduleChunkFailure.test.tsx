import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import App from "./App";

// The chunk of an enabled module is gone — a deploy renamed it.
vi.mock("./modules/api_keys/module.ts", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});

describe("an enabled module whose chunk did not load", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    tokenStore.set("test-token");
    useAuthStore.setState({
      user: {
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en" as const,
        role: "admin",
        is_active: true,
        is_superuser: false,
        is_blocked: false,
        permissions: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
      isLoading: false,
      authUnavailable: false,
      checkAuth: vi.fn(),
    });
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "api_keys"]),
      ),
      http.get("*/api/v1/about", () =>
        HttpResponse.json({ version: "1.0.0", source_code_url: null }),
      ),
    );
  });

  it("says part of the application did not load instead of answering Page Not Found", async () => {
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ModulesProvider>
          <App initialEntries={["/settings/modules/api_keys"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Part of the application did not load"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Page Not Found")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
