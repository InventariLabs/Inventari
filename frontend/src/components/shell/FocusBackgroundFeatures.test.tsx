import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FocusBackgroundFeatures } from "./FocusBackgroundFeatures";
import { moduleRegistry } from "@/lib/moduleRegistry";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ enabledModules: ["provider"] }),
}));
const panelMounted = vi.fn();
function Panel() {
  panelMounted();
  return <p>Provider content</p>;
}

describe("focused background sheets", () => {
  it("mounts the provider only when opened and closes without navigation", () => {
    vi.spyOn(moduleRegistry, "getBackgroundFeatures").mockReturnValue([
      {
        provider: "provider",
        feature: "stock",
        labelKey: "common:actions.view",
        component: Panel,
      },
    ]);
    const before = window.location.href;
    render(<FocusBackgroundFeatures moduleName="consumer" />);
    expect(panelMounted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("dialog")).toHaveTextContent("Provider content");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(window.location.href).toBe(before);
  });

  it("closes the sheet from its header button, so the reader is not stuck without a keyboard", () => {
    vi.spyOn(moduleRegistry, "getBackgroundFeatures").mockReturnValue([
      {
        provider: "provider",
        feature: "stock",
        labelKey: "common:actions.view",
        component: Panel,
      },
    ]);
    render(<FocusBackgroundFeatures moduleName="consumer" />);
    fireEvent.click(screen.getByRole("button"));
    const dialog = screen.getByRole("dialog");

    fireEvent.click(within(dialog).getByRole("button", { name: /close/i }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
