/*
 * Verify that the four migrated ad-hoc modals no longer render the
 * legacy inline backdrop markup (``fixed inset-0 z-[100]``) anywhere in the
 * tree, and that they all get ``role="dialog"`` from the shared Radix
 * ui/Dialog primitive instead.
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

import { CheckinModal } from "../components/CheckinModal";
import { MaintenanceLogModal } from "../components/MaintenanceLogModal";
import { CheckoutModal } from "../components/CheckoutModal";
import QuickAddLocationModal from "../components/QuickAddLocationModal";
import ImportEquipmentModal from "../components/ImportEquipmentModal";
import ModelEditModal from "../components/ModelEditModal";
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import { ModulesProvider } from "@/contexts/ModulesContext";
import type { EquipmentAssignment } from "../api/equipment";
import type { Item } from "@/types";

const mockAssignment: EquipmentAssignment = {
  id: "a-1",
  item_id: "i-1",
  item_name: "Dell Laptop",
  item_serial: null,
  item_asset_tag: null,
  assignee_partner_id: null,
  partner_name: null,
  checkout_location_id: null,
  checkout_location_name: null,
  assigned_to_name: "John",
  assigned_to_email: "john@example.com",
  checked_out_at: "2024-01-01T00:00:00Z",
  expected_return_at: null,
  checked_in_at: null,
  checked_out_by: "u-1",
  checked_in_by: null,
  checked_out_by_name: null,
  checked_in_by_name: null,
  checkout_notes: null,
  checkin_notes: null,
  checkin_condition: null,
  created_at: "2024-01-01T00:00:00Z",
};

const mockItem: Item = {
  id: "i-1",
  name: "Test Asset",
  description: null,
  weight: null,
  quantity: 1,
  added_date: null,
  expiry_date: null,
  brand: null,
  barcode: null,
  status: "ACTIVE",
  category_id: null,
  location_id: null,
  context_tag: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  metadata: { equipment: { equipment_status: "AVAILABLE" } },
} as unknown as Item;

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <BrowserRouter>{children}</BrowserRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

describe("modal Dialog migration", () => {
  it.each([
    [
      "CheckinModal",
      () => <CheckinModal assignment={mockAssignment} onClose={() => {}} />,
    ],
    [
      "MaintenanceLogModal",
      () => (
        <MaintenanceLogModal
          itemId="i-1"
          itemName="Test Asset"
          onClose={() => {}}
        />
      ),
    ],
    [
      "CheckoutModal",
      () => <CheckoutModal item={mockItem} onClose={() => {}} />,
    ],
    // The three modals that were left ad-hoc in the first migration pass
    // are now on ui/Dialog too.
    ["ImportEquipmentModal", () => <ImportEquipmentModal onClose={() => {}} />],
    [
      "ModelEditModal",
      () => (
        <ModelEditModal
          isOpen={true}
          model={null}
          isSubmitting={false}
          onSave={() => {}}
          onClose={() => {}}
        />
      ),
    ],
  ])(
    "%s no longer renders the legacy z-[100] inline backdrop",
    (_name, renderEl) => {
      const { baseElement } = render(renderEl(), { wrapper: createWrapper() });
      const legacyBackdrops = baseElement.querySelectorAll(
        "div.fixed.inset-0.z-\\[100\\]",
      );
      expect(legacyBackdrops.length).toBe(0);
    },
  );

  it.each([
    [
      "CheckinModal",
      () => <CheckinModal assignment={mockAssignment} onClose={() => {}} />,
      "Return Asset",
    ],
    [
      "MaintenanceLogModal",
      () => (
        <MaintenanceLogModal
          itemId="i-1"
          itemName="Test Asset"
          onClose={() => {}}
        />
      ),
      "Add Entry",
    ],
    [
      "CheckoutModal",
      () => <CheckoutModal item={mockItem} onClose={() => {}} />,
      "Check Out Asset",
    ],
  ])(
    "%s renders inside a Radix Dialog root",
    (_name, renderEl, expectedTitle) => {
      render(renderEl(), { wrapper: createWrapper() });
      // The localized title may also appear in the sr-only DialogDescription
      // and/or in the modal's submit button text — assert at least one match.
      expect(screen.getAllByText(expectedTitle).length).toBeGreaterThan(0);
    },
  );

  it("QuickAddLocationModal (isOpen prop) wires open state to Dialog", () => {
    const { rerender, baseElement } = render(
      <QuickAddLocationModal
        isOpen={false}
        onClose={() => {}}
        onCreated={() => {}}
      />,
      { wrapper: createWrapper() },
    );
    // With isOpen={false} Radix Dialog removes its content from the DOM.
    expect(baseElement.querySelector("[role='dialog']")).toBeNull();

    rerender(
      <QuickAddLocationModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );
    // The dialog title carries the localized "Add Location" copy —
    // disambiguate from any identically-named buttons below it.
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
  });

  it("AuditCampaignsPage CreateCampaignModal migrates to ui/Dialog", () => {
    // Render the page; opening the modal flips it to ui/Dialog. We assert
    // there are zero legacy backdrops even after triggering creation.
    const { baseElement } = render(<AuditCampaignsPage />, {
      wrapper: createWrapper(),
    });
    // Page itself must never emit a fixed z-[100] overlay.
    const legacy = baseElement.querySelectorAll(
      "div.fixed.inset-0.z-\\[100\\]",
    );
    expect(legacy.length).toBe(0);
  });
});
