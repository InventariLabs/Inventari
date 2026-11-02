import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";

import PartnerFormModal from "./PartnerFormModal";

const createMutate = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  useCreatePartner: () => ({ mutate: createMutate, isPending: false }),
  useUpdatePartner: () => ({ mutate: vi.fn(), isPending: false }),
}));

/**
 * The email and website fields leaned on the browser's own validation, which
 * speaks the operating system's language and cannot be styled or translated:
 * with the interface in English a Polish user got a Polish sentence, and an
 * app that ships five languages was handing its validation to the browser.
 */
describe("PartnerFormModal native validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderForm() {
    render(<PartnerFormModal onClose={vi.fn()} />);
    return {
      name: screen.getByLabelText(/Name/i),
      email: screen.getByLabelText(/Email/i),
      website: screen.getByLabelText(/Website/i),
      submit: screen.getByRole("button", { name: /Create|Save/i }),
    };
  }

  it("does not hand validation to the browser", () => {
    renderForm();
    const form = document.querySelector("form") as HTMLFormElement;
    expect(form).toHaveAttribute("noValidate");
  });

  it("rejects a malformed email in the interface language", () => {
    const { name, email, submit } = renderForm();

    fireEvent.change(name, { target: { value: "ACME" } });
    fireEvent.change(email, { target: { value: "to-nie-jest-email" } });
    fireEvent.click(submit);

    expect(createMutate).not.toHaveBeenCalled();
    const message = screen.getByRole("alert");
    expect(message).toHaveTextContent("Enter an email address");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining("error"),
    );
  });

  it("marks an empty name on the field and moves focus to it", () => {
    const { name, submit } = renderForm();

    fireEvent.click(submit);

    expect(createMutate).not.toHaveBeenCalled();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Name is required");
    expect(name).toHaveFocus();
  });

  it("marks a name that was typed and then deleted, without throwing", () => {
    const { name, submit } = renderForm();

    fireEvent.change(name, { target: { value: "ACME" } });
    fireEvent.change(name, { target: { value: "" } });
    fireEvent.click(submit);

    expect(createMutate).not.toHaveBeenCalled();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Name is required");
    expect(name).toHaveFocus();
  });

  it("rejects a malformed website the same way", () => {
    const { name, website, submit } = renderForm();

    fireEvent.change(name, { target: { value: "ACME" } });
    fireEvent.change(website, { target: { value: "not a url" } });
    fireEvent.click(submit);

    expect(createMutate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a web address");
  });

  it("accepts a valid email and website", () => {
    const { name, email, website, submit } = renderForm();

    fireEvent.change(name, { target: { value: "ACME" } });
    fireEvent.change(email, { target: { value: "buyer@acme.com" } });
    fireEvent.change(website, { target: { value: "https://acme.com" } });
    fireEvent.click(submit);

    expect(createMutate).toHaveBeenCalled();
  });
});

describe("PartnerFormModal private person", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("saves a partner marked as a private person", () => {
    render(<PartnerFormModal onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Name/i), {
      target: { value: "Jan Kowalski" },
    });
    fireEvent.click(screen.getByLabelText("Private person (consumer)"));
    fireEvent.click(screen.getByRole("button", { name: /Create|Save/i }));

    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Jan Kowalski", is_consumer: true }),
      expect.any(Object),
    );
  });
});
