import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import {
  OutputBatchCard,
  labelsForRun,
} from "@/modules/maker/components/OutputBatchCard";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const profile = { seed_profile: "clean_core" as string | null };
const mocks = vi.hoisted(() => ({
  hold: vi.fn(),
  release: vi.fn(),
  canManage: true,
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: vi.fn() },
}));

vi.mock("@/hooks/useActiveProfile", () => ({
  useActiveProfile: () => profile,
}));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => mocks.canManage,
}));
vi.mock("@/modules/maker/hooks/useBatches", () => ({
  useOutputBatchStatus: () => ({
    hold: { mutateAsync: mocks.hold, isPending: false },
    release: { mutate: mocks.release, isPending: false },
  }),
}));
vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useUoms: () => ({
    data: [
      { id: "c1", name: "Unit", uoms: [{ id: "u1", symbol: "pcs" }] },
      { id: "c2", name: "Weight", uoms: [{ id: "u2", symbol: "g" }] },
      { id: "c3", name: "Volume", uoms: [{ id: "u3", symbol: "ml" }] },
    ],
  }),
}));
vi.mock("@/modules/shared/components/BarcodeLabelSheet", () => ({
  BarcodeLabelSheet: (props: {
    target: { lotIds: string[] };
    initialCopies: number;
    title?: string;
  }) => (
    <div data-testid="label-sheet">
      {props.target.lotIds.join(",")}|{props.initialCopies}|{props.title ?? ""}
    </div>
  ),
}));

const run = {
  id: "ord-1",
  status: "COMPLETED",
  planned_qty: "12",
  actual_qty: "12",
  production_date: "2025-11-02",
  best_before: "2026-05-01",
  output_lot_id: "lot-1",
  output_lot_name: "20261102-1",
  output_lot_status: "active",
} as unknown as ProductionOrder;

describe("OutputBatchCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    profile.seed_profile = "clean_core";
    mocks.canManage = true;
  });

  it("shows the batch, the day it was made and its best-before", () => {
    render(<OutputBatchCard order={run} />);

    expect(screen.getByTestId("maker-output-batch-code")).toHaveTextContent(
      "20261102-1",
    );
    expect(screen.getByTestId("maker-output-best-before")).toHaveTextContent(
      /2026/,
    );
  });

  it("prints one label per unit made, through the batch label sheet", () => {
    render(<OutputBatchCard order={run} />);

    fireEvent.click(screen.getByTestId("maker-print-batch-labels"));

    expect(screen.getByTestId("label-sheet")).toHaveTextContent("lot-1|12|");
  });

  it("holds the batch with the reason given", async () => {
    render(<OutputBatchCard order={run} />);

    fireEvent.click(screen.getByTestId("maker-hold-batch"));
    fireEvent.change(screen.getByTestId("maker-hold-reason"), {
      target: { value: "Cloudy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Quarantine" }));

    expect(mocks.hold).toHaveBeenCalledWith("Cloudy");
    await waitFor(() =>
      expect(screen.queryByTestId("maker-hold-reason")).toBeNull(),
    );
  });

  it("keeps the hold dialog open, with the reason typed, when the hold is refused", async () => {
    mocks.hold.mockRejectedValueOnce(new Error("offline"));
    render(<OutputBatchCard order={run} />);

    fireEvent.click(screen.getByTestId("maker-hold-batch"));
    fireEvent.change(screen.getByTestId("maker-hold-reason"), {
      target: { value: "Cloudy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Quarantine" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByTestId("maker-hold-reason")).toHaveValue("Cloudy");
  });

  it("shows the reason a batch was quarantined, beside its state", () => {
    render(
      <OutputBatchCard
        order={
          {
            ...run,
            output_batches: [
              {
                lot_id: "lot-1",
                lot_name: "20261102-1",
                status: "quarantined",
                status_reason: "Mould on the crust",
                best_before: "2026-05-01",
              },
            ],
          } as unknown as ProductionOrder
        }
      />,
    );

    expect(screen.getByTestId("maker-batch-hold-note")).toHaveTextContent(
      "Quarantined: Mould on the crust",
    );
  });

  it("asks about one batch when the run holds one", () => {
    render(<OutputBatchCard order={run} />);

    fireEvent.click(screen.getByTestId("maker-hold-batch"));

    expect(screen.getByText("Quarantine this batch?")).toBeInTheDocument();
  });

  it("offers a release for a batch on hold, and no second hold", () => {
    render(
      <OutputBatchCard order={{ ...run, output_lot_status: "quarantined" }} />,
    );

    // The word the Batches list uses for the state.
    expect(screen.getByText("Quarantined")).toBeInTheDocument();
    expect(screen.queryByTestId("maker-hold-batch")).toBeNull();
    fireEvent.click(screen.getByTestId("maker-release-batch"));
    expect(mocks.release).toHaveBeenCalled();
  });

  it("speaks of jars at home and does not put the code forward", () => {
    profile.seed_profile = "food_home";
    render(<OutputBatchCard order={run} />);

    expect(screen.getByText("Jars from this run")).toBeInTheDocument();
    expect(screen.getByTestId("maker-output-batch-code")).toHaveTextContent(
      "Batch code 20261102-1",
    );
    fireEvent.click(screen.getByTestId("maker-print-batch-labels"));
    expect(screen.getByTestId("label-sheet")).toHaveTextContent("Jar labels");
  });

  it("is not there for a run that filed nothing under a batch", () => {
    render(<OutputBatchCard order={{ ...run, output_lot_id: null }} />);

    expect(screen.queryByTestId("maker-output-batch-card")).toBeNull();
  });
});

