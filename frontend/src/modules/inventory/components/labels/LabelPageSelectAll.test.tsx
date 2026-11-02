import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import type { LabelPool } from "@/types";
import { LabelPageSelectAll } from "./LabelPageSelectAll";

const label = (id: string) => ({ id, short_code: id }) as unknown as LabelPool;

function Harness({ initial }: { initial: string[] }) {
  const [selectedIds, setSelectedIds] = useState<string[]>(initial);
  return (
    <>
      <LabelPageSelectAll
        labels={[label("a"), label("b")]}
        selectedIds={selectedIds}
        setSelectedIds={setSelectedIds}
      />
      <output>{selectedIds.join(",")}</output>
    </>
  );
}

/**
 * The header checkbox acts on this page only. A selection made on another
 * page ("z" below) must survive both the select and the clear — dropping it
 * would delete or print fewer labels than the reader had picked.
 */
describe("LabelPageSelectAll", () => {
  it("adds this page's labels to a selection from another page, without doubling one already picked", () => {
    render(<Harness initial={["z", "a"]} />);
    const box = screen.getByRole("checkbox", { name: "Select all" });
    expect(box).not.toBeChecked();

    fireEvent.click(box);
    expect(screen.getByRole("status")).toHaveTextContent("z,a,b");
    expect(box).toBeChecked();
  });

  it("clears this page's labels and leaves the other page's selection", () => {
    render(<Harness initial={["z", "a", "b"]} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByRole("status")).toHaveTextContent(/^z$/);
  });
});
