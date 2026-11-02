import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PrintLayoutSelector } from "./PrintLayoutSelector";

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { default_template_id: null, print_template: "standard" },
  }),
  useUpdateDocumentProfile: () => ({ mutate: mocks.mutate, isPending: false }),
}));

const org = vi.hoisted(() => ({
  data: { tax_id: "PL1234567890", address: { street: "Prosta 1" } } as {
    tax_id?: string | null;
    address?: unknown;
  },
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useOrganization: () => ({ data: org.data }),
}));

const templates = vi.hoisted(() => ({ failed: false }));

vi.mock("@/modules/shared/hooks/useDocumentTemplates", () => ({
  useDocumentTemplates: () =>
    templates.failed
      ? {
          data: undefined,
          isError: true,
          error: new Error("boom"),
          refetch: vi.fn(),
        }
      : { data: [] },
}));

describe("PrintLayoutSelector — the choice says what it reaches", () => {
  /**
   * Saving this selector re-dresses every printout in the organization the
   * moment it lands, and nothing on screen used to say so — the difference
   * showed up on the first printed document. The selector now says what the
   * choice covers and what it does not: a template written for a document's
   * type still wins for that type.
   */
  it("names the scope of the change before anyone saves it", () => {
    render(<PrintLayoutSelector />);

    expect(
      screen.getByText(/no template of its own type/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/still wins for that type/i)).toBeInTheDocument();
  });

  it("says the templates could not be loaded instead of ending at two layouts", () => {
    templates.failed = true;
    try {
      render(<PrintLayoutSelector />);

      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /try again/i }),
      ).toBeInTheDocument();
    } finally {
      templates.failed = false;
    }
  });

  it("says the issuer block is empty, and where to fill it", () => {
    org.data = { tax_id: null, address: null };
    try {
      render(
        <MemoryRouter>
          <PrintLayoutSelector />
        </MemoryRouter>,
      );

      expect(screen.getByRole("status")).toHaveTextContent(/tax id/i);
      expect(screen.getByRole("link", { name: /settings/i })).toHaveAttribute(
        "href",
        "/settings",
      );
    } finally {
      org.data = { tax_id: "PL1234567890", address: { street: "Prosta 1" } };
    }
  });

  it("stays quiet once the issuer is filled in", () => {
    render(<PrintLayoutSelector />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("offers an automatic layout beside the two built-in ones", () => {
    render(<PrintLayoutSelector />);

    expect(
      screen.getByRole("option", { name: /automatic/i }),
    ).toBeInTheDocument();
  });
});
