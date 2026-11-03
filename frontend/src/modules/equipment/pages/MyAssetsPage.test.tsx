import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
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

import MyAssetsPage from "./MyAssetsPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const ASSET = {
  assignment_id: "as-1",
  item_id: "item-1",
  item_name: "ThinkPad T14",
  item_barcode: null,
  category_name: "Laptops",
  category_code: null,
  checked_out_at: "2026-08-01T10:00:00Z",
  expected_return_at: null,
  checkout_notes: null,
  equipment_status: "DEPLOYED",
  warranty_until: null,
  serial_number: "SN-9",
  image_url: null,
  model_image_url: null,
};

const PAST = {
  assignment_id: "as-0",
  item_id: "item-0",
  item_name: "Old Phone",
  checked_out_at: "2025-01-10T10:00:00Z",
  checked_in_at: "2025-06-30T10:00:00Z",
  checkin_condition: "GOOD",
};

let historyReads: number;

beforeEach(() => {
  historyReads = 0;
  signInWith(["equipment:read", "equipment:write"]);
  withModules("equipment");
  server.use(
    http.get("/api/v1/equipment/my-assets", () =>
      HttpResponse.json(onePage([ASSET])),
    ),
    http.get("/api/v1/equipment/my-assets/history", () => {
      historyReads++;
      return HttpResponse.json(onePage([PAST]));
    }),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
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
        {children}
      </PageHeaderContext.Provider>
    );
  }
  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>
            <MyAssetsPage />
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/**
 * My Assets shows what the reader holds now, opens a return on it, and
 * keeps the history folded until asked. The failures caught: the history
 * toggle that never unfolds (or never folds back), and a Return that opens
 * nothing or a dialog that cannot be closed.
 */
describe("MyAssetsPage", () => {
  it("unfolds the assignment history on request and folds it again", async () => {
    const user = renderPage();
    await screen.findByText("ThinkPad T14");
    expect(screen.queryByText("Old Phone")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show" }));
    expect(await screen.findByText("Old Phone")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText("Old Phone")).not.toBeInTheDocument();
  });

  it("says there is no history yet when the list is empty", async () => {
    server.use(
      http.get("/api/v1/equipment/my-assets/history", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    const user = renderPage();
    await screen.findByText("ThinkPad T14");

    await user.click(screen.getByRole("button", { name: "Show" }));
    expect(await screen.findByText("No past assignments")).toBeInTheDocument();
  });

  it("offers the history again after it failed to load", async () => {
    server.use(
      http.get("/api/v1/equipment/my-assets/history", () => {
        historyReads++;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    const user = renderPage();
    await screen.findByText("ThinkPad T14");
    await user.click(screen.getByRole("button", { name: "Show" }));

    const before = historyReads;
    await user.click(await screen.findByRole("button", { name: /try again/i }));
    await waitFor(() => expect(historyReads).toBeGreaterThan(before));
  });

  it("opens the return for the held asset and closes it on Cancel", async () => {
    const user = renderPage();
    await screen.findByText("ThinkPad T14");

    await user.click(screen.getByRole("button", { name: /Return/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("ThinkPad T14");
    await user.click(screen.getByText("Cancel", { selector: "button" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
