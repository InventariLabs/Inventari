/**
 * A line whose unit does not convert to its product's stock unit is marked
 * for correction under the line, in the sentence the server wrote.
 */
import { render, screen } from "@/test/utils";
import { describe, expect, it } from "vitest";
import { PlannedPutawayLine } from "./PlannedPutawayLine";
import type { DocumentLine } from "@/modules/warehouse/types";

function line(over: Partial<DocumentLine>): DocumentLine {
  return {
    executed_location_id: null,
    planned_location_id: null,
    planned_source: null,
    unit_conversion_error: null,
    ...over,
  } as DocumentLine;
}

describe("PlannedPutawayLine", () => {
  it("shows the unit refusal instead of a plan", () => {
    render(
      <PlannedPutawayLine
        line={line({
          unit_conversion_error:
            "Quantity in box cannot be converted to the stock unit pcs",
        })}
      />,
    );
    expect(
      screen.getByText(/Quantity in box cannot be converted/),
    ).toBeInTheDocument();
  });

  it("shows nothing for a line with no plan and no refusal", () => {
    const { container } = render(<PlannedPutawayLine line={line({})} />);
    expect(container).toBeEmptyDOMElement();
  });
});
