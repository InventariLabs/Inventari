import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import { FormSheetFooter } from "./FormSheetFooter";

function renderFooter(
  overrides: Partial<React.ComponentProps<typeof FormSheetFooter>> = {},
) {
  const props = {
    isPending: false,
    lineCount: 0,
    lineCountText: "3 lines",
    cancelText: "Cancel",
    submitText: "Create",
    onCancel: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides,
  };
  const utils = render(<FormSheetFooter {...props} />);
  return { ...utils, props };
}

describe("FormSheetFooter", () => {
  it("shows the submit label when not pending", () => {
    renderFooter();
    expect(screen.getByText("Create")).toBeInTheDocument();
  });

  it("disables the submit button and shows a spinner beside its label while pending", () => {
    const { container } = renderFooter({ isPending: true });
    expect(screen.getByText("Create")).toBeInTheDocument();
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
    const submitBtn = container.querySelectorAll("button")[1];
    expect(submitBtn).toBeDisabled();
  });

  it("shows the line-count hint when lineCount > 0", () => {
    renderFooter({ lineCount: 3 });
    expect(screen.getByText("3 lines")).toBeInTheDocument();
  });

  it("hides the line-count hint when lineCount is 0", () => {
    renderFooter({ lineCount: 0, lineCountText: "0 lines" });
    expect(screen.queryByText("0 lines")).not.toBeInTheDocument();
  });

  it("calls onCancel when the cancel button is clicked", () => {
    const { props } = renderFooter();
    fireEvent.click(screen.getByText("Cancel"));
    expect(props.onCancel).toHaveBeenCalledOnce();
  });

  it("calls onSubmit when the submit button is clicked", () => {
    const { props } = renderFooter();
    fireEvent.click(screen.getByText("Create"));
    expect(props.onSubmit).toHaveBeenCalledOnce();
  });
});
