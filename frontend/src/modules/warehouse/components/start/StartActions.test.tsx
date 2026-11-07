import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { StartActions } from "./StartActions";

function renderActions() {
  return render(
    <StartActions
      onReceive={vi.fn()}
      onIssue={vi.fn()}
      onMove={vi.fn()}
      onCount={vi.fn()}
    />,
  );
}

describe("StartActions", () => {
  afterEach(signOut);

  it("offers all four tiles to an account that holds both keys", () => {
    signInWith(["warehouse:write", "stock_takes:write"]);
    renderActions();
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });

  it("asks stock_takes, not warehouse, for the Count tile", () => {
    signInWith(["warehouse:write"]);
    renderActions();
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(
      screen.queryByText("Count", { selector: "span" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the Count tile for an account that may count but not move goods", () => {
    signInWith(["stock_takes:write"]);
    renderActions();
    const tiles = screen.getAllByRole("button");
    expect(tiles).toHaveLength(1);
  });

  it("offers nothing to a read-only account", () => {
    signInWith(["warehouse:read", "stock_takes:read"]);
    const { container } = renderActions();
    expect(container).toBeEmptyDOMElement();
  });
});
