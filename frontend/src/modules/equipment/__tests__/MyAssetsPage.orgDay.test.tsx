import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
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

/**
 * The return day reproduction in "My assets".
 *
 * The checkout form said "2026-09-30" and the record stores
 * ``2026-09-30T00:00:00Z``. A Los Angeles reader used to see "Sep 29, 2026"
 * here — the browser reading its own day off an instant the organization's
 * clock owns (the same defect as the assignments tab on /equipment/<id>,
 * seen here on this screen too).
 */

const ASSET = {
  assignment_id: "as-1",
  item_id: "item-1",
  item_name: "ThinkPad T14",
  item_barcode: null,
  category_name: "Laptops",
  category_code: null,
  checked_out_at: "2026-08-01T10:00:00Z",
  expected_return_at: "2026-09-30T00:00:00Z",
  checkout_notes: null,
  equipment_status: "CHECKED_OUT",
  warranty_until: null,
  serial_number: "SN-9",
  image_url: null,
  model_image_url: null,
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

function inZone(zone: string, body: () => Promise<void> | void): Promise<void> {
  const original = process.env.TZ;
  process.env.TZ = zone;
  return Promise.resolve()
    .then(body)
    .finally(() => {
      process.env.TZ = original;
    });
}

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write"]);
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
  process.env.TZ = undefined;
  signOut();
});

describe("My Assets — the return day reads the organization's clock", () => {
  it("a Los Angeles reader sees the day the form picked, not the one before", async () => {
    await inZone("America/Los_Angeles", async () => {
      server.use(
        http.get("/api/v1/organizations/my", () =>
          HttpResponse.json({ timezone: "UTC" }),
        ),
      );

      renderPage();
      await screen.findByText("ThinkPad T14");

      expect(screen.getByText(/Sep 30, 2026/)).toBeInTheDocument();
      expect(screen.queryByText(/Sep 29, 2026/)).not.toBeInTheDocument();
    });
  });
});
