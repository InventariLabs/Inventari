import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AppStore from "./AppStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

/**
 * Switching off api_keys or webhooks revokes something that is live right now.
 * The toggle used to be one unguarded click with a toast afterwards, which is
 * too late to be a warning — and an admin reaching for this lever *because*
 * they suspect a leaked key deserves to be told it is the right lever.
 *
 * Every other module asks too, with the general sentence about its data:
 * screens disappear, data stays, switching back undoes it. An admin tidying
 * the store must be able to tell a module they never used from one with
 * production history inside — the toggle alone did not say which.
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

const toggled: { name: string; enabled: boolean }[] = [];

function listModules(...names: string[]) {
  server.use(
    http.get("/api/v1/modules/available", () =>
      HttpResponse.json(
        onePage(
          names.map((name) => ({
            name,
            display_name: name,
            description: `${name} module`,
            icon: "plug",
            requires: [],
            version: "1.0.0",
            requires_api_key: false,
            category: "integrations",
          })),
        ),
      ),
    ),
    http.post("/api/v1/modules/toggle", async ({ request }) => {
      const body = (await request.json()) as {
        module_name: string;
        enabled: boolean;
      };
      toggled.push({ name: body.module_name, enabled: body.enabled });
      return HttpResponse.json({ ok: true });
    }),
  );
}

describe("AppStore — switching off what reaches outside", () => {
  beforeEach(() => {
    toggled.length = 0;
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["api_keys", "webhooks", "recipes"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("asks before revoking every issued key, and says so", async () => {
    listModules("api_keys");
    render(<AppStore />, { wrapper: Wrapper });

    const button = await screen.findByRole("button", { name: /deactivate/i });
    await userEvent.click(button);

    expect(
      await screen.findByRole("alertdialog", { name: /switch off/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/stops working immediately/i)).toBeInTheDocument();
    expect(toggled).toHaveLength(0);
  });

  it("does nothing when the answer is no", async () => {
    listModules("webhooks");
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /deactivate/i }),
    );
    await screen.findByRole("alertdialog");
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(toggled).toHaveLength(0);
  });

  it("switches it off once the answer is yes", async () => {
    listModules("webhooks");
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /deactivate/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: /deactivate/i }),
    );

    await waitFor(() =>
      expect(toggled).toEqual([{ name: "webhooks", enabled: false }]),
    );
  });

  it("asks on every module, and the general sentence names what happens to the data", async () => {
    listModules("recipes");
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /deactivate/i }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(screen.getByText(/its data stays/i)).toBeInTheDocument();
    expect(toggled).toHaveLength(0);

    await userEvent.click(
      within(dialog).getByRole("button", { name: /deactivate/i }),
    );
    await waitFor(() =>
      expect(toggled).toEqual([{ name: "recipes", enabled: false }]),
    );
  });
});
