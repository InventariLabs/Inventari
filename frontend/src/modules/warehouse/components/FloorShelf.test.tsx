import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import FloorShelf from "./FloorShelf";

describe("FloorShelf", () => {
  it("reads the code large, the name under it, the reason and the label still to scan", () => {
    render(
      <FloorShelf
        label="Put on"
        shelf={{ code: "A-02-01", name: "Aisle A, shelf 2" }}
        reason="The product already lies here"
        confirmation="toScan"
        kind="receiving"
        onChoose={vi.fn()}
      />,
    );

    expect(screen.getByText("A-02-01")).toHaveClass("text-xl");
    expect(screen.getByText("Aisle A, shelf 2")).toBeInTheDocument();
    expect(
      screen.getByText("The product already lies here"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Scan the location to confirm"),
    ).toBeInTheDocument();
  });

  it("names a shelf without a code once, by its name", () => {
    render(
      <FloorShelf
        label="Put on"
        shelf={{ code: null, name: "Fridge B" }}
        kind="receiving"
        onChoose={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Fridge B")).toHaveLength(1);
  });

  it("is the choice itself when nothing names a shelf", async () => {
    const onChoose = vi.fn();
    render(
      <FloorShelf
        label="Put on"
        shelf={null}
        kind="receiving"
        onChoose={onChoose}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Choose a location" }));
    expect(onChoose).toHaveBeenCalledOnce();
    expect(screen.queryByText("Put on")).not.toBeInTheDocument();
  });
});
