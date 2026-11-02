import React from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import PartnersPage from "./PartnersPage";
import type { Partner } from "@/types";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

type MutateOptions = { onSuccess: () => void; onError: (e: unknown) => void };
const calls = vi.hoisted(() => ({
  list: [] as Record<string, unknown>[],
  deactivate: [] as [string, unknown][],
  activate: [] as [string, unknown][],
  partners: [] as unknown[],
  total: 0,
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  usePartners: (params: Record<string, unknown>) => {
    calls.list.push(params);
    return {
      data: { items: calls.partners, total: calls.total },
      isLoading: false,
      isError: false,
    };
  },
  usePartner: () => ({ data: undefined }),
  useDeactivatePartner: () => ({
    mutate: (id: string, opts: unknown) => calls.deactivate.push([id, opts]),
  }),
  useActivatePartner: () => ({
    mutate: (id: string, opts: unknown) => calls.activate.push([id, opts]),
  }),
}));

vi.mock("@/modules/partners/components/PartnerFormModal", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog" aria-label="Partner form">
      <button onClick={onClose}>close partner form</button>
    </div>
  ),
}));

vi.mock("@/modules/partners/components/PartnerImportModal", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog" aria-label="Partner import">
      <button onClick={onClose}>close import</button>
    </div>
  ),
}));

const partner = (id: string, name: string, is_active = true): Partner =>
  ({
    purchase_order_count: 0,
    document_count: 0,
    id,
    organization_id: "org-1",
    name,
    code: null,
    type: "SUPPLIER",
    tax_id: null,
    is_consumer: false,
    email: null,
    phone: null,
    website: null,
    contact_person: null,
    address: null,
    notes: null,
    is_active,
    created_by: null,
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:00:00Z",
  }) as Partner;

function Shell({ children }: { children: React.ReactNode }) {
  const [data, setHeader] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader }}>
      <header aria-label="Page header">{data.actions}</header>
      {children}
    </PageHeaderContext.Provider>
  );
}

const renderPage = () =>
  render(
    <Shell>
      <PartnersPage />
    </Shell>,
  );
const header = () => screen.getByRole("banner", { name: "Page header" });

/**
 * The partner register's own actions: activating and deactivating name the
 * partner they act on and toast the server's refusal, the filter tabs ask
 * for the right set, the pager walks back, and the header's import and new
 * partner open their forms. Activating the wrong partner, swallowing a
 * refusal, or a filter tab asking for the active set fails here.
 */
describe("PartnersPage — register actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    calls.list = [];
    calls.deactivate = [];
    calls.activate = [];
    calls.partners = [partner("p-1", "ACME"), partner("p-2", "Zed", false)];
    calls.total = 2;
    signInWith(["partners:read", "partners:write"]);
  });

  afterEach(() => signOut());

  it("activates an inactive partner and says so; a refusal is toasted", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Activate" }));
    expect(calls.activate.map(([id]) => id)).toEqual(["p-2"]);
    const opts = calls.activate[0][1] as MutateOptions;
    opts.onSuccess();
    expect(toast.success).toHaveBeenCalledWith("Partner activated");
    opts.onError(new Error("network"));
    expect(toast.error).toHaveBeenCalledWith("Failed to activate partner");
  });

  it("deactivates only after the confirmation, and toasts a refusal", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(calls.deactivate).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: "Deactivate" }),
    );
    await waitFor(() => expect(calls.deactivate).toHaveLength(1));
    expect(calls.deactivate[0][0]).toBe("p-1");
    (calls.deactivate[0][1] as MutateOptions).onError(new Error("x"));
    expect(toast.error).toHaveBeenCalledWith("Failed to deactivate partner");
  });

  it("asks for inactive and then for every partner from the tabs", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("tab", { name: /Inactive/ }));
    await waitFor(() => expect(calls.list.at(-1)?.is_active).toBe(false));
    await user.click(screen.getByRole("tab", { name: /All/ }));
    await waitFor(() => expect(calls.list.at(-1)?.is_active).toBeUndefined());
  });

  it("walks the pager forward and back", async () => {
    calls.partners = Array.from({ length: 25 }, (_, i) =>
      partner(`p-${i}`, `Partner ${i}`),
    );
    calls.total = 60;
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(calls.list.at(-1)?.offset).toBe(25));
    await user.click(screen.getByRole("button", { name: /previous/i }));
    await waitFor(() => expect(calls.list.at(-1)?.offset).toBe(0));
  });

  it("opens and closes the import and the new partner form from the header", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(within(header()).getByRole("button", { name: "Import" }));
    await user.click(screen.getByRole("button", { name: "close import" }));
    expect(
      screen.queryByRole("dialog", { name: "Partner import" }),
    ).not.toBeInTheDocument();

    await user.click(
      within(header()).getByRole("button", { name: "New partner" }),
    );
    await user.click(
      screen.getByRole("button", { name: "close partner form" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "Partner form" }),
    ).not.toBeInTheDocument();
  });

  it("offers a new partner from an empty register", async () => {
    calls.partners = [];
    calls.total = 0;
    const user = userEvent.setup();
    renderPage();
    const buttons = screen.getAllByRole("button", { name: "New partner" });
    await user.click(buttons[buttons.length - 1]);
    expect(
      screen.getByRole("dialog", { name: "Partner form" }),
    ).toBeInTheDocument();
  });

  it("closes the detail sheet, and deactivates from it after confirming", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("ACME"));
    let sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByText("ACME"));
    sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: "Deactivate" }),
    );
    await waitFor(() => expect(calls.deactivate[0]?.[0]).toBe("p-1"));
  });
});
