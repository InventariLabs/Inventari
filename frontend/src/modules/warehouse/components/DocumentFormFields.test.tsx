import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@/test/utils";
import { DocumentFormFields } from "./DocumentFormFields";
import { serveLocations } from "@/test/serveLocations";
import type { DocumentType } from "@/modules/warehouse/types";

const partnerOptions = { loading: false, failed: false };

vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    options,
    value,
    onChange,
    placeholder,
    title,
    createLabel,
    onCreateNew,
    label,
    required,
    loading,
  }: {
    options: { id: string; name: string; path?: string }[];
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
    title?: string;
    createLabel?: string;
    onCreateNew?: (query: string) => void;
    label?: string;
    required?: boolean;
    loading?: boolean;
  }) => (
    <div>
      {label && (
        <span>
          {label}
          {/* the star sits beside the label text, aria-hidden, so it
              never enters the accessible name. */}
          {required && <span aria-hidden="true">*</span>}
        </span>
      )}
      <select
        aria-label={title ?? placeholder ?? "searchable-combobox"}
        aria-required={required || undefined}
        data-loading={loading ? "true" : undefined}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      {onCreateNew && createLabel && (
        <button type="button" onClick={() => onCreateNew("")}>
          {createLabel}
        </button>
      )}
    </div>
  ),
}));

const baseProps = {
  docType: "IN" as DocumentType,
  partnerId: "",
  sourceLocationId: "",
  targetLocationId: "",
  scheduledDate: "",
  externalReference: "",
  notes: "",
  requiresPartner: true,
  requiresSource: false,
  requiresTarget: true,
  partners: [
    { id: "p1", name: "ACME" },
    { id: "p2", name: "Beta Corp" },
  ],
  errors: {},
  onPartnerIdChange: vi.fn(),
  onSourceLocationIdChange: vi.fn(),
  onTargetLocationIdChange: vi.fn(),
  onScheduledDateChange: vi.fn(),
  onExternalReferenceChange: vi.fn(),
  onNotesChange: vi.fn(),
};

function renderFields() {
  render(
    <DocumentFormFields
      {...baseProps}
      onPartnerCreate={vi.fn()}
      partnersLoading={partnerOptions.loading}
      partnersError={partnerOptions.failed ? new Error("boom") : null}
      retryPartners={vi.fn()}
    />,
  );
}

