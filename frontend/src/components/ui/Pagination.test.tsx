import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import Pagination from "./Pagination";

const base = {
  skip: 0,
  limit: 50,
  total: 608,
  onPrev: vi.fn(),
  onNext: vi.fn(),
};

describe("Pagination", () => {
  it("renders nothing when there is nothing to page through", () => {
    const { container } = render(<Pagination {...base} total={0} />);
    expect(container.firstChild).toBeNull();
  });

  it("keeps prev/next only when the caller offers no jump", () => {
    render(<Pagination {...base} />);
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.getByText("1 / 13")).toBeInTheDocument();
  });

  describe("jump to page", () => {
    it("goes to the page typed in", () => {
      const onPageChange = vi.fn();
      render(<Pagination {...base} onPageChange={onPageChange} />);

      const field = screen.getByRole("spinbutton");
      fireEvent.change(field, { target: { value: "13" } });
      fireEvent.blur(field);

      expect(onPageChange).toHaveBeenCalledWith(13);
    });

    it("commits on Enter as well", () => {
      const onPageChange = vi.fn();
      render(<Pagination {...base} onPageChange={onPageChange} />);

      const field = screen.getByRole("spinbutton");
      fireEvent.change(field, { target: { value: "7" } });
      fireEvent.keyDown(field, { key: "Enter" });

      expect(onPageChange).toHaveBeenCalledWith(7);
    });

    it("clamps a page past the end back onto the last one", () => {
      const onPageChange = vi.fn();
      render(<Pagination {...base} onPageChange={onPageChange} />);

      const field = screen.getByRole("spinbutton");
      fireEvent.change(field, { target: { value: "99" } });
      fireEvent.blur(field);

      expect(onPageChange).toHaveBeenCalledWith(13);
    });

    it("clamps a page below the range back onto the first one", () => {
      const onPageChange = vi.fn();
      render(<Pagination {...base} skip={150} onPageChange={onPageChange} />);

      const field = screen.getByRole("spinbutton");
      fireEvent.change(field, { target: { value: "0" } });
      fireEvent.blur(field);

      expect(onPageChange).toHaveBeenCalledWith(1);
    });

    it("ignores a value that is not a page", () => {
      const onPageChange = vi.fn();
      render(<Pagination {...base} onPageChange={onPageChange} />);

      const field = screen.getByRole("spinbutton");
      fireEvent.change(field, { target: { value: "" } });
      fireEvent.blur(field);

      expect(onPageChange).not.toHaveBeenCalled();
    });

    it("follows the page it is given", () => {
      render(<Pagination {...base} skip={150} onPageChange={vi.fn()} />);
      expect(screen.getByRole("spinbutton")).toHaveValue(4);
    });
  });

  describe("rows per page", () => {
    it("is absent unless the caller can change it", () => {
      render(<Pagination {...base} />);
      expect(screen.queryByRole("combobox")).toBeNull();
    });

    it("reports the chosen size", () => {
      const onLimitChange = vi.fn();
      render(<Pagination {...base} onLimitChange={onLimitChange} />);

      fireEvent.change(screen.getByRole("combobox"), {
        target: { value: "100" },
      });

      expect(onLimitChange).toHaveBeenCalledWith(100);
    });

    it("offers the current size even when it is not one of the presets", () => {
      render(<Pagination {...base} limit={30} onLimitChange={vi.fn()} />);
      expect(screen.getByRole("combobox")).toHaveValue("30");
    });
  });

  describe("a list that stopped counting", () => {
    const capped = { ...base, total: 10000, totalCapped: true };

    it("says there are more than it counted", () => {
      render(<Pagination {...capped} />);

      expect(screen.getByText("more than 10000")).toBeInTheDocument();
      expect(screen.getByText("1 / 200+")).toBeInTheDocument();
    });

    it("keeps next open on the last page it counted", () => {
      render(<Pagination {...capped} skip={9950} />);

      expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
    });

    it("closes next on a list that counted to its end", () => {
      render(<Pagination {...base} total={10000} skip={9950} />);

      expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    });
  });

  describe("a cursor-paged list past the count it carries", () => {
    // The journal counts once, on its first page, and every later page
    // carries that number: with a cap of 50, page two still says 50.
    const journal = { ...base, total: 50, totalCapped: true, skip: 50 };

    it("names the rows it shows, not a range that runs backwards", () => {
      render(<Pagination {...journal} keyset={{ rows: 50, hasNext: true }} />);

      expect(screen.getByText("51–100")).toBeInTheDocument();
      expect(screen.getByText("more than 100")).toBeInTheDocument();
      expect(screen.getByText("2 / 2+")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
    });

    it("ends where the cursor ends, with the count it walked", () => {
      render(<Pagination {...journal} keyset={{ rows: 20, hasNext: false }} />);

      expect(screen.getByText("51–70")).toBeInTheDocument();
      expect(screen.getByText("70")).toBeInTheDocument();
      expect(screen.getByText("2 / 2")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    });

    it("closes next on a counted page with no cursor after it", () => {
      render(
        <Pagination
          {...base}
          total={120}
          skip={50}
          keyset={{ rows: 50, hasNext: false }}
        />,
      );

      expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    });
  });
});
