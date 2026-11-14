import { describe, expect, expectTypeOf, it } from "vitest";
import { TypedSlot } from "@/components/Slot";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";

// The slot is declared in slotAugmentation.fixture.d.ts the way a module's own
// `slots.d.ts` declares it. These checks are compiled by `tsc`: with the
// recipe broken the new name is refused, and so are the core slots that
// other files use.
describe("a module's own slot through SlotDataMap", () => {
  it("is part of the map next to the core slots", () => {
    expectTypeOf<SlotDataMap["fixture_module_card_extra"]>().toEqualTypeOf<{
      recordId: string;
    }>();
    expectTypeOf<"item_edit_extra">().toMatchTypeOf<keyof SlotDataMap>();
    const data: SlotDataMap["fixture_module_card_extra"] = { recordId: "r-1" };
    expect(data.recordId).toBe("r-1");
  });

  it("is accepted by TypedSlot with the data shape it declared", () => {
    // Compile-time check: a wrong shape or an unknown name fails `tsc`.
    const element = (
      <TypedSlot name="fixture_module_card_extra" data={{ recordId: "r-1" }} />
    );
    expect(element.props.name).toBe("fixture_module_card_extra");
  });
});
