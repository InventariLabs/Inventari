import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { tFor } from "@/test/mocks/i18n";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import KitsPage from "../pages/KitsPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const t = tFor("rentals");

const ASSET_ID = "11111111-1111-4111-8111-111111111111";
const KIT_ID = "22222222-2222-4222-8222-222222222222";
const KIT_ID_2 = "33333333-3333-4333-8333-333333333333";

const asset = {
  id: ASSET_ID,
  name: "Projektor 4K #1",
  model: "Projektor 4K",
  status: "AVAILABLE",
  serial_number: "PRJ-1",
};

const kit = {
  id: KIT_ID,
  name: "Fotografia",
  code: "KIT-AAAA1111",
  member_count: 2,
  summary: "Projektor 4K ×2, Aparat A7",
};

const secondKit = {
  id: KIT_ID_2,
  name: "Warsztat",
  code: "KIT-BBBB2222",
  member_count: 1,
  summary: "Wiertarka udarowa",
};

function mockBase() {
  server.use(
    http.get("/api/v1/rentals/kits", () => HttpResponse.json([])),
    http.get("/api/v1/rentals/models", () =>
      HttpResponse.json([{ model: "Projektor 4K", total_units: 3 }]),
    ),
    http.get("/api/v1/rentals/assets", () => HttpResponse.json([asset])),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {data.actions}
        {children}
      </PageHeaderContext.Provider>
    );
  }
  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={["/rentals/kits"]}>
          <HeaderHost>
            <KitsPage />
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  signInWith(["rentals:read", "rentals:write"]);
  withModules("rentals", "equipment");
  mockBase();
});

afterEach(() => {
  signOut();
});

describe("kits screen", () => {
  it("says the list is empty", async () => {
    renderPage();
    expect(await screen.findByText(t("kits.empty"))).toBeInTheDocument();
  });

  it("lists a kit's name, code, summary and member count", async () => {
    server.use(
      http.get("/api/v1/rentals/kits", () =>
        HttpResponse.json([kit, secondKit]),
      ),
    );
    renderPage();
    await screen.findByText("Fotografia");
    expect(screen.getByText("Warsztat")).toBeInTheDocument();
    // The code is a scanner's string, so it is shown as one.
    expect(screen.getByText("KIT-AAAA1111")).toHaveClass("font-mono");
    expect(screen.getByText(kit.summary)).toBeInTheDocument();
    // The count is formatted by the catalogue; both kits state their own.
    for (const count of [2, 1]) {
      expect(
        screen.getAllByText(t("kits.memberCount", { count })).length,
      ).toBeGreaterThan(0);
    }
  });

  it("saves a new kit with the member chosen in the sheet", async () => {
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/rentals/kits", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: KIT_ID,
            name: "Fotografia",
            code: "KIT-AAAA1111",
            members: [],
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
    );
    const user = renderPage();
    await screen.findByText(t("kits.empty"));
    await user.click(
      await screen.findByRole("button", { name: t("kits.new") }),
    );
    // A required field's label carries a star hidden from the a11y tree.
    const name = await screen.findByLabelText(t("kits.name"), {
      exact: false,
    });
    await user.type(name, "Fotografia");
    const assetSelect = await screen.findByLabelText(t("kits.chooseAsset"));
    await screen.findByRole("option", { name: /Projektor 4K #1/ });
    await user.selectOptions(assetSelect, ASSET_ID);
    const save = screen.getByRole("button", { name: t("kits.save") });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({
      name: "Fotografia",
      members: [{ item_id: ASSET_ID, quantity: 1 }],
    });
  });

  it("adds and removes member rows", async () => {
    const user = renderPage();
    await screen.findByText(t("kits.empty"));
    await user.click(
      await screen.findByRole("button", { name: t("kits.new") }),
    );
    expect(
      await screen.findByLabelText(t("kits.chooseAsset")),
    ).toBeInTheDocument();
    expect(screen.getAllByLabelText(t("kits.chooseAsset"))).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: t("kits.addMember") }));
    expect(screen.getAllByLabelText(t("kits.chooseAsset"))).toHaveLength(2);
    await user.click(
      screen.getAllByRole("button", { name: t("kits.removeMember") })[0],
    );
    expect(screen.getAllByLabelText(t("kits.chooseAsset"))).toHaveLength(1);
  });

  it("edits a kit with its existing members", async () => {
    const detail = {
      id: KIT_ID,
      name: "Fotografia",
      code: "KIT-AAAA1111",
      note: null,
      members: [
        {
          id: "66666666-6666-4666-8666-666666666661",
          item_id: ASSET_ID,
          item_name: "Projektor 4K #1",
          model: null,
          quantity: 1,
        },
        {
          id: "66666666-6666-4666-8666-666666666662",
          item_id: null,
          item_name: null,
          model: "Projektor 4K",
          quantity: 2,
        },
      ],
      created_at: new Date().toISOString(),
    };
    let updated: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/rentals/kits", () => HttpResponse.json([kit])),
      http.get("/api/v1/rentals/kits/:id", () => HttpResponse.json(detail)),
      http.put("/api/v1/rentals/kits/:id", async ({ request }) => {
        updated = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(detail);
      }),
    );
    const user = renderPage();
    await screen.findByText("Fotografia");
    await user.click(
      screen.getByRole("button", {
        name: t("kits.editNamed", { name: kit.name }),
      }),
    );
    const name = await screen.findByDisplayValue("Fotografia");
    expect(
      within(screen.getByRole("dialog")).getByText("KIT-AAAA1111"),
    ).toHaveClass("font-mono");
    expect(screen.getByLabelText(t("kits.quantity"))).toHaveValue(2);
    await user.clear(name);
    await user.type(name, "Fotografia 2");
    await user.click(screen.getByRole("button", { name: t("kits.save") }));
    await waitFor(() => expect(updated).not.toBeNull());
    expect(updated).toMatchObject({
      name: "Fotografia 2",
      members: [
        { item_id: ASSET_ID, quantity: 1 },
        { model: "Projektor 4K", quantity: 2 },
      ],
    });
  });

  it("deletes a kit only after the question is answered", async () => {
    let deleted: string | null = null;
    server.use(
      http.get("/api/v1/rentals/kits", () => HttpResponse.json([kit])),
      http.delete("/api/v1/rentals/kits/:id", ({ params }) => {
        deleted = String(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = renderPage();
    await screen.findByText("Fotografia");
    expect(deleted).toBeNull();
    await user.click(
      screen.getByRole("button", {
        name: t("kits.deleteNamed", { name: kit.name }),
      }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(t("kits.deleteConfirmTitle")),
    ).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: t("kits.delete") }),
    );
    await waitFor(() => expect(deleted).toBe(KIT_ID));
  });
});
