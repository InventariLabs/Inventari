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
import MyAssetsPage from "../pages/MyAssetsPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * The one screen written for an ordinary employee ended at reading: ten units
 * listed, no way to hand one back and no word about who could.
 *
 * Checking in is `equipment:write` on the API and that is the right key — a
 * return is somebody receiving the unit and recording its condition, not the
 * holder declaring it gone. So the screen answers the question twice: the
 * action for a reader who holds the key, the sentence for one who does not.
 */

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
  equipment_status: "CHECKED_OUT",
  warranty_until: null,
  serial_number: "SN-9",
  image_url: null,
  model_image_url: null,
  holder_name: "Alicja Holder",
  holder_kind: "person",
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
  return render(<MyAssetsPage />, { wrapper });
}

beforeEach(() => {
  withModules("equipment");
  server.use(
    http.get("/api/v1/equipment/my-assets", () =>
      HttpResponse.json(onePage([ASSET])),
    ),
    http.get("/api/v1/equipment/my-assets/history", () =>
      HttpResponse.json(onePage([])),
    ),
  );
});

afterEach(() => {
  signOut();
});

describe("My Assets, for a holder who can check in", () => {
  beforeEach(() => {
    signInWith(["equipment:read", "equipment:write"]);
  });

  it("offers the return, and opens the check-in with the unit named", async () => {
    renderPage();
    await screen.findByText("ThinkPad T14");

    fireEvent.click(screen.getByRole("button", { name: /Return/ }));

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    // The modal names what is being handed back — it takes the assignment,
    // and the holder's list describes it under a different shape.
    expect(screen.getAllByText("ThinkPad T14").length).toBeGreaterThan(1);
    // The holder line comes from the payload, not from a field the modal
    // finds empty: it used to read "Assigned to: undefined" here.
    expect(screen.getByText(/Held by: Alicja Holder/)).toBeInTheDocument();
  });

  it("does not repeat the sentence about who else could do it", async () => {
    renderPage();
    await screen.findByText("ThinkPad T14");

    expect(screen.queryByText(/A return is recorded by/)).toBeNull();
  });
});

describe("My Assets, for a holder who cannot", () => {
  beforeEach(() => {
    signInWith(["equipment:read"]);
  });

  it("says who records a return instead of ending at reading", async () => {
    renderPage();
    await screen.findByText("ThinkPad T14");

    expect(screen.getByText(/A return is recorded by/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Return/ })).toBeNull();
  });

  it("still opens the unit — the card was always a link", async () => {
    renderPage();
    const card = await screen.findByText("ThinkPad T14");

    expect(card.closest("a")).toHaveAttribute("href", "/equipment/item-1");
  });
});
