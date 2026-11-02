import { describe, expect, it } from "vitest";
import type { WarehouseReceiving } from "@/modules/warehouse/api/putaway";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { waitingInReceiving } from "./waitingInReceiving";

const mode = (overrides: Partial<WarehouseReceiving> = {}) =>
  ({
    warehouse_id: "w1",
    two_step: true,
    receiving_location_id: "recv-1",
    receiving_location_name: "Receiving",
    ...overrides,
  }) as WarehouseReceiving;

const receipt = (executedAt: string) =>
  ({
    lines: [{ executed_location_id: executedAt }],
  }) as unknown as WarehouseDocument;

describe("waitingInReceiving", () => {
  it("names the receiving area when the goods stand in it", () => {
    expect(waitingInReceiving(receipt("recv-1"), [mode()])).toBe("Receiving");
  });

  it("says nothing for goods that landed on a shelf", () => {
    expect(waitingInReceiving(receipt("shelf-1"), [mode()])).toBeNull();
  });

  it("says nothing for a warehouse that receives in one step", () => {
    expect(
      waitingInReceiving(receipt("recv-1"), [mode({ two_step: false })]),
    ).toBeNull();
  });

  it("says nothing while the modes are not loaded", () => {
    expect(waitingInReceiving(receipt("recv-1"), undefined)).toBeNull();
  });
});
