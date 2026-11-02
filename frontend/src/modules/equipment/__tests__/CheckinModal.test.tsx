import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { CheckinModal } from "../components/CheckinModal";
import { CheckoutModal } from "../components/CheckoutModal";
import { MaintenanceLogModal } from "../components/MaintenanceLogModal";
import QuickAddLocationModal from "../components/QuickAddLocationModal";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import type { EquipmentAssignment } from "@/modules/equipment/api/equipment";
import type { Item } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockAssignment: EquipmentAssignment = {
  id: "asg-1",
  item_id: "item-1",
  item_name: "Dell Laptop",
  item_serial: null,
  item_asset_tag: null,
  assignee_partner_id: null,
  partner_name: null,
  checkout_location_id: null,
  checkout_location_name: null,
  assigned_to_name: "John Doe",
  assigned_to_email: "john@example.com",
  checked_out_at: "2024-01-01T00:00:00Z",
  expected_return_at: null,
  checked_in_at: null,
  checked_out_by: "user-1",
  checked_in_by: null,
  checked_out_by_name: null,
  checked_in_by_name: null,
  checkout_notes: null,
  checkin_notes: null,
  checkin_condition: null,
  created_at: "2024-01-01T00:00:00Z",
};

const mockItem = {
  id: "item-1",
  name: "Dell Laptop",
} as Item;

const expectScrollableModal = (cardTestId: string, bodyTestId: string) => {
  expect(screen.getByTestId(cardTestId)).toHaveClass(
    "max-h-[90vh]",
    "flex",
    "flex-col",
    "overflow-hidden",
  );
  expect(screen.getByTestId(bodyTestId)).toHaveClass(
    "min-h-0",
    "flex-1",
    "overflow-y-auto",
  );
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <BrowserRouter>{children}</BrowserRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

describe("CheckinModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post(
        `/api/v1/equipment/assignments/${mockAssignment.id}/checkin`,
        () => HttpResponse.json(mockAssignment),
      ),
    );
  });

  it("renders assignment item name", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    expect(screen.getByText("Dell Laptop")).toBeInTheDocument();
  });

  it("names the place a deployed asset stands in, not a person", () => {
    render(
      <CheckinModal
        assignment={{
          ...mockAssignment,
          assigned_to_name: "",
          holder_name: "Server Rack A",
          holder_kind: "location",
        }}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Stands in: Server Rack A")).toBeInTheDocument();
    expect(screen.queryByText(/Assigned to/)).not.toBeInTheDocument();
  });

  it("renders condition buttons", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    expect(screen.getByText(/good/i)).toBeInTheDocument();
    expect(screen.getByText(/damaged/i)).toBeInTheDocument();
    expect(screen.getByText(/needs repair/i)).toBeInTheDocument();
  });

  // A tap on the second radio took the asset out of circulation and filed a
  // repair entry, and neither the dialog nor the toast said so.
  it("says what each condition does to the asset before the click", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    expect(screen.getByText("Back to Available.")).toBeInTheDocument();
    expect(
      screen.getAllByText("To Maintenance, with a repair entry."),
    ).toHaveLength(2);
  });

  it("names the status a damaged return moved the asset to", async () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByRole("radio", { name: /damaged/i }));
    fireEvent.click(screen.getByRole("button", { name: "Return" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith(
      "Returned: Dell Laptop — now Maintenance",
    );
  });

  it("says only that a good return was returned", async () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByRole("button", { name: "Return" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith("Returned: Dell Laptop");
  });

  // The asset's own location is its home: a checkout to a place does not
  // move it, and the return puts it back there unless the person says else.
  it("returns the asset to its home unless told otherwise", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(
        `/api/v1/equipment/assignments/${mockAssignment.id}/checkin`,
        async ({ request }) => {
          body = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json(mockAssignment);
        },
      ),
    );
    render(
      <CheckinModal
        assignment={mockAssignment}
        homeLocationId="loc-home"
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Returns to")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Return" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(body).toMatchObject({ return_location_id: "loc-home" });
  });

  it("does not ask the holder on My Assets where the asset goes", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    expect(screen.queryByText("Returns to")).not.toBeInTheDocument();
  });

  it("calls onClose when cancel is clicked", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  // The modal uses the shared ui/Dialog primitive so
  // the role/aria-modal/aria-labelledby wiring is provided by Radix.
  it("renders the Radix dialog content (dialog migration smoke)", () => {
    const { container } = render(
      <CheckinModal assignment={mockAssignment} onClose={onClose} />,
      { wrapper: createWrapper() },
    );
    // The migrated modal must not render the legacy inline backdrop markup.
    // The legacy backdrop was a div with classes 'fixed inset-0 z-[100]'.
    const legacyBackdrops = container.ownerDocument.querySelectorAll(
      "div.fixed.inset-0.z-\\[100\\]",
    );
    expect(legacyBackdrops.length).toBe(0);
    // Radix renders the content into document.body via Portal — confirm the
    // content nodes exist somewhere in the DOM after render.
    expect(container.ownerDocument.body.textContent ?? "").toContain(
      "Dell Laptop",
    );
  });

  it("closes via the X button (Radix Dialog close primitive)", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    // Radix DialogContent auto-injects a close button with sr-only text.
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Equipment modal scrolling", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("constrains checkout content to a scrollable viewport", () => {
    render(<CheckoutModal item={mockItem} onClose={onClose} />, {
      wrapper: createWrapper(),
    });

    expectScrollableModal("checkout-modal-card", "checkout-modal-body");
  });

  it("constrains checkin content to a scrollable viewport", () => {
    render(<CheckinModal assignment={mockAssignment} onClose={onClose} />, {
      wrapper: createWrapper(),
    });

    expectScrollableModal("checkin-modal-card", "checkin-modal-body");
  });

  it("constrains maintenance content to a scrollable viewport", () => {
    render(
      <MaintenanceLogModal
        itemId={mockItem.id}
        itemName={mockItem.name}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    expectScrollableModal("maintenance-modal-card", "maintenance-modal-body");
  });

  it("constrains quick location content to a scrollable viewport", () => {
    render(
      <QuickAddLocationModal isOpen onClose={onClose} onCreated={vi.fn()} />,
      { wrapper: createWrapper() },
    );

    expectScrollableModal(
      "quick-location-modal-card",
      "quick-location-modal-body",
    );
  });
});
