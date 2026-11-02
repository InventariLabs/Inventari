import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import AuditCampaignsPage from "./AuditCampaignsPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const ACTIVE = {
  id: "camp-q3",
  name: "Q3 laptops",
  description: null,
  status: "ACTIVE",
  deadline: "2026-09-30T00:00:00Z",
  launched_at: "2026-08-20T00:00:00Z",
};

const OTHER = {
  ...ACTIVE,
  id: "camp-phones",
  name: "Phones 2026",
};

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write"]);
  withModules("equipment");
  server.use(
    http.get("/api/v1/equipment/campaigns", () =>
      HttpResponse.json(onePage([ACTIVE, OTHER])),
    ),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/campaigns/scope-preview", () =>
      HttpResponse.json({ assets: 0, people: 0 }),
    ),
  );
});

afterEach(() => {
  signOut();
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {data.actions ? <div>{data.actions}</div> : null}
        {children}
      </PageHeaderContext.Provider>
    );
  }
  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>
            <AuditCampaignsPage />
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/**
 * Completing closes an attestation to further answers, so it asks first.
 * The failures caught: a complete sent on the click itself or after a
 * cancel, a search box that does not narrow the list, and a header button
 * that does not open the creation form.
 */
describe("AuditCampaignsPage", () => {
  it("completes an attestation only once the confirmation is accepted", async () => {
    let completed: string | null = null;
    server.use(
      http.post("/api/v1/equipment/campaigns/:id/complete", ({ params }) => {
        completed = params.id as string;
        return HttpResponse.json({ ...ACTIVE, status: "COMPLETED" });
      }),
    );
    const user = renderPage();
    await screen.findByText("Q3 laptops");

    await user.click(screen.getAllByRole("button", { name: "Complete" })[0]);
    let dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText("Complete attestation?"),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(completed).toBeNull();

    await user.click(screen.getAllByRole("button", { name: "Complete" })[0]);
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(completed).toBe("camp-q3"));
  });

  it("narrows the list to the attestations whose name matches", async () => {
    const user = renderPage();
    await screen.findByText("Q3 laptops");

    await user.type(
      screen.getByPlaceholderText("Search attestations…"),
      "phones",
    );
    expect(screen.getByText("Phones 2026")).toBeInTheDocument();
    expect(screen.queryByText("Q3 laptops")).not.toBeInTheDocument();
  });

  it("opens the creation form from the header and closes it again", async () => {
    const user = renderPage();
    await screen.findByText("Q3 laptops");

    await user.click(screen.getByRole("button", { name: "New attestation" }));
    const form = await screen.findByRole("dialog");
    expect(within(form).getByText("New attestation")).toBeInTheDocument();
    await user.click(within(form).getByText("Cancel", { selector: "button" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
