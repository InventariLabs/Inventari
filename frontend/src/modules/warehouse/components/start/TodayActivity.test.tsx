import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { TodayActivity } from "./TodayActivity";
import { useTodayActivity } from "@/modules/warehouse/hooks/useTodayActivity";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";

vi.mock("@/modules/warehouse/hooks/useTodayActivity", () => ({
  useTodayActivity: vi.fn(),
}));

const refetch = vi.fn();

function answer(overrides: Partial<ReturnType<typeof useTodayActivity>> = {}) {
  vi.mocked(useTodayActivity).mockReturnValue({
    data: { items: [], total: 0 },
    isLoading: false,
    isError: false,
    refetch,
    ...overrides,
  } as unknown as ReturnType<typeof useTodayActivity>);
}

function postedDocument(overrides: Partial<WarehouseDocumentRow> = {}) {
  return {
    id: "doc-1",
    number: "MM/2026/031",
    type: "INT",
    status: "COMPLETED",
    partner_snapshot: null,
    completed_by_name: "Marek",
    completed_at: "2026-10-20T10:05:00Z",
    created_by_name: "Marek",
    source_location_name: "Fridge A",
    target_location_name: "Fridge B",
    line_count: 1,
    moved_line_count: 1,
    first_lines: [
      { name: "Gouda Cheese", quantity: "12", done_quantity: "12", uom: null },
    ],
    ...overrides,
  } as unknown as WarehouseDocumentRow;
}

describe("Today in the warehouse", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("narrows the feed to the warehouse the reader chose", () => {
    answer();
    render(<TodayActivity warehouseId="w-north" />);
    expect(useTodayActivity).toHaveBeenLastCalledWith("w-north");
  });

  it("says the warehouse has not moved when one is chosen", () => {
    answer();
    render(<TodayActivity warehouseId="w-north" />);
    expect(
      screen.getByText("Nothing has moved here today."),
    ).toBeInTheDocument();
  });

  it("names the person and links the document that proves it", () => {
    answer({
      data: { items: [postedDocument()], total: 1 },
    } as Partial<ReturnType<typeof useTodayActivity>>);
    render(<TodayActivity warehouseId={null} />);

    expect(
      screen.getByText("Marek: Moved 12 Gouda Cheese"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MM/2026/031" })).toHaveAttribute(
      "href",
      "/warehouse/documents/doc-1",
    );
  });

  it("counts the lines a receipt received, not the ones it kept at nought", () => {
    answer({
      data: {
        items: [
          postedDocument({
            type: "IN",
            line_count: 3,
            moved_line_count: 1,
            first_lines: [
              {
                name: "Olive oil",
                quantity: "20",
                done_quantity: "20",
                uom: null,
              },
              { name: "Flour", quantity: "50", done_quantity: "0", uom: null },
            ],
          }),
        ],
        total: 1,
      },
    } as Partial<ReturnType<typeof useTodayActivity>>);
    render(<TodayActivity warehouseId={null} />);

    expect(
      screen.getByText("Marek: Received 20 Olive oil"),
    ).toBeInTheDocument();
  });

  it("retries when the day could not be read", async () => {
    answer({ isError: true } as Partial<ReturnType<typeof useTodayActivity>>);
    render(<TodayActivity warehouseId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });
});
