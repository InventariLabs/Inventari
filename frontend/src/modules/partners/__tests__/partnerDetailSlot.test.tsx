import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { render, screen } from "@/test/utils";
import {
  moduleRegistry,
  slotComponent,
  type SlotDataMap,
} from "@/lib/moduleRegistry";
import type { Partner } from "@/types";

import { PartnerDetailSheet } from "../components/PartnerDetailSheet";

// The sheet is Partners' screen; the rental history that fills the slot is a
// stand-in contributor here, so this file stays about where the slot is
// mounted and what it is handed.
function PartnerHistoryProbe({
  data,
}: {
  data: SlotDataMap["partner_detail_extra"];
}) {
  return (
    <p data-testid="partner-history-slot">
      {data.partnerName} ({data.partnerId})
    </p>
  );
}

moduleRegistry.register({
  name: "rentals",
  routes: [],
  slots: [
    {
      slot: "partner_detail_extra",
      component: slotComponent(PartnerHistoryProbe),
    },
  ],
});

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  usePartner: () => ({ data: undefined }),
}));

const partner: Partner = {
  id: "p1",
  organization_id: "org-1",
  name: "ABC Wholesaler",
  document_count: 0,
  purchase_order_count: 0,
  code: "SUP-001",
  type: "SUPPLIER",
  tax_id: null,
  is_consumer: false,
  email: null,
  phone: null,
  website: null,
  contact_person: null,
  address: null,
  notes: null,
  is_active: true,
  created_by: null,
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
};

describe("PartnerDetailSheet — partner_detail_extra slot", () => {
  beforeEach(() => {
    signInWith(["partners:read"]);
    withModules("partners", "rentals");
  });

  afterEach(() => {
    signOut();
  });

  it("renders a module's component with the partner the sheet is about", async () => {
    render(
      <PartnerDetailSheet
        partner={partner}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onToggleActive={vi.fn()}
      />,
    );

    const slot = await screen.findByTestId("partner-history-slot");
    expect(slot).toHaveTextContent(partner.name);
    expect(slot).toHaveTextContent(partner.id);
  });
});
