import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import FieldBuilder, {
  useFieldBuilderCommit,
} from "@/components/ui/FieldBuilder";
import type { FieldDefinition } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The host of a field builder, reduced to what the three real ones share: a
 * list of fields in state and a Save that reads what the builder settles.
 */
function Host({
  initial = [],
  onSave,
}: {
  initial?: FieldDefinition[];
  onSave: (fields: FieldDefinition[]) => void;
}) {
  const [fields, setFields] = useState<FieldDefinition[]>(initial);
  const builder = useFieldBuilderCommit(fields);
  return (
    <div>
      <FieldBuilder
        commitRef={builder.ref}
        fields={fields}
        onChange={setFields}
        defaultOpen
      />
      <button
        type="button"
        onClick={() => {
          const settled = builder.commit();
          if (settled) onSave(settled);
        }}
      >
        Save form
      </button>
    </div>
  );
}

const threadSize: FieldDefinition = {
  key: "thread_size",
  label: "Thread size",
  type: "text",
  required: false,
  is_system: false,
  visible: true,
  placeholder: null,
};

const type = (label: string) => {
  fireEvent.click(screen.getByRole("button", { name: /add custom field/i }));
  fireEvent.change(screen.getByLabelText("Field label"), {
    target: { value: label },
  });
};

describe("FieldBuilder — a field typed but not confirmed", () => {
  beforeEach(() => vi.clearAllMocks());

  it("is added to what the form saves", () => {
    const onSave = vi.fn();
    render(<Host onSave={onSave} />);

    type("Thread size");
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toEqual([
      expect.objectContaining({
        key: "thread_size",
        label: "Thread size",
        type: "text",
        is_system: false,
      }),
    ]);
  });

  it("is listed once the form has saved, with the add form closed", () => {
    render(<Host onSave={vi.fn()} />);

    type("Thread size");
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(screen.getByText("Thread size")).toBeInTheDocument();
    expect(screen.queryByLabelText("Field label")).not.toBeInTheDocument();
  });

  it("stops the save when the field is unfinished, and says what is missing", () => {
    const onSave = vi.fn();
    render(<Host onSave={onSave} />);

    type("Thread size");
    fireEvent.change(screen.getByLabelText("Data type"), {
      target: { value: "select" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledTimes(1);
    // The unfinished form stays open for the reader to complete.
    expect(screen.getByLabelText("Field label")).toHaveValue("Thread size");
  });

  it("stops the save when the key is taken by a field already there", () => {
    const onSave = vi.fn();
    render(
      <Host
        onSave={onSave}
        initial={[
          {
            key: "thread_size",
            label: "Thread size",
            type: "text",
            required: false,
            is_system: false,
            visible: true,
            placeholder: null,
          },
        ]}
      />,
    );

    type("Thread size");
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("saves the fields as they are when the add form holds nothing", () => {
    const onSave = vi.fn();
    render(<Host onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: /add custom field/i }));
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(onSave).toHaveBeenCalledWith([]);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("applies an edit the reader did not confirm with the row's Save", () => {
    const onSave = vi.fn();
    render(
      <Host
        onSave={onSave}
        initial={[
          {
            key: "thread_size",
            label: "Thread size",
            type: "text",
            required: false,
            is_system: false,
            visible: true,
            placeholder: null,
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByText("Thread size"));
    fireEvent.change(screen.getByLabelText("Field label"), {
      target: { value: "Thread pitch" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(onSave.mock.calls[0][0]).toEqual([
      expect.objectContaining({ key: "thread_size", label: "Thread pitch" }),
    ]);
  });

  it("stops the save when an edit leaves a dropdown without options", () => {
    const onSave = vi.fn();
    render(<Host onSave={onSave} initial={[threadSize]} />);

    fireEvent.click(screen.getByText("Thread size"));
    fireEvent.change(screen.getByLabelText("Data type"), {
      target: { value: "select" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      "This field type requires at least one option",
    );
    // The edit stays open for the reader to add the options.
    expect(screen.getByLabelText("Data type")).toHaveValue("select");
  });
});

describe("FieldBuilder — the edit form's own Save", () => {
  beforeEach(() => vi.clearAllMocks());

  it("refuses a dropdown without options and keeps the field as it was", () => {
    const onSave = vi.fn();
    render(<Host onSave={onSave} initial={[threadSize]} />);

    fireEvent.click(screen.getByText("Thread size"));
    fireEvent.change(screen.getByLabelText("Data type"), {
      target: { value: "multi-select" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(toast.error).toHaveBeenCalledWith(
      "This field type requires at least one option",
    );
    expect(screen.getByLabelText("Data type")).toHaveValue("multi-select");
  });
});
