import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FocusLockGate } from "./FocusLockGate";

const refreshFocus = vi.fn();
const state: {
  focusModule: string | null;
  focusStatus: "loading" | "failed" | "ready";
} = { focusModule: null, focusStatus: "ready" };

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    focusModule: state.focusModule,
    focusStatus: state.focusStatus,
    refreshFocus,
  }),
}));

function renderGate() {
  return render(
    <MemoryRouter>
      <FocusLockGate>
        <p>Browse apps</p>
      </FocusLockGate>
    </MemoryRouter>,
  );
}

describe("FocusLockGate", () => {
  beforeEach(() => {
    state.focusModule = null;
    state.focusStatus = "ready";
    refreshFocus.mockReset();
  });

  it("shows the screen when every module is showing", () => {
    state.focusModule = null;
    renderGate();
    expect(screen.getByText("Browse apps")).toBeInTheDocument();
  });

  it("replaces the screen when one module is showing and keeps the way back visible", () => {
    state.focusModule = "equipment";
    renderGate();
    expect(screen.queryByText("Browse apps")).not.toBeInTheDocument();
    expect(screen.getByText("Only one module is showing")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open My modules" }),
    ).toHaveAttribute("href", "/settings/my-modules");
  });

  it("does not offer the screen while the focus read is pending", () => {
    state.focusStatus = "loading";
    renderGate();
    expect(screen.queryByText("Browse apps")).not.toBeInTheDocument();
  });

  it("does not take a failed focus read for an ordinary workspace", () => {
    state.focusStatus = "failed";
    renderGate();
    expect(screen.queryByText("Browse apps")).not.toBeInTheDocument();
    expect(
      screen.getByText("Could not check which modules are showing"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open My modules" }),
    ).toHaveAttribute("href", "/settings/my-modules");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refreshFocus).toHaveBeenCalledTimes(1);
  });
});
