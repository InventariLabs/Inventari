import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LabelPickerInput } from "./LabelPickerInput";

const read = vi.hoisted(() => ({
  failed: false,
  refetch: vi.fn(),
  items: [] as { id: string; short_code: string; description: string | null }[],
  generate: vi.fn(),
}));

vi.mock("@/modules/shared/hooks/useLabels", () => ({
  useLabels: () => ({
    data: read.failed ? undefined : { items: read.items },
    isLoading: false,
    isError: read.failed,
    refetch: read.refetch,
  }),
  useGenerateLabels: () => ({
    mutate: (
      vars: unknown,
      options?: { onSuccess?: (result: unknown) => void },
    ) => void read.generate(vars).then(options?.onSuccess),
    isPending: false,
  }),
}));

function openPool() {
  render(<LabelPickerInput value="" onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /no label assigned/i }));
}

describe("LabelPickerInput", () => {
  afterEach(() => {
    read.failed = false;
    read.items = [];
    read.refetch.mockClear();
    read.generate.mockReset();
  });

  it("says the pool is empty when it is", () => {
    openPool();
    expect(screen.getByText("No free labels in pool")).toBeInTheDocument();
  });

  it("does not call the pool empty when the request failed", () => {
    // "No free labels" sends the reader to print a new sheet for labels
    // that are sitting in the pool.
    read.failed = true;
    openPool();

    expect(screen.queryByText("No free labels in pool")).toBeNull();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(read.refetch).toHaveBeenCalledTimes(1);
  });

  describe("with labels in the pool", () => {
    beforeEach(() => {
      read.items = [
        { id: "1", short_code: "STM-0001", description: "Cold storage" },
        { id: "2", short_code: "STM-0002", description: null },
        { id: "3", short_code: "BOX-0007", description: "Garage shelf" },
      ];
    });

    it("narrows the pool by code or by description as the reader types", () => {
      openPool();

      fireEvent.change(screen.getByLabelText("Search labels…"), {
        target: { value: "box" },
      });
      expect(screen.getByText("BOX-0007")).toBeInTheDocument();
      expect(screen.queryByText("STM-0001")).toBeNull();

      fireEvent.change(screen.getByLabelText("Search labels…"), {
        target: { value: "cold" },
      });
      expect(screen.getByText("STM-0001")).toBeInTheDocument();
      expect(screen.queryByText("BOX-0007")).toBeNull();
    });

    it("hands back the chosen code and closes the pool", () => {
      const onChange = vi.fn();
      render(<LabelPickerInput value="" onChange={onChange} />);
      fireEvent.click(
        screen.getByRole("button", { name: /no label assigned/i }),
      );

      fireEvent.click(screen.getByRole("button", { name: /STM-0002/ }));

      expect(onChange).toHaveBeenCalledWith("STM-0002");
      expect(screen.queryByLabelText("Search labels…")).toBeNull();
    });

    it("closes the pool when the reader clicks anywhere outside it", () => {
      // A dropdown that only the trigger can close stays over the form fields
      // under it.
      openPool();
      expect(screen.getByLabelText("Search labels…")).toBeInTheDocument();

      fireEvent.mouseDown(document.body);

      expect(screen.queryByLabelText("Search labels…")).toBeNull();
    });

    it("keeps the pool open for a click inside it", () => {
      openPool();

      fireEvent.mouseDown(screen.getByLabelText("Search labels…"));

      expect(screen.getByLabelText("Search labels…")).toBeInTheDocument();
    });
  });

  describe("the label already chosen", () => {
    it("clears the choice from the x with a click, without opening the pool", () => {
      const onChange = vi.fn();
      render(<LabelPickerInput value="STM-0001" onChange={onChange} />);

      fireEvent.click(screen.getByTitle("Clear label"));

      expect(onChange).toHaveBeenCalledWith("");
      expect(screen.queryByLabelText("Search labels…")).toBeNull();
    });

    it.each(["Enter", " "])(
      "clears the choice from the keyboard with %j",
      (key) => {
        const onChange = vi.fn();
        render(<LabelPickerInput value="STM-0001" onChange={onChange} />);

        fireEvent.keyDown(screen.getByTitle("Clear label"), { key });

        expect(onChange).toHaveBeenCalledWith("");
      },
    );

    it("ignores other keys on the x", () => {
      const onChange = vi.fn();
      render(<LabelPickerInput value="STM-0001" onChange={onChange} />);

      fireEvent.keyDown(screen.getByTitle("Clear label"), { key: "a" });

      expect(onChange).not.toHaveBeenCalled();
    });

    it("offers no x on a disabled field", () => {
      render(<LabelPickerInput value="STM-0001" onChange={vi.fn()} disabled />);

      expect(screen.queryByTitle("Clear label")).toBeNull();
    });
  });

  describe("generating a label on the spot", () => {
    it("requests one item label and chooses the code it came back with", async () => {
      read.generate.mockResolvedValue([{ short_code: "STM-0099" }]);
      const onChange = vi.fn();
      render(<LabelPickerInput value="" onChange={onChange} />);

      fireEvent.click(
        screen.getByRole("button", { name: "Generate new label" }),
      );

      await waitFor(() => expect(onChange).toHaveBeenCalledWith("STM-0099"));
      expect(read.generate).toHaveBeenCalledWith({
        count: 1,
        label_type: "ITEM",
      });
    });

    it("chooses nothing when the server returned no label", async () => {
      read.generate.mockResolvedValue([]);
      const onChange = vi.fn();
      render(<LabelPickerInput value="" onChange={onChange} />);

      fireEvent.click(
        screen.getByRole("button", { name: "Generate new label" }),
      );

      await waitFor(() => expect(read.generate).toHaveBeenCalled());
      expect(onChange).not.toHaveBeenCalled();
    });
  });
});
