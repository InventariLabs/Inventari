import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useAuthStore } from "@/store/authStore";
import { useIsSignedInAs } from "@/hooks/useIsSignedInAs";

describe("useIsSignedInAs", () => {
  const before = useAuthStore.getState().user;
  const signInAs = (email: string | undefined) =>
    act(() => {
      useAuthStore.setState({
        user: email === undefined ? null : ({ email } as never),
      });
    });

  afterEach(() => signInAs(before?.email));

  it("matches the signed-in address without regard to case", () => {
    signInAs("Kasia@Firma.example");
    const { result } = renderHook(() => useIsSignedInAs("kasia@firma.example"));
    expect(result.current).toBe(true);
  });

  it("is false for another address, an absent one, or nobody signed in", () => {
    signInAs("kasia@firma.example");
    expect(
      renderHook(() => useIsSignedInAs("piotr@firma.example")).result.current,
    ).toBe(false);
    expect(renderHook(() => useIsSignedInAs(null)).result.current).toBe(false);
    signInAs(undefined);
    expect(
      renderHook(() => useIsSignedInAs("kasia@firma.example")).result.current,
    ).toBe(false);
  });
});
