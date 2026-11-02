import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@/test/utils";
import { ImportPastePanel } from "./ImportPastePanel";

describe("ImportPastePanel", () => {
  it("renders textarea and parse button", () => {
    render(<ImportPastePanel onParse={vi.fn()} isParsing={false} />);
    expect(
      screen.getByPlaceholderText(/name.*quantity.*barcode/s),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Parse/i })).toBeInTheDocument();
  });

  it("disables parse button when textarea is empty", () => {
    render(<ImportPastePanel onParse={vi.fn()} isParsing={false} />);
    expect(screen.getByRole("button", { name: /Parse/i })).toBeDisabled();
  });

  it("enables parse button when text is entered", () => {
    render(<ImportPastePanel onParse={vi.fn()} isParsing={false} />);
    const textarea = screen.getByPlaceholderText(/name/s);
    fireEvent.change(textarea, {
      target: { value: "name\tqty\nWidget\t10" },
    });
    expect(screen.getByRole("button", { name: /Parse/i })).not.toBeDisabled();
  });

  it("calls onParse with text when parse is clicked", async () => {
    const onParse = vi.fn().mockResolvedValue(undefined);
    render(<ImportPastePanel onParse={onParse} isParsing={false} />);
    const textarea = screen.getByPlaceholderText(/name/s);
    const text = "name\tqty\nWidget\t10";
    fireEvent.change(textarea, { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: /Parse/i }));
    await waitFor(() => {
      expect(onParse).toHaveBeenCalledWith(text);
    });
  });

  it("does not call onParse for whitespace-only text", async () => {
    const onParse = vi.fn().mockResolvedValue(undefined);
    render(<ImportPastePanel onParse={onParse} isParsing={false} />);
    const textarea = screen.getByPlaceholderText(/name/s);
    fireEvent.change(textarea, { target: { value: "   \n  " } });
    expect(screen.getByRole("button", { name: /Parse/i })).toBeDisabled();
  });

  it("shows parsing label when isParsing is true", () => {
    render(<ImportPastePanel onParse={vi.fn()} isParsing={true} />);
    expect(screen.getByRole("button", { name: /Parsing/i })).toBeDisabled();
  });
});