const filledInPortions = {
  ...run,
  actual_qty: "12",
  output_lot_id: "lot-a",
  output_lot_name: "WA",
  output_batches: [
    {
      lot_id: "lot-a",
      lot_name: "WA",
      status: "active",
      best_before: "2026-05-01",
    },
    {
      lot_id: "lot-b",
      lot_name: "WB",
      status: "active",
      best_before: "2026-06-01",
    },
    {
      lot_id: "lot-c",
      lot_name: "WC",
      status: "active",
      best_before: null,
    },
  ],
} as unknown as ProductionOrder;

describe("OutputBatchCard for a run filled in portions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    profile.seed_profile = "clean_core";
    mocks.canManage = true;
  });

  it("names every batch the output was filed under, each with its own date", () => {
    render(<OutputBatchCard order={filledInPortions} />);

    const list = screen.getByTestId("maker-output-batches");
    expect(list).toHaveTextContent("WA");
    expect(list).toHaveTextContent("WB");
    expect(list).toHaveTextContent("WC");
    expect(screen.queryByTestId("maker-output-batch-code")).toBeNull();
  });

  it("prints the labels of one batch at a time, the units spread over them", () => {
    render(<OutputBatchCard order={filledInPortions} />);

    // The label sheet takes one batch: each one has its own button.
    expect(screen.getAllByTestId("maker-print-batch-labels")).toHaveLength(3);
    fireEvent.click(
      screen.getByRole("button", { name: "Print batch labels: WB" }),
    );

    expect(screen.getByTestId("label-sheet")).toHaveTextContent("lot-b|4|");
  });

  it("offers a hold while one batch is not held, and a release while one is", () => {
    const mixed = {
      ...filledInPortions,
      output_batches: filledInPortions.output_batches?.map((batch, index) =>
        index === 0 ? { ...batch, status: "quarantined" } : batch,
      ),
    } as ProductionOrder;
    render(<OutputBatchCard order={mixed} />);

    expect(screen.getByTestId("maker-hold-batch")).toBeInTheDocument();
    expect(screen.getByTestId("maker-release-batch")).toBeInTheDocument();
  });

  it("asks about the batches, not about one, when the run holds several", () => {
    render(<OutputBatchCard order={filledInPortions} />);

    fireEvent.click(screen.getByTestId("maker-hold-batch"));

    expect(screen.getByText("Quarantine these batches?")).toBeInTheDocument();
  });

  it("says the batches are quarantined once it is done", async () => {
    render(<OutputBatchCard order={filledInPortions} />);
    fireEvent.click(screen.getByTestId("maker-hold-batch"));
    fireEvent.change(screen.getByTestId("maker-hold-reason"), {
      target: { value: "Cloudy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Quarantine" }));

    await waitFor(() =>
      expect(mocks.toastSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/^The batches are quarantined/),
      ),
    );
  });

  it("counts only the batches that were on hold when it says they are released", () => {
    const held = (count: number) =>
      ({
        ...filledInPortions,
        output_batches: filledInPortions.output_batches?.map((batch, index) =>
          index < count ? { ...batch, status: "quarantined" } : batch,
        ),
      }) as ProductionOrder;
    const { unmount } = render(<OutputBatchCard order={held(1)} />);
    fireEvent.click(screen.getByTestId("maker-release-batch"));
    mocks.release.mock.calls[0][1].onSuccess();
    expect(mocks.toastSuccess).toHaveBeenLastCalledWith(
      expect.stringMatching(/^The batch is released/),
    );
    unmount();

    render(<OutputBatchCard order={held(2)} />);
    fireEvent.click(screen.getByTestId("maker-release-batch"));
    mocks.release.mock.calls[1][1].onSuccess();
    expect(mocks.toastSuccess).toHaveBeenLastCalledWith(
      expect.stringMatching(/^The batches are released/),
    );
  });

  it("offers only a release once every batch is held", () => {
    const held = {
      ...filledInPortions,
      output_batches: filledInPortions.output_batches?.map((batch) => ({
        ...batch,
        status: "quarantined",
      })),
    } as ProductionOrder;
    render(<OutputBatchCard order={held} />);

    expect(screen.queryByTestId("maker-hold-batch")).toBeNull();
    expect(screen.getByTestId("maker-release-batch")).toBeInTheDocument();
  });
});

describe("labels a run offers", () => {
  it("rounds a part of a unit up and stops at two hundred", () => {
    expect(labelsForRun({ ...run, actual_qty: "12.5" })).toBe(13);
    expect(labelsForRun({ ...run, actual_qty: "5000" })).toBe(200);
  });

  it("starts a run counted in pieces at one label per piece", () => {
    render(
      <OutputBatchCard
        order={{ ...run, actual_qty: "12", output_uom_symbol: "pcs" }}
      />,
    );
    fireEvent.click(screen.getByTestId("maker-print-batch-labels"));
    expect(screen.getByTestId("label-sheet")).toHaveTextContent("|12|");
  });

  it.each(["g", "ml"])(
    "starts a run kept in %s at one label, not one per gram",
    (symbol) => {
      render(
        <OutputBatchCard
          order={{ ...run, actual_qty: "1000", output_uom_symbol: symbol }}
        />,
      );
      fireEvent.click(screen.getByTestId("maker-print-batch-labels"));
      expect(screen.getByTestId("label-sheet")).toHaveTextContent("|1|");
    },
  );
});
