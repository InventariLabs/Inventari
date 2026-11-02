import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { StatusBadge } from "@/components/ui/StatusBadge";

describe("StatusBadge", () => {
  it("renders the correct variant for known statuses", () => {
    const cases = [
      { status: "DRAFT", className: "bg-surface-raised" },
      { status: "PENDING", className: "bg-amber-100" },
      { status: "ACTIVE", className: "bg-blue-100" },
      { status: "COMPLETED", className: "bg-success-100" },
      { status: "CANCELLED", className: "bg-red-100" },
    ] as const;

    for (const { status, className } of cases) {
      const { container } = render(<StatusBadge status={status} />);
      expect(container.firstChild).toHaveClass(className);
    }
  });

  it("uses the custom variants map override", () => {
    const { container } = render(
      <StatusBadge status="DRAFT" variants={{ DRAFT: "danger" }} />,
    );
    expect(container.firstChild).toHaveClass("bg-red-100");
  });

  it("uses the fallback variant for unknown statuses", () => {
    const { container } = render(
      <StatusBadge status="MYSTERY" fallbackVariant="info" />,
    );
    expect(container.firstChild).toHaveClass("bg-blue-100");
  });

  it("falls back to the default variant for unknown statuses", () => {
    const { container } = render(<StatusBadge status="MYSTERY" />);
    expect(container.firstChild).toHaveClass("bg-surface-raised");
  });

  it("shows the explicit label when provided", () => {
    render(<StatusBadge status="DRAFT" label="Custom Label" />);
    expect(screen.getByText("Custom Label")).toBeInTheDocument();
  });

  it("falls back to the status text when the i18n key is missing", () => {
    render(<StatusBadge status="MYSTERY_STATUS" />);
    expect(screen.getByText("MYSTERY_STATUS")).toBeInTheDocument();
  });

  it("passes custom className", () => {
    const { container } = render(
      <StatusBadge status="DRAFT" className="extra-class" />,
    );
    expect(container.firstChild).toHaveClass("extra-class");
  });
});
