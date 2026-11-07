import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ArchivedItemSheet from "./ArchivedItemSheet";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

describe("ArchivedItemSheet", () => {
  const mockItem = {
    id: "old-item-1",
    location_id: "location-1",
    category_id: null,
    name: "Old Milk",
    brand: "Old Brand",
    description: null,
    weight: null,
    uom_id: null,
    uom: null,
    quantity: "1",
    added_date: new Date().toISOString(),
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    is_deleted: true,
    deleted_at: new Date().toISOString(),
    deletion_reason: "USED",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    barcode: undefined,
    serial_number: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/labels/pool/STM-0001/unassign", () =>
        HttpResponse.json({ message: "Success" }),
      ),
    );
  });

  it("should render archived item details", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={mockItem}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={() => {}}
        />
      </QueryClientProvider>,
    );

    // Check archived item info renders (label code, item name, deletion reason)
    expect(screen.getByText(/STM-0001/i)).toBeInTheDocument();
    expect(screen.getByText(/Old Milk/i)).toBeInTheDocument();
    // The stored reason is a vocabulary code; the sheet shows its word.
    expect(
      screen.getByText(
        (_, el) => el?.textContent?.trim() === "Reason for deletion: Used",
      ),
    ).toBeInTheDocument();
  });

  it("calls the stored value what it is: the reason the product was deleted", () => {
    // Read as "Status: Test / erroneous data", the line put the deletion
    // reason under a word the sheet uses for nothing else.
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={{ ...mockItem, deletion_reason: "TEST_DATA" }}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(
      screen.getByText(
        (_, el) =>
          el?.textContent?.trim() ===
          "Reason for deletion: Test / erroneous data",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Status/)).not.toBeInTheDocument();
  });

  it("shows a missing reason as a lack, not as the reason Other", () => {
    // The defect this sheet carried for a year: a record archived without a
    // reason read "Reason for deletion: Other", because the missing value was defaulted
    // into a key that exists — the one answer that cannot be counted, said
    // with confidence. The absence has its own word now.
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={{ ...mockItem, deletion_reason: null }}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(
      screen.getByText(
        (_, el) => el?.textContent?.trim() === "Reason for deletion: Unknown",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        (_, el) => el?.textContent?.trim() === "Reason for deletion: Other",
      ),
    ).not.toBeInTheDocument();
  });

  it("heads the sheet with what the sheet shows", () => {
    // The heading came from the change-history tab of the item card, which
    // is a different screen's story. This sheet holds one label and the one
    // thing it was stuck to.
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={mockItem}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByText("Product history")).toBeInTheDocument();
    expect(screen.queryByText("Change history")).not.toBeInTheDocument();
  });

  it("reads an unmapped stored reason as the value that was written", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={{ ...mockItem, deletion_reason: "SOMETHING_NEW" }}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(
      screen.getByText(
        (_, el) =>
          el?.textContent?.trim() === "Reason for deletion: SOMETHING_NEW",
      ),
    ).toBeInTheDocument();
  });

  it("should call unassign API when reuse button clicked", async () => {
    const onReuse = vi.fn();
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={mockItem}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={onReuse}
        />
      </QueryClientProvider>,
    );

    const reuseBtn = screen.getByText(/Reuse label|actions\.reuseLabel/i);
    fireEvent.click(reuseBtn);

    await waitFor(() => {
      expect(onReuse).toHaveBeenCalled();
    });
  });

  it("names the label when freeing it fails without a reason", async () => {
    server.use(
      http.post("/api/v1/labels/pool/STM-0001/unassign", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
      ),
    );
    const onReuse = vi.fn();
    render(
      <QueryClientProvider client={queryClient}>
        <ArchivedItemSheet
          item={mockItem}
          labelCode="STM-0001"
          onClose={() => {}}
          onReuse={onReuse}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByText(/Reuse label/i));

    // "The action could not be completed." said nothing about which write.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Could not free the label"),
    );
    expect(onReuse).not.toHaveBeenCalled();
  });
});
