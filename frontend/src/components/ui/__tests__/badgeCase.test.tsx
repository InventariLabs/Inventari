/**
 * Uppercase is reserved, not decorative.
 *
 * `Badge` hardcoded `uppercase tracking-widest` in its base, so every badge in
 * the product shouted regardless of what it carried. Counted on the running
 * app, one screen rendered 51 uppercase runs and another 6 — the same product,
 * an eightfold spread — and a signal that says "this is a label, not content"
 * stops working when fifty things on a screen are labels. It is kept for a
 * column header and a status pill, and nothing else.
 */
import { render, screen } from "@/test/utils";
import { describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/Badge";
import { StatusBadge } from "@/components/ui/StatusBadge";

describe("uppercase is reserved for a status", () => {
  it("leaves a plain badge in sentence case", () => {
    render(<Badge>3 of 7 purchased</Badge>);

    const badge = screen.getByText("3 of 7 purchased");
    expect(badge.className).not.toContain("uppercase");
    expect(badge.className).not.toContain("tracking-widest");
  });

  it("keeps a status pill shouting, because a status is a shape to recognise", () => {
    render(<StatusBadge status="AVAILABLE" label="Available" />);

    const badge = screen.getByText("Available");
    expect(badge.className).toContain("uppercase");
  });

  it("lets a caller add to the status classes without losing them", () => {
    render(
      <StatusBadge status="AVAILABLE" label="Available" className="ml-2" />,
    );

    const badge = screen.getByText("Available");
    expect(badge.className).toContain("uppercase");
    expect(badge.className).toContain("ml-2");
  });
});
