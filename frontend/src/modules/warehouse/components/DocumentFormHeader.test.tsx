import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import { DocumentFormHeader } from "./DocumentFormHeader";

describe("DocumentFormHeader", () => {
  it("shows create title when not editing", () => {
    render(
      <DocumentFormHeader isEdit={false} docType="IN" onClose={vi.fn()} />,
    );
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      /new document/i,
    );
  });

  it("shows edit title when editing", () => {
    render(<DocumentFormHeader isEdit={true} docType="IN" onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      /edit document/i,
    );
  });

  it("calls onClose when X button clicked", () => {
    const onClose = vi.fn();
    render(
      <DocumentFormHeader isEdit={false} docType="IN" onClose={onClose} />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("renders without crashing for each doc type", () => {
    const types = [
      "IN",
      "OUT",
      "INT",
      "INTERNAL_IN",
      "INTERNAL_OUT",
      "CORRECTION",
      "SCRAP",
    ] as const;
    for (const docType of types) {
      const { container, unmount } = render(
        <DocumentFormHeader
          isEdit={false}
          docType={docType}
          onClose={vi.fn()}
        />,
      );
      expect(container.querySelector("h2")).toBeInTheDocument();
      unmount();
    }
  });
});
