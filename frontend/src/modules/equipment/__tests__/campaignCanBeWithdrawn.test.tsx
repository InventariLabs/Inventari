import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * An attestation set up wrongly had one way out and it said the wrong thing:
 * "complete" claims it finished. Now there are two, and which one applies is
 * decided by whether anything went out.
 */

const DRAFT = {
  id: "camp-draft",
  name: "Wrong deadline",
  description: null,
  status: "DRAFT",
  deadline: "2026-09-30T00:00:00Z",
  launched_at: null,
};

const ACTIVE = {
  id: "camp-active",
  name: "Wrong people",
  description: null,
  status: "ACTIVE",
  deadline: "2026-09-30T00:00:00Z",
  launched_at: "2026-08-20T00:00:00Z",
};

const CANCELLED = {
  id: "camp-cancelled",
  name: "Called off last week",
  description: null,
  status: "CANCELLED",
  deadline: "2026-09-30T00:00:00Z",
  launched_at: "2026-08-10T00:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {children}
      </PageHeaderContext.Provider>
    );
  }

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>{children}</HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<AuditCampaignsPage />, { wrapper });
}

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write"]);
  withModules("equipment");
  server.use(
    http.get("/api/v1/equipment/campaigns", () =>
      HttpResponse.json(onePage([DRAFT, ACTIVE, CANCELLED])),
    ),
  );
});

afterEach(() => {
  signOut();
});

describe("withdrawing an attestation", () => {
  it("deletes a draft, which never went out", async () => {
    let deleted: string | null = null;
    server.use(
      http.delete("/api/v1/equipment/campaigns/:id", ({ params }) => {
        deleted = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPage();
    await screen.findByText("Wrong deadline");

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleted).toBe("camp-draft"));
  });

  it("calls off a launched one instead of deleting it", async () => {
    let cancelled: string | null = null;
    server.use(
      http.post("/api/v1/equipment/campaigns/:id/cancel", ({ params }) => {
        cancelled = params.id as string;
        return HttpResponse.json({ ...ACTIVE, status: "CANCELLED" });
      }),
    );
    renderPage();
    await screen.findByText("Wrong people");

    fireEvent.click(screen.getByRole("button", { name: /Call off/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Call it off/ }));

    await waitFor(() => expect(cancelled).toBe("camp-active"));
  });

  it("offers no deletion on a launched one", async () => {
    renderPage();
    await screen.findByText("Wrong people");

    // One Delete on the page: the draft's. The launched row must not have
    // one — the answers that came back are the only trace an attestation
    // produces, and the foreign key cascades.
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);
  });

  it("keeps a called-off one readable", async () => {
    renderPage();
    const row = await screen.findByText("Called off last week");

    // The reason for cancelling rather than deleting: it is still there, and
    // it says what it is.
    expect(row).toBeInTheDocument();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });
});
