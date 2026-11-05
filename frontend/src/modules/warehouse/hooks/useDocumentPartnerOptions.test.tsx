import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePartner, usePartners } from "@/hooks/usePartners";
import { useDocumentPartnerOptions } from "./useDocumentPartnerOptions";

vi.mock("@/hooks/usePartners", () => ({
  usePartners: vi.fn(),
  usePartner: vi.fn(),
}));

const supplier = {
  id: "supplier-1",
  name: "Hurtownia Północ",
  type: "SUPPLIER",
  is_active: true,
};

function typesAsked() {
  return vi.mocked(usePartners).mock.lastCall?.[0]?.types;
}

describe("useDocumentPartnerOptions", () => {
  beforeEach(() => {
    vi.mocked(usePartners).mockReturnValue({
      data: { items: [] },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof usePartners>);
    vi.mocked(usePartner).mockReturnValue({
      data: supplier,
      isError: false,
    } as unknown as ReturnType<typeof usePartner>);
  });

  it("offers customers on an ordinary issue and suppliers on a receipt", () => {
    renderHook(() => useDocumentPartnerOptions({ type: "OUT" }));
    expect(typesAsked()).toEqual(["CUSTOMER", "BOTH"]);

    renderHook(() => useDocumentPartnerOptions({ type: "IN" }));
    expect(typesAsked()).toEqual(["SUPPLIER", "BOTH", "MANUFACTURER"]);
  });

  it("offers suppliers on the return of a receipt, and accepts the one it holds", () => {
    const { result } = renderHook(() =>
      useDocumentPartnerOptions(
        { type: "OUT", return_of_id: "receipt-1" },
        supplier.id,
      ),
    );

    expect(typesAsked()).toEqual(["SUPPLIER", "BOTH", "MANUFACTURER"]);
    expect(result.current.selectedPartnerOffered).toBe(true);
    expect(result.current.fieldProps.partners).toContainEqual(
      expect.objectContaining({ id: supplier.id, name: supplier.name }),
    );
  });

  it("offers customers on the return of a delivery", () => {
    renderHook(() =>
      useDocumentPartnerOptions({ type: "IN", return_of_id: "issue-1" }),
    );

    expect(typesAsked()).toEqual(["CUSTOMER", "BOTH"]);
  });

  it("names a saved partner on the detail page whatever its role", () => {
    const { result } = renderHook(() =>
      useDocumentPartnerOptions({ type: "OUT", partner_id: supplier.id }),
    );

    expect(result.current.fieldProps.partners).toContainEqual(
      expect.objectContaining({ id: supplier.id, name: supplier.name }),
    );
  });
});
