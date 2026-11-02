import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { PutawayPlanSentence } from "./PutawayPlanSentence";
import type { PutawayPreviewLine } from "@/modules/warehouse/api/putaway";

const plan = {
  planned_location_id: "loc-receiving",
  planned_location_name: "Receiving",
  planned_source: "receiving",
  planned_rule_match_key: null,
  planned_rule_match_name: null,
  planned_rule_warning: null,
  planned_over_capacity: false,
  planned_capacity_used: null,
  planned_capacity_max: null,
  planned_shelf_fill: null,
} as PutawayPreviewLine;

describe("PutawayPlanSentence", () => {
  it("names a receiving area as the first stop, not the final shelf", () => {
    render(<PutawayPlanSentence plan={plan} checking={false} />);

    // Two-step receiving books the area and carries on later; calling it
    // the destination would promise a shelf the goods do not reach yet.
    expect(
      screen.getByText("→ Receiving · receiving area, put away later"),
    ).toBeInTheDocument();
  });
});
