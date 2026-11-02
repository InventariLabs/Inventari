import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { useMoney } from "@/hooks/useMoney";
import { QueryWrapper } from "@/test/queryWrapper";

/** Intl separates a currency code from the number with a non-breaking space. */
const plain = (text: string) => text.replace(/\u00a0/g, " ");

describe("useMoney", () => {
  it("writes the amount in the organization's currency without being told", async () => {
    const { result } = renderHook(() => useMoney(), { wrapper: QueryWrapper });

    // Before the organization answers there is no currency to name, and the
    // formatter says so rather than passing a bare number off as an amount.
    expect(plain(result.current(30))).toBe("30.00 ?");

    await waitFor(() => expect(plain(result.current(30))).toBe("PLN 30.00"));
  });

  it("lets an amount that carries its own currency keep it", async () => {
    const { result } = renderHook(() => useMoney(), { wrapper: QueryWrapper });

    await waitFor(() =>
      expect(plain(result.current(30, "EUR"))).toBe("€30.00"),
    );
  });

  it("renders a missing amount as a dash, not as zero", () => {
    const { result } = renderHook(() => useMoney(), { wrapper: QueryWrapper });

    expect(result.current(null)).toBe("—");
  });
});
