import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authApi } from "@/lib/api/auth";
import { signInWith, signOut } from "@/test/auth";
import { logger } from "@/utils/logger";
import { useLanguagePreference } from "./useLanguagePreference";
import { takeLanguageChoice } from "@/i18n/languageChoice";
import i18next from "i18next";

/**
 * The language is saved to the account only when there is one. A visitor on
 * the sign-in screen has no session: the call would answer 401 and the
 * console would log an error for a refusal nobody should be told about.
 */
describe("useLanguagePreference", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(async () => {
    signOut();
    vi.restoreAllMocks();
    await act(async () => {
      await i18next.changeLanguage("en");
    });
  });

  it("keeps a signed-out choice local: no account call, no logged error", async () => {
    signOut();
    const save = vi.spyOn(authApi, "updateLanguage");
    const logged = vi.spyOn(logger, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useLanguagePreference());

    await act(async () => {
      await result.current.changeLanguage("pl");
    });

    expect(save).not.toHaveBeenCalled();
    expect(logged).not.toHaveBeenCalled();
    expect(result.current.language).toBe("pl");
    // …and the next sign-in still adopts it.
    expect(takeLanguageChoice()).toBe("pl");
  });

  it("saves a signed-in choice to the account", async () => {
    signInWith([]);
    const save = vi
      .spyOn(authApi, "updateLanguage")
      .mockResolvedValue(undefined as never);
    const { result } = renderHook(() => useLanguagePreference());

    await act(async () => {
      await result.current.changeLanguage("de");
    });

    expect(save).toHaveBeenCalledWith("de");
    expect(takeLanguageChoice()).toBeNull();
  });

  it("still reports a real failure of the save, and holds the choice", async () => {
    signInWith([]);
    vi.spyOn(authApi, "updateLanguage").mockRejectedValue(new Error("down"));
    const logged = vi.spyOn(logger, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useLanguagePreference());

    await act(async () => {
      await result.current.changeLanguage("fr");
    });

    expect(logged).toHaveBeenCalledOnce();
    expect(takeLanguageChoice()).toBe("fr");
  });
});
