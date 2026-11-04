import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import SettingsGeneralSection from "./SettingsGeneralSection";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const authState = {
  user: { role: "admin", is_superuser: false, permissions: [] as string[] },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof authState) => unknown) =>
    selector ? selector(authState) : authState,
}));

function renderSection(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[entry]}>
          <SettingsGeneralSection />
        </MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("SettingsGeneralSection", () => {
  beforeEach(() => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Org",
          currency: "PLN",
          enabled_modules: ["core"],
          settings: {},
        }),
      ),
      // The sibling cards ask for these; the section is under test, not them.
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(onePage([])),
      ),
    );
  });

  it("scrolls the module-data switch into view when the deep link asks for it", async () => {
    // The "kept out of general lists" states across the app link to
    // /settings#module-data; the switch sits below the fold, so the section
    // brings it into view rather than leaving the reader at the page top.
    const scrollSpy = vi.spyOn(HTMLElement.prototype, "scrollIntoView");

    renderSection("/settings#module-data");

    expect(await screen.findByTestId("module-data-toggle")).toBeInTheDocument();
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
  });

  it("scrolls the people section into view for the sidebar's People entry", async () => {
    const scrollSpy = vi.spyOn(HTMLElement.prototype, "scrollIntoView");

    renderSection("/settings#people");

    await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
    expect(scrollSpy.mock.contexts[0]).toHaveProperty("id", "people");
  });

  it("stays put without the hash", async () => {
    const scrollSpy = vi.spyOn(HTMLElement.prototype, "scrollIntoView");

    renderSection("/settings");

    expect(await screen.findByTestId("module-data-toggle")).toBeInTheDocument();
    expect(scrollSpy).not.toHaveBeenCalled();
  });
});
