import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import { toast } from "sonner";
import PartnerFormModal from "./PartnerFormModal";
import type { Partner } from "@/types";

type MutateOptions = {
  onSuccess: () => void;
  onError: (err: unknown) => void;
};
const createMutate = vi.fn();
const updateMutate = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  useCreatePartner: () => ({ mutate: createMutate, isPending: false }),
  useUpdatePartner: () => ({ mutate: updateMutate, isPending: false }),
}));

const PARTNER = {
  id: "partner-1",
  name: "ACME",
  type: "SUPPLIER",
  code: "AC",
  tax_id: null,
  is_consumer: false,
  email: "buyer@acme.com",
  phone: null,
  website: null,
  contact_person: null,
  address: { city: "Gdańsk" },
  notes: null,
  is_active: true,
} as unknown as Partner;

const field = (label: RegExp | string) => screen.getByLabelText(label);
const change = (label: RegExp | string, value: string) =>
  fireEvent.change(field(label), { target: { value } });
const submit = () =>
  fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

/**
 * The partner form sends the optional fields trimmed, with blank ones
 * as null and an address only when one of its fields is filled; it closes
 * only on success and toasts the server's refusal. A payload that kept
 * whitespace, sent an empty address object, or closed the form on a failed
 * save fails here.
 */
describe("PartnerFormModal — what a save sends", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a partner with the optional fields trimmed and the address kept", () => {
    const onClose = vi.fn();
    render(<PartnerFormModal onClose={onClose} />);
    change(/^Name/, "  Cold Storage Co  ");
    change(/^Type/, "MANUFACTURER");
    change(/Tax ID/, " PL123 ");
    change(/Partner Code/, " CS ");
    change(/^Phone/, " 555 ");
    change(/^Website/, "https://cold.example");
    change(/Contact Person/, " Ann ");
    change(/Internal Notes/, " night deliveries ");
    change(/^Street/, "Long 1");
    change(/Postal Code/, "80-001");
    change(/^City/, "Gdańsk");
    fireEvent.click(screen.getByLabelText(/Private person/));
    submit();

    expect(createMutate).toHaveBeenCalledOnce();
    const [payload, options] = createMutate.mock.calls[0] as [
      Record<string, unknown>,
      MutateOptions,
    ];
    expect(payload).toMatchObject({
      // The name alone goes as typed, and the server does not trim it
      // either: this pins today's behaviour, not the wanted one.
      name: "  Cold Storage Co  ",
      type: "MANUFACTURER",
      tax_id: "PL123",
      code: "CS",
      phone: "555",
      website: "https://cold.example",
      contact_person: "Ann",
      notes: "night deliveries",
      email: null,
      is_consumer: true,
      address: { street: "Long 1", postal_code: "80-001", city: "Gdańsk" },
    });

    expect(onClose).not.toHaveBeenCalled();
    options.onSuccess();
    expect(toast.success).toHaveBeenCalledWith("Partner created");
    expect(onClose).toHaveBeenCalled();
  });

  it("toasts a refused create and keeps the form open", () => {
    const onClose = vi.fn();
    render(<PartnerFormModal onClose={onClose} />);
    change(/^Name/, "ACME");
    submit();
    const options = createMutate.mock.calls[0][1] as MutateOptions;
    options.onError(new Error("network"));
    expect(toast.error).toHaveBeenCalledWith("Failed to create partner");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sends no address when every address field was emptied", () => {
    render(<PartnerFormModal partner={PARTNER} onClose={vi.fn()} />);
    change(/^City/, "");
    submit();
    const [arg] = updateMutate.mock.calls[0] as [
      { id: string; data: Record<string, unknown> },
    ];
    expect(arg.id).toBe("partner-1");
    expect(arg.data.address).toBeNull();
  });

  it("updates the partner it opened, says so and closes; a refusal keeps it open", () => {
    const onClose = vi.fn();
    render(<PartnerFormModal partner={PARTNER} onClose={onClose} />);
    change(/^Name/, "ACME Ltd");
    submit();
    const [arg, options] = updateMutate.mock.calls[0] as [
      { id: string; data: Record<string, unknown> },
      MutateOptions,
    ];
    expect(arg).toMatchObject({
      id: "partner-1",
      data: { name: "ACME Ltd", email: "buyer@acme.com", code: "AC" },
    });
    expect(createMutate).not.toHaveBeenCalled();

    options.onError(new Error("network"));
    expect(toast.error).toHaveBeenCalledWith("Failed to save partner");
    expect(onClose).not.toHaveBeenCalled();
    options.onSuccess();
    expect(toast.success).toHaveBeenCalledWith("Partner saved");
    expect(onClose).toHaveBeenCalled();
  });

  it("refuses a nameless partner", () => {
    render(<PartnerFormModal onClose={vi.fn()} />);
    submit();
    expect(createMutate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Name is required");
  });

  it("clears an email error as soon as the field is edited again", () => {
    render(<PartnerFormModal onClose={vi.fn()} />);
    change(/^Name/, "ACME");
    change(/^Email/, "nope");
    submit();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    change(/^Email/, "nope@acme.com");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("asks an employee for a position instead of a contact, and hides the address", () => {
    render(<PartnerFormModal onClose={vi.fn()} />);
    change(/^Type/, "EMPLOYEE");
    expect(field(/Full Name/)).toBeInTheDocument();
    expect(field(/Position/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Street/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Tax ID/)).not.toBeInTheDocument();
  });

  it("folds the address away and back, and closes on Cancel and on the close button", () => {
    const onClose = vi.fn();
    render(<PartnerFormModal onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /Address/ }));
    expect(screen.queryByLabelText(/^Street/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Address/ }));
    expect(field(/^Street/)).toBeInTheDocument();
    change(/^Country/, "PL");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
