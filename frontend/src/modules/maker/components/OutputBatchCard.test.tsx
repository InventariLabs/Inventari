import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
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
    hold: { mutate: mocks.hold, isPending: false },
    release: { mutate: mocks.release, isPending: false },
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
  production_date: "2026-11-02",
  best_before: "2027-05-01",
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
      /2027/,
    );
  });

  it("prints one label per unit made, through the batch label sheet", () => {
    render(<OutputBatchCard order={run} />);

    fireEvent.click(screen.getByTestId("maker-print-batch-labels"));

    expect(screen.getByTestId("label-sheet")).toHaveTextContent("lot-1|12|");
  });

  it("holds the batch with the reason given", () => {
    render(<OutputBatchCard order={run} />);

    fireEvent.click(screen.getByTestId("maker-hold-batch"));
    fireEvent.change(screen.getByTestId("maker-hold-reason"), {
      target: { value: "Cloudy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Put on hold" }));

    expect(mocks.hold).toHaveBeenCalledWith("Cloudy", expect.anything());
  });

  it("offers a release for a batch on hold, and no second hold", () => {
    render(
      <OutputBatchCard order={{ ...run, output_lot_status: "quarantined" }} />,
    );

    expect(screen.getByText("On hold")).toBeInTheDocument();
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

describe("labels a run offers", () => {
  it("rounds a part of a unit up and stops at two hundred", () => {
    expect(labelsForRun({ ...run, actual_qty: "12.5" })).toBe(13);
    expect(labelsForRun({ ...run, actual_qty: "5000" })).toBe(200);
  });
});
