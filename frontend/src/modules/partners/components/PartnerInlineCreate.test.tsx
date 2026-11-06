import React, { act } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { PartnerInlineCreate } from "./PartnerInlineCreate";
import { CUSTOMER_ROLE_TYPES } from "../partnerRoles";
import * as partnerHooks from "@/modules/partners/hooks/usePartners";

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  useCreatePartner: vi.fn(),
}));

const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: vi.fn(),
  },
}));

const mockMutate = vi.fn();

function getActionButton() {
  return screen.getByTestId("partner-inline-create-submit");
}

describe("PartnerInlineCreate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(partnerHooks.useCreatePartner).mockReturnValue({
      mutate: mockMutate,
      isPending: false,
    } as unknown as ReturnType<typeof partnerHooks.useCreatePartner>);
  });

  it("renders form with name input and type select", () => {
    render(
      <PartnerInlineCreate
        initialName=""
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByPlaceholderText("e.g. ABC Wholesaler"),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("hands the focus back to the field that opened it when Cancel closes it", async () => {
    // The layer unmounts while Cancel holds the focus; the page body then has
    // it, outside the dialog the layer sits in.
    const user = userEvent.setup();
    function Host() {
      const [open, setOpen] = React.useState(true);
      return (
        <div>
          <button id="partner-field">Partner</button>
          {open && (
            <PartnerInlineCreate
              initialName=""
              onCreated={vi.fn()}
              onCancel={() => setOpen(false)}
              returnFocusId="partner-field"
            />
          )}
        </div>
      );
    }
    render(<Host />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("partner-inline-create-submit")).toBeNull();
    await act(
      () =>
        new Promise<void>((done) =>
          requestAnimationFrame(() => requestAnimationFrame(() => done())),
        ),
    );

    expect(document.activeElement).toBe(screen.getByText("Partner"));
  });

  it("takes focus into the name and brings the layer into view", () => {
    // The layer opens under the field that asked for it — below the fold on a
    // short window — and the click that opened it read as dead.
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    render(
      <PartnerInlineCreate
        initialName="ACME"
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    expect(screen.getByPlaceholderText("e.g. ABC Wholesaler")).toHaveFocus();
  });

  it("pre-fills name from initialName prop", () => {
    render(
      <PartnerInlineCreate
        initialName="ACME Corp"
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("e.g. ABC Wholesaler")).toHaveValue(
      "ACME Corp",
    );
  });

  // A dispatch form's recipient picker lists customers only, so the layer
  // opened from it has to start on a role the picker will accept — a
  // supplier created there was set as the field's value and the field went
  // on looking empty while the form treated it as filled.
  // Measurement note: this test alone does not bite the default-type line —
  // with the default re-hardened to "SUPPLIER" but the options still
  // narrowed, a jsdom select with no SUPPLIER option falls back to the first
  // option and the value still reads "CUSTOMER". It goes red only as the
  // pair (narrowed options + default): with the old QUICK_TYPES the SUPPLIER
  // option exists and wins. The default line's own guard is the options
  // test below.
  it("starts on the first role the calling field accepts, not on supplier", () => {
    render(
      <PartnerInlineCreate
        initialName=""
        roleTypes={CUSTOMER_ROLE_TYPES}
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox")).toHaveValue("CUSTOMER");
  });

  it("offers no role the calling field would refuse", () => {
    render(
      <PartnerInlineCreate
        initialName=""
        roleTypes={CUSTOMER_ROLE_TYPES}
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const values = screen
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(["CUSTOMER", "BOTH"]);
  });

  it("calls createMutation on submit with name and type", async () => {
    const user = userEvent.setup();

    render(
      <PartnerInlineCreate
        initialName="New Supplier"
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await act(async () => {
      await user.click(getActionButton());
    });

    expect(mockMutate).toHaveBeenCalledWith(
      {
        name: "New Supplier",
        type: "SUPPLIER",
        tax_id: null,
        is_consumer: false,
      },
      expect.any(Object),
    );
  });

  it("calls onCreated with partner id after successful creation", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();

    vi.mocked(partnerHooks.useCreatePartner).mockReturnValue({
      mutate: (
        _data: unknown,
        options: {
          onSuccess: (p: { id: string; name: string; type: string }) => void;
        },
      ) => {
        options.onSuccess({
          id: "new-partner-1",
          name: "Test",
          type: "SUPPLIER",
        });
      },
      isPending: false,
    } as unknown as ReturnType<typeof partnerHooks.useCreatePartner>);

    render(
      <PartnerInlineCreate
        initialName="Test"
        onCreated={onCreated}
        onCancel={vi.fn()}
      />,
    );

    await act(async () => {
      await user.click(getActionButton());
    });

    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ id: "new-partner-1", type: "SUPPLIER" }),
    );
  });

  it("calls onCancel when cancel button clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();

    render(
      <PartnerInlineCreate
        initialName=""
        onCreated={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /Cancel/i }));
    });

    expect(onCancel).toHaveBeenCalled();
  });

  it("disables submit when name is empty", () => {
    render(
      <PartnerInlineCreate
        initialName=""
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(getActionButton()).toBeDisabled();
  });

  it("confirms creation with a sentence that names what is missing", async () => {
    const user = userEvent.setup();

    vi.mocked(partnerHooks.useCreatePartner).mockReturnValue({
      mutate: (
        _data: unknown,
        options: { onSuccess: (p: { id: string; name: string }) => void },
      ) => {
        options.onSuccess({ id: "new-partner-1", name: "New Supplier" });
      },
      isPending: false,
    } as unknown as ReturnType<typeof partnerHooks.useCreatePartner>);

    render(
      <PartnerInlineCreate
        initialName="New Supplier"
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await act(async () => {
      await user.click(getActionButton());
    });

    expect(toastSuccess).toHaveBeenCalledWith(
      'Partner "New Supplier" created. Add their tax ID and address before issuing a document with an address.',
    );
  });
});

