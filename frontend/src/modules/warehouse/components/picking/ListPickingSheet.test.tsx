import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/utils";

import { ListPickingSheet } from "./ListPickingSheet";

vi.mock("@/modules/warehouse/components/picking/WmsPickingView", () => ({
  default: ({ withoutCarrier }: { withoutCarrier?: boolean }) => (
    <div
      data-testid="picking"
      data-without-carrier={String(!!withoutCarrier)}
    />
  ),
}));

vi.mock("@/modules/warehouse/hooks/usePickingHandOff", () => ({
  usePickingHandOff: () => ({ onClose: vi.fn(), onPack: vi.fn() }),
}));

describe("ListPickingSheet", () => {
  it("passes on that the dispatches opened ask for no carrier", () => {
    render(
      <ListPickingSheet documentIds={["a"]} onLeave={vi.fn()} withoutCarrier />,
    );
    expect(screen.getByTestId("picking")).toHaveAttribute(
      "data-without-carrier",
      "true",
    );
  });
});
