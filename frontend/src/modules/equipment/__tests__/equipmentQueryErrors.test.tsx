import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { equipmentApi } from "@/modules/equipment/api/equipment";

import ImportEquipmentModal from "../components/ImportEquipmentModal";
import { CheckoutModal } from "../components/CheckoutModal";
import { EmployeeAutocomplete } from "../components/EmployeeAutocomplete";
import ModelEditModal from "../components/ModelEditModal";
import QuickAddLocationModal from "../components/QuickAddLocationModal";
import { BulkEditDialogs } from "../components/BulkEditDialogs";
import { ModelGridCard } from "../components/ModelGridCard";
import { CampaignParameters } from "../components/CampaignParameters";
import type { EquipmentModel } from "../api/equipment";
import type { Item } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * Every picker in this module reads a list the server may not deliver. A list
 * that failed used to render as an empty one — a "Location" picker with
 * nothing in it, "no matches" under a name that exists — which reads as a
 * statement about the organization instead of about the request.
 */
function renderWith(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

const fail = (path: string) =>
  http.get(path, () =>
    HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
  );

const tryAgain = () => screen.findByRole("button", { name: /try again/i });

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "locations:write",
    "categories:read",
  ]);
});

afterEach(() => {
  signOut();
});

describe("ImportEquipmentModal — the default pickers", () => {
  function chooseFile() {
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [new File(["name\nDell"], "a.csv", { type: "text/csv" })],
      },
    });
  }

  async function toMappingStep() {
    vi.spyOn(equipmentApi, "analyzeImport").mockResolvedValue({
      headers: ["name"],
      total_rows: 1,
      preview_rows: [],
      suggested_mapping: { name: "name" },
    });
    renderWith(<ImportEquipmentModal onClose={vi.fn()} />);
    chooseFile();
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));
    await screen.findByText(/1 row found/i);
  }

  it("says the locations did not load instead of offering an empty default", async () => {
    server.use(fail("/api/v1/locations"));
    await toMappingStep();

    fireEvent.click(
      screen.getByRole("combobox", { name: /default location/i }),
    );
    expect(await tryAgain()).toBeInTheDocument();
  });

  it("says the categories did not load instead of offering an empty default", async () => {
    server.use(fail("/api/v1/categories"));
    await toMappingStep();

    await tryAgain();
    expect(
      screen.queryByLabelText(/default category/i),
    ).not.toBeInTheDocument();
  });
});

describe("CheckoutModal — the location picker", () => {
  const item = {
    id: "item-1",
    name: "Laptop",
    quantity: 1,
    location_id: "loc-1",
  } as unknown as Item;

  it("says the search failed with a retry, and the retry asks again", async () => {
    let asked = 0;
    server.use(
      http.get("/api/v1/locations", () => {
        asked += 1;
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      }),
    );
    renderWith(
      <CheckoutModal item={item} onClose={vi.fn()} onDone={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /location/i }));
    await userEvent.click(screen.getByRole("combobox", { name: /^location/i }));
    const retry = await tryAgain();

    const before = asked;
    await userEvent.click(retry);
    await waitFor(() => expect(asked).toBeGreaterThan(before));
  });
});

describe("EmployeeAutocomplete — the registers", () => {
  it("does not say 'no matches' when the accounts register failed", async () => {
    server.use(fail("/api/v1/organizations/my/members"));
    renderWith(
      <EmployeeAutocomplete
        selected={null}
        onSelect={vi.fn()}
        onClear={vi.fn()}
        label="Assign to"
        includeAccounts
      />,
    );

    await userEvent.click(screen.getByRole("textbox"));

    expect(await tryAgain()).toBeInTheDocument();
    expect(screen.queryByText(/no (matching|employees)/i)).toBeNull();
  });
});

describe("ModelEditModal — the category picker", () => {
  it("says so instead of offering only 'No category'", async () => {
    server.use(fail("/api/v1/categories"));
    renderWith(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(await tryAgain()).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Category" }),
    ).not.toBeInTheDocument();
  });
});

describe("QuickAddLocationModal — the parent picker", () => {
  it("says so instead of silently dropping the parent picker", async () => {
    server.use(fail("/api/v1/locations"));
    renderWith(
      <QuickAddLocationModal isOpen onClose={vi.fn()} onCreated={vi.fn()} />,
    );

    fireEvent.click(await screen.findByRole("combobox", { name: /parent/i }));
    expect(await tryAgain()).toBeInTheDocument();
  });
});

describe("BulkEditDialogs — the target location", () => {
  it("shows the retry in place of an empty picker", async () => {
    server.use(fail("/api/v1/locations"));
    renderWith(
      <BulkEditDialogs
        action="change_location"
        selectedCount={2}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isPending={false}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("combobox"));
    expect(await tryAgain()).toBeInTheDocument();
  });
});

/**
 * Two names that decorate a label, each looked up in a list the request may
 * not deliver.
 *
 * Behaviour documents, not teeth: when the list fails the name simply is not
 * there, which is the same screen as with the lookup removed — both pass
 * either way, on purpose. What they pin is the fallback a reader gets (the
 * model's own words, the scope type alone) and the absence of the empty
 * default the picker used to offer beside it.
 */
describe("names that only decorate keep the honest fallback", () => {
  const model = {
    id: "m1",
    name: "OptiPlex 7010",
    brand: "Dell",
    category_id: "cat-1",
    equipment_meta: {},
  } as unknown as EquipmentModel;

  it("ModelGridCard renders without a category name when the list failed", async () => {
    server.use(fail("/api/v1/categories"));
    renderWith(
      <ModelGridCard
        model={model}
        onEdit={vi.fn()}
        onClone={vi.fn()}
        onDelete={vi.fn()}
        isClonePending={false}
        isDeletePending={false}
      />,
    );

    expect(await screen.findByText(/OptiPlex 7010/)).toBeInTheDocument();
  });

  it("CampaignParameters shows the scope type alone when the name lookup failed", async () => {
    server.use(fail("/api/v1/locations"));
    renderWith(
      <CampaignParameters
        scopeType="STORAGE"
        scopeFilterId="loc-1"
        deadline="2026-12-01T12:00:00Z"
        reminderDaysBefore={3}
        emailSubject={null}
      />,
    );

    expect(await screen.findByText("By location")).toBeInTheDocument();
  });
});