describe("PartnerInlineCreate (nested-form guard)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(partnerHooks.useCreatePartner).mockReturnValue({
      mutate: mockMutate,
      isPending: false,
    } as unknown as ReturnType<typeof partnerHooks.useCreatePartner>);
  });

  it("does not render a <form> element (avoids invalid nested <form>)", () => {
    const { container } = render(
      <PartnerInlineCreate
        initialName=""
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(container.querySelector("form")).toBeNull();
  });

  it("primary action button has type='button' to avoid submitting a parent form", () => {
    render(
      <PartnerInlineCreate
        initialName="ACME"
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const actionButton = getActionButton();
    expect(actionButton).toHaveAttribute("type", "button");
  });

  it("pressing Enter in the name input creates the partner without submitting a parent form (data survived)", async () => {
    const user = userEvent.setup();
    const parentOnSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());

    render(
      <form onSubmit={parentOnSubmit}>
        <input data-testid="parent-field" defaultValue="kept" />
        <PartnerInlineCreate
          initialName="Quick Supplier"
          onCreated={vi.fn()}
          onCancel={vi.fn()}
        />
      </form>,
    );

    const nameInput = screen.getByPlaceholderText("e.g. ABC Wholesaler");
    await act(async () => {
      nameInput.focus();
      await user.keyboard("{Enter}");
    });

    expect(mockMutate).toHaveBeenCalledWith(
      {
        name: "Quick Supplier",
        type: "SUPPLIER",
        tax_id: null,
        is_consumer: false,
      },
      expect.any(Object),
    );
    expect(parentOnSubmit).not.toHaveBeenCalled();
    expect(screen.getByTestId("parent-field")).toHaveValue("kept");
  });

  it("takes a tax ID and a private person without leaving the document", async () => {
    // A Polish or German organization confirms a document only once its
    // partner has a tax ID or is a private person; the quick form asked for
    // neither, so the dispatch could not be confirmed from where it began.
    const user = userEvent.setup();
    render(
      <PartnerInlineCreate
        initialName="Jan Kowalski"
        roleTypes={CUSTOMER_ROLE_TYPES}
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await act(async () => {
      await user.type(screen.getByLabelText("Tax ID / VAT"), " PL123 ");
      await user.click(screen.getByLabelText("Private person (consumer)"));
      await user.click(getActionButton());
    });

    expect(mockMutate).toHaveBeenCalledWith(
      {
        name: "Jan Kowalski",
        type: "CUSTOMER",
        tax_id: "PL123",
        is_consumer: true,
      },
      expect.any(Object),
    );
  });
});
