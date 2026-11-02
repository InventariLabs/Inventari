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
 * Switching Webhooks off asks, and says "switching this back on resumes sending
 * to the same addresses" — to whoever switched it off. Months later someone
 * else switches it on, in one click, and every saved address starts receiving.
 * The store now asks the module what a switch-on would resume and, when the
 * answer is not zero, says the number before it happens.
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

function listModule(name: string, preview: () => Response) {
  server.use(
    http.get("/api/v1/modules/available", () =>
      HttpResponse.json(
        onePage([
          {
            name,
            display_name: name,
            description: `${name} module`,
            icon: "plug",
            requires: [],
            version: "1.0.0",
            requires_api_key: false,
            category: "integrations",
          },
        ]),
      ),
    ),
    http.get(`/api/v1/modules/${name}/enable-preview`, preview),
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

describe("AppStore — switching on what was left saved", () => {
  beforeEach(() => {
    toggled.length = 0;
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("says how many addresses will start receiving before it switches on", async () => {
    listModule("webhooks", () => HttpResponse.json({ resumes: 3 }));
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /activate/i }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/3 saved addresses/i)).toBeInTheDocument();
    expect(toggled).toHaveLength(0);
  });

  it("switches it on once the answer is yes", async () => {
    listModule("webhooks", () => HttpResponse.json({ resumes: 1 }));
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /activate/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/1 saved address\b/i)).toBeInTheDocument();
    await userEvent.click(
      within(dialog).getByRole("button", { name: /switch on/i }),
    );

    await waitFor(() =>
      expect(toggled).toEqual([{ name: "webhooks", enabled: true }]),
    );
  });

  it("does nothing when the answer is no", async () => {
    listModule("webhooks", () => HttpResponse.json({ resumes: 2 }));
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /activate/i }),
    );
    await screen.findByRole("alertdialog");
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(toggled).toHaveLength(0);
  });

  it("switches on at once when nothing saved would resume", async () => {
    listModule("webhooks", () => HttpResponse.json({ resumes: 0 }));
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /activate/i }),
    );

    await waitFor(() =>
      expect(toggled).toEqual([{ name: "webhooks", enabled: true }]),
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("does not hold the switch when the question cannot be answered", async () => {
    // The preview is advice. A failed read must not leave an admin unable to
    // switch a module on.
    listModule("webhooks", () => new HttpResponse(null, { status: 500 }));
    render(<AppStore />, { wrapper: Wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /activate/i }),
    );

    await waitFor(() =>
      expect(toggled).toEqual([{ name: "webhooks", enabled: true }]),
    );
  });
});
