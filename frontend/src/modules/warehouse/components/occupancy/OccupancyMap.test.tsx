import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@/test/utils";
import i18n from "@/i18n/config";
import { entry, shelfNode } from "@/test/factories/occupancy";
import { OccupancyMap } from "./OccupancyMap";

function renderPicked(entries: ReturnType<typeof entry>[]) {
  const shelf = shelfNode("A1", "Hall", 1, 0, entries);
  render(
    <OccupancyMap
      nodes={[shelf]}
      byId={new Map([[shelf.location_id, shelf]])}
      hits={null}
      pickedId={shelf.location_id}
      pickedEntries={entries}
      pickedFailure={undefined}
      onPick={vi.fn()}
      onOpenSettings={vi.fn()}
    />,
  );
}

describe("OccupancyMap picked shelf", () => {
  afterEach(async () => {
    await act(() => i18n.changeLanguage("en"));
  });

  it("names a product's unit in the reader's language, with and without a limit", async () => {
    await act(() => i18n.changeLanguage("pl"));
    renderPicked([entry("Rice", "10", "50"), entry("Beans", "4", null)]);

    expect(screen.getByText(/10 z 50 szt\./)).toBeInTheDocument();
    expect(screen.getByText("4 szt.")).toBeInTheDocument();
    expect(screen.queryByText(/pcs/)).not.toBeInTheDocument();
  });
});