describe("DocumentFormFields", () => {
  beforeEach(() => {
    partnerOptions.loading = false;
    partnerOptions.failed = false;
    serveLocations([
      { id: "l1", name: "Receiving" },
      { id: "l2", name: "Shelf A" },
    ]);
  });

  it("says the partners could not be loaded instead of showing an empty picker", () => {
    partnerOptions.failed = true;
    renderFields();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("tells the partner picker while the partner list is still on its way", () => {
    partnerOptions.loading = true;
    renderFields();

    // The picker must not offer to create a partner the list may be about to
    // show: it is told the list is loading.
    expect(screen.getByLabelText("Partner")).toHaveAttribute(
      "data-loading",
      "true",
    );
  });

  it("does not hold the picker back once the partner list has arrived", () => {
    renderFields();

    expect(screen.getByLabelText("Partner")).not.toHaveAttribute(
      "data-loading",
    );
  });

  it("shows partner field for IN document", () => {
    render(<DocumentFormFields {...baseProps} />);
    expect(screen.getByText("Partner")).toBeInTheDocument();
  });

  it("hides partner field for INT document", () => {
    render(
      <DocumentFormFields
        {...baseProps}
        docType="INT"
        requiresPartner={false}
      />,
    );
    expect(screen.queryByText("Partner")).not.toBeInTheDocument();
  });

  it("shows target location select when requiresTarget", () => {
    render(<DocumentFormFields {...baseProps} />);
    expect(screen.getByLabelText("To location")).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("hides target location when requiresTarget is false", () => {
    render(<DocumentFormFields {...baseProps} requiresTarget={false} />);
    expect(screen.queryByLabelText("To location")).not.toBeInTheDocument();
  });

  it("shows source location select when requiresSource", () => {
    render(
      <DocumentFormFields
        {...baseProps}
        docType="OUT"
        requiresSource={true}
        requiresTarget={false}
      />,
    );
    expect(screen.getByLabelText("From location")).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("hides source location when requiresSource is false", () => {
    render(<DocumentFormFields {...baseProps} />);
    expect(screen.queryByLabelText("From location")).not.toBeInTheDocument();
  });

  it("shows required asterisk on partner when requiresPartner", () => {
    render(<DocumentFormFields {...baseProps} requiresPartner={true} />);
    // The label's own text stays clean — the star is a hidden sibling.
    const label = screen.getByText("Partner");
    expect(label.textContent).toContain("*");
  });

  it("renders notes textarea", () => {
    render(<DocumentFormFields {...baseProps} />);
    expect(screen.getByText("Notes")).toBeInTheDocument();
  });

  it("renders scheduled date input", () => {
    render(<DocumentFormFields {...baseProps} />);
    expect(screen.getByText("Scheduled date")).toBeInTheDocument();
  });

  it("renders external reference input", () => {
    render(<DocumentFormFields {...baseProps} />);
    expect(
      screen.getByText("Reference / related document"),
    ).toBeInTheDocument();
  });

  it("filters out source location from target dropdown when both required", async () => {
    render(
      <DocumentFormFields
        {...baseProps}
        docType="INT"
        requiresSource={true}
        requiresTarget={true}
        requiresPartner={false}
        sourceLocationId="l1"
      />,
    );
    const select = screen.getByLabelText("To location");
    await within(select).findByText("Shelf A");
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).not.toContain("Receiving");
    expect(options).toContain("Shelf A");
  });

  it("renders create new partner button when onPartnerCreate is provided", () => {
    const onPartnerCreate = vi.fn();
    render(
      <DocumentFormFields {...baseProps} onPartnerCreate={onPartnerCreate} />,
    );
    expect(screen.getByText("+ Create new partner")).toBeInTheDocument();
  });

  it("calls onPartnerCreate when create button clicked", () => {
    const onPartnerCreate = vi.fn();
    render(
      <DocumentFormFields {...baseProps} onPartnerCreate={onPartnerCreate} />,
    );
    screen.getByText("+ Create new partner").click();
    expect(onPartnerCreate).toHaveBeenCalled();
  });

  // With the Partners module disabled, show a notice instead of a dead
  // empty picker and do not mark partner as required.
  it("shows an enable-partners notice instead of the picker when module disabled", () => {
    render(
      <DocumentFormFields
        {...baseProps}
        partnersModuleDisabled
        onPartnerCreate={vi.fn()}
      />,
    );
    expect(screen.getByText("Enable partners")).toBeInTheDocument();
    // On the inset surface the ramp's 600 step is 2.96:1 in light and 3.28:1
    // in dark; 800 (5.98:1) and the brand-text token (6.66:1) clear 4.5:1.
    const link = screen.getByRole("link", { name: "Enable partners" });
    expect(link).toHaveClass("text-primary-800", "dark:text-on-primary");
    expect(link).not.toHaveClass("text-primary-600");
    // Notice body text rendered.
    expect(screen.getByText(/Enable the Partners module/i)).toBeInTheDocument();
    // No "+ Create new partner" dead action.
    expect(screen.queryByText("+ Create new partner")).not.toBeInTheDocument();
  });

  it("asks a scrap why, with the note the reason owns", async () => {
    const onReasonCodeChange = vi.fn();
    const user = (await import("@testing-library/user-event")).default.setup();
    render(
      <DocumentFormFields
        {...baseProps}
        docType="SCRAP"
        requiresPartner={false}
        scrapReason={{ code: "", setCode: onReasonCodeChange }}
        errors={{ reason_code: "reasons.codeRequired" }}
      />,
    );

    const reason = screen.getByTestId("scrap-reason-code");
    await user.selectOptions(reason, "EXPIRED");

    expect(onReasonCodeChange).toHaveBeenCalledWith("EXPIRED");
    // Nothing chosen yet, and the reader has tried to save.
    expect(screen.getByText("Pick a reason")).toBeInTheDocument();
  });

  it("offers no reason on a receipt", () => {
    render(
      <DocumentFormFields
        {...baseProps}
        scrapReason={{ code: "", setCode: vi.fn() }}
      />,
    );

    expect(screen.queryByTestId("scrap-reason-code")).not.toBeInTheDocument();
  });
});
