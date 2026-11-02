import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NutritionToolbar } from "./NutritionToolbar";

const t = (key: string) => key;

vi.mock("@/components/ui/ListControlBar", () => ({
  ListControlBar: ({ primaryAction }: { primaryAction?: React.ReactNode }) => (
    <div>{primaryAction}</div>
  ),
}));

function renderToolbar(
  over: Partial<Parameters<typeof NutritionToolbar>[0]> = {},
) {
  const props = {
    q: "",
    onSearch: vi.fn(),
    onToggleAdd: vi.fn(),
    onImport: vi.fn(),
    onExport: vi.fn(),
    canWrite: true,
    canExport: true,
    t,
    ...over,
  };
  return render(<NutritionToolbar {...props} />);
}

describe("NutritionToolbar — the export button answers for what it hands over", () => {
  it("exports when there is something to export", async () => {
    const onExport = vi.fn();
    renderToolbar({ onExport });
    await userEvent.click(
      screen.getByText("recipes:ingredient_defaults.export"),
    );
    expect(onExport).toHaveBeenCalledOnce();
  });

  it("says why it is dead when the dictionary has no entries", () => {
    // An export of an empty dictionary used to download a file with a
    // header in it and no word of explanation — the reader got the empty
    // artifact as if it were the data.
    renderToolbar({ canExport: false, exportHint: "Nothing to export yet" });
    const button = screen
      .getByText("recipes:ingredient_defaults.export")
      .closest("button")!;
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Nothing to export yet");
  });

  it("stays dead while loading even without a hint", () => {
    renderToolbar({ canExport: false });
    const button = screen
      .getByText("recipes:ingredient_defaults.export")
      .closest("button")!;
    expect(button).toBeDisabled();
    expect(button).not.toHaveAttribute("title");
  });

  it("keeps only the export for an account that may not write", () => {
    // Add and import write the dictionary; export reads it. Hiding all three
    // would turn the screen into a dead end.
    renderToolbar({ canWrite: false });

    expect(
      screen.queryByText("recipes:ingredient_defaults.add"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("recipes:ingredient_defaults.import"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("recipes:ingredient_defaults.export"),
    ).toBeInTheDocument();
  });
});
