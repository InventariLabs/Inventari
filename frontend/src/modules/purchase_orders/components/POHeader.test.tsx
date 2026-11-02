import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import { POHeader } from "./POHeader";

describe("POHeader", () => {
  it("shows create title and subtitle when not editing", () => {
    render(
      <POHeader
        isEdit={false}
        onClose={vi.fn()}
        titleCreate="New PO"
        titleEdit="Edit PO"
        subtitleCreate="Create purchase order"
        subtitleEdit="Edit purchase order"
      />,
    );
    expect(screen.getByText("New PO")).toBeInTheDocument();
  });

  it("shows edit title when editing", () => {
    render(
      <POHeader
        isEdit={true}
        onClose={vi.fn()}
        titleCreate="New PO"
        titleEdit="Edit PO"
        subtitleCreate="Create purchase order"
        subtitleEdit="Edit purchase order"
      />,
    );
    expect(screen.getByText("Edit PO")).toBeInTheDocument();
  });

  it("names the close button for what it does, not for the dialog it sits in", () => {
    // The icon button announced itself as "New Purchase Order", so a screen
    // reader user had every reason to think it created an order. The dialog
    // is already named by the Sheet's aria-label.
    render(
      <POHeader
        isEdit={false}
        onClose={vi.fn()}
        titleCreate="New Purchase Order"
        titleEdit="Edit Purchase Order"
        subtitleCreate="Create"
        subtitleEdit="Edit"
      />,
    );
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New Purchase Order" }),
    ).not.toBeInTheDocument();
  });

  it("calls onClose when X button clicked", () => {
    const onClose = vi.fn();
    render(
      <POHeader
        isEdit={false}
        onClose={onClose}
        titleCreate="New PO"
        titleEdit="Edit PO"
        subtitleCreate="Create"
        subtitleEdit="Edit"
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
