import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import type { ReactNode } from "react";
import { useProfileTheme, resolveProfileThemeForMode } from "./useProfileTheme";
import { useThemeStore } from "@/store/themeStore";
import type { Organization, ProductProfile } from "@/types";
import { onePage } from "@/test/mocks/page";

const foodProfile: ProductProfile = {
  id: "food_home",
  name: "Food & Home",
  description: "",
  default_modules: ["items"],
  seed_profile: "food_home",
  theme: {
    "--color-accent-500": "16 185 129",
    "--color-accent-600": "5 150 105",
  },
};

const equipmentProfile: ProductProfile = {
  id: "equipment_wms",
  name: "Equipment & Warehouse",
  description: "",
  default_modules: ["equipment"],
  seed_profile: "equipment_wms",
  theme: {
    "--color-accent-500": "59 130 246",
    "--color-accent-600": "37 99 235",
  },
};

// Every shipped profile declares a theme. A profile with none is one from
// outside this distribution — the branch that has to restore the originals
// rather than leave the previous profile's paint on the document.
const themelessProfile: ProductProfile = {
  id: "vineyard_ops",
  name: "Vineyard Ops",
  description: "",
  default_modules: ["items"],
  seed_profile: "vineyard_ops",
  theme: null,
};

const profiles = [foodProfile, equipmentProfile, themelessProfile];

function makeOrg(activeProfileId: string | null): Organization {
  return {
    can_send_email: false,
    timezone: "UTC",
    currency: "PLN",
    id: "org-1",
    name: "Test",
    created_at: new Date().toISOString(),
    created_by: null,
    settings: null,
    active_profile_id: activeProfileId,
    onboarding_completed: true,
  };
}

function setActiveProfile(profileId: string | null) {
  server.use(
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json(makeOrg(profileId)),
    ),
  );
}

const accent = (name: string) =>
  document.documentElement.style.getPropertyValue(name);

describe("useProfileTheme", () => {
  let qc: QueryClient;

  beforeEach(() => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    );
    setActiveProfile("food_home");
    document.documentElement.style.removeProperty("--color-accent-500");
    document.documentElement.style.removeProperty("--color-accent-600");
    qc = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  function renderTheme() {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    return renderHook(() => useProfileTheme(), { wrapper });
  }

  it("applies the active profile's palette on <html>", async () => {
    renderTheme();
    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("16 185 129");
    });
    expect(accent("--color-accent-600")).toBe("5 150 105");
  });

  it("switches the palette when the profile changes (no reload)", async () => {
    renderTheme();
    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("16 185 129");
    });

    // Simulate the demo switch: profile switch endpoint + invalidation.
    setActiveProfile("equipment_wms");
    qc.invalidateQueries({ queryKey: ["organization"] });

    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("59 130 246");
    });
    expect(accent("--color-accent-600")).toBe("37 99 235");
  });

  it("restores original values for a profile without a theme", async () => {
    // Pre-existing value (e.g. left over from a module theme).
    document.documentElement.style.setProperty(
      "--color-accent-500",
      "128 128 128",
    );
    renderTheme();
    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("16 185 129");
    });

    setActiveProfile("vineyard_ops");
    qc.invalidateQueries({ queryKey: ["organization"] });

    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("128 128 128");
    });
  });

  it("restores originals on unmount", async () => {
    document.documentElement.style.setProperty(
      "--color-accent-500",
      "128 128 128",
    );
    const { unmount } = renderTheme();
    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("16 185 129");
    });

    unmount();
    expect(accent("--color-accent-500")).toBe("128 128 128");
  });

  it("wins over a module theme applied earlier (profile applied last)", async () => {
    // Simulate a module theme having applied its palette first.
    document.documentElement.style.setProperty(
      "--color-accent-500",
      "99 102 241",
    );
    renderTheme();
    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("16 185 129");
    });
  });

  it("does nothing when no profile is active", async () => {
    setActiveProfile(null);
    renderTheme();
    // Give the queries time to settle, then assert nothing was applied.
    await waitFor(() => {
      expect(accent("--color-accent-500")).toBe("");
    });
  });

  it("applies primary-ramp variables on <html> and restores them on cleanup", async () => {
    // Profiles now also override the
    // --color-primary-* ramp, so the whole action palette repaints.
    const primaryProfile: ProductProfile = {
      ...foodProfile,
      id: "primary_profile",
      theme: {
        "--color-primary-500": "16 185 129",
        "--color-primary-600": "5 150 105",
      },
    };
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(onePage([...profiles, primaryProfile])),
      ),
    );
    const primary = (name: string) =>
      document.documentElement.style.getPropertyValue(name);
    document.documentElement.style.setProperty(
      "--color-primary-500",
      "128 128 128",
    );
    setActiveProfile("primary_profile");

    const { unmount } = renderTheme();
    await waitFor(() => {
      expect(primary("--color-primary-500")).toBe("16 185 129");
    });
    expect(primary("--color-primary-600")).toBe("5 150 105");

    unmount();
    expect(primary("--color-primary-500")).toBe("128 128 128");
    document.documentElement.style.removeProperty("--color-primary-500");
  });

  it("remaps tint steps in dark mode so text steps keep contrast", async () => {
    const rampProfile: ProductProfile = {
      ...equipmentProfile,
      id: "ramp_profile",
      theme: {
        "--color-accent-100": "219 234 254",
        "--color-accent-400": "96 165 250",
        "--color-accent-700": "29 78 216",
        "--color-accent-900": "30 58 138",
        "--color-accent-50": "239 246 255",
      },
    };
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(onePage([...profiles, rampProfile])),
      ),
    );
    setActiveProfile("ramp_profile");
    act(() => {
      useThemeStore.getState().setMode("dark");
    });

    try {
      renderTheme();
      await waitFor(() => {
        // 700 (text step) takes the 400 value in dark mode.
        expect(accent("--color-accent-700")).toBe("96 165 250");
      });
      // Low tints take the ramp's dark end — 100 among them, the step the
      // shell's avatar paints on (with resolved once stuck on "light" the
      // light 219 234 254 landed on a dark background).
      expect(accent("--color-accent-100")).toBe("30 58 138");
      expect(accent("--color-accent-50")).toBe("30 58 138");

      // Toggling back to light restores the declared light ramp.
      act(() => {
        useThemeStore.getState().setMode("light");
      });
      await waitFor(() => {
        expect(accent("--color-accent-700")).toBe("29 78 216");
      });
      expect(accent("--color-accent-100")).toBe("219 234 254");
      expect(accent("--color-accent-50")).toBe("239 246 255");
    } finally {
      act(() => {
        useThemeStore.getState().setMode("light");
      });
    }
  });
});

describe("resolveProfileThemeForMode", () => {
  const ramp = {
    "--color-accent-50": "239 246 255",
    "--color-accent-100": "219 234 254",
    "--color-accent-200": "191 219 254",
    "--color-accent-400": "96 165 250",
    "--color-accent-500": "59 130 246",
    "--color-accent-700": "29 78 216",
    "--color-accent-800": "30 64 175",
    "--color-accent-900": "30 58 138",
  };

  it("returns the theme unchanged in light mode", () => {
    expect(resolveProfileThemeForMode(ramp, false)).toEqual(ramp);
  });

  it("maps text step 700 to 400 and low tints to the dark end", () => {
    const dark = resolveProfileThemeForMode(ramp, true);
    expect(dark["--color-accent-700"]).toBe("96 165 250");
    expect(dark["--color-accent-50"]).toBe("30 58 138");
    expect(dark["--color-accent-100"]).toBe("30 58 138");
    expect(dark["--color-accent-200"]).toBe("30 64 175");
    // Untouched steps pass through.
    expect(dark["--color-accent-500"]).toBe("59 130 246");
  });

  it("hands brand text the profile's light 300, which carries on a raised surface", () => {
    // `text-on-primary` is the one class that reads right under every
    // profile in dark: the default dark value is a teal, which beside a blue
    // ramp is a second brand colour.
    const primary = {
      "--color-primary-300": "147 197 253",
      "--color-primary-400": "96 165 250",
      "--color-primary-700": "29 78 216",
    };
    // blue-400 (the remapped 700) is 4.1:1 on surface-raised 63 63 70; 300 is
    // above 4.5.
    expect(resolveProfileThemeForMode(primary, true)["--on-primary"]).toBe(
      "147 197 253",
    );
    // A ramp without a 300 falls back to the remapped 700.
    expect(
      resolveProfileThemeForMode(
        {
          "--color-primary-400": "96 165 250",
          "--color-primary-700": "29 78 216",
        },
        true,
      )["--on-primary"],
    ).toBe("96 165 250");
    expect(resolveProfileThemeForMode(primary, false)).not.toHaveProperty(
      "--on-primary",
    );
    // No primary ramp in the profile: the stylesheet's own value stands.
    expect(resolveProfileThemeForMode(ramp, true)).not.toHaveProperty(
      "--on-primary",
    );
  });

  it("drops a step whose dark counterpart the ramp does not define", () => {
    // Keeping the light value is how a tint step ends up painting a near-white
    // blob on a dark surface — a brand-tinted chip or selected tile is
    // `bg-primary-50`, and is what that looks like. Without the
    // override, the `.dark` block in index.css supplies its own dark tint.
    const partial = { "--color-accent-700": "29 78 216" };
    expect(resolveProfileThemeForMode(partial, true)).toEqual({});
  });

  it("keeps a step it can remap even when other steps are missing", () => {
    const partial = {
      "--color-accent-50": "239 246 255",
      "--color-accent-900": "30 58 138",
    };
    expect(resolveProfileThemeForMode(partial, true)).toEqual({
      "--color-accent-50": "30 58 138",
      "--color-accent-900": "30 58 138",
    });
  });

  it("ignores variables that are not color ramp steps", () => {
    const vars = { "--surface-card": "255 255 255" };
    expect(resolveProfileThemeForMode(vars, true)).toEqual(vars);
  });
});

// The three shipped primary ramps, verbatim from
// backend/app/core/product_profiles.py. The shell avatar paints on
// primary-100 and the active list chips on primary-50, both with `text-on`
// (250 250 250 in dark). If the dark remap ever lands those tints on a light
// step again, the avatar letter and chip labels go invisible on their own
// background — so the remapped values are pinned to WCAG AA here.
const SHIPPED_PRIMARY_RAMPS: Record<string, Record<string, string>> = {
  food_home: {
    "--color-primary-50": "236 253 245",
    "--color-primary-100": "209 250 229",
    "--color-primary-200": "167 243 208",
    "--color-primary-300": "110 231 183",
    "--color-primary-400": "52 211 153",
    "--color-primary-500": "16 185 129",
    "--color-primary-600": "5 150 105",
    "--color-primary-700": "4 120 87",
    "--color-primary-800": "6 95 70",
    "--color-primary-900": "6 78 59",
    "--color-primary-950": "2 44 34",
  },
  equipment_wms: {
    "--color-primary-50": "239 246 255",
    "--color-primary-100": "219 234 254",
    "--color-primary-200": "191 219 254",
    "--color-primary-300": "147 197 253",
    "--color-primary-400": "96 165 250",
    "--color-primary-500": "59 130 246",
    "--color-primary-600": "37 99 235",
    "--color-primary-700": "29 78 216",
    "--color-primary-800": "30 64 175",
    "--color-primary-900": "30 58 138",
    "--color-primary-950": "23 37 84",
  },
  clean_core: {
    "--color-primary-50": "255 251 235",
    "--color-primary-100": "254 243 199",
    "--color-primary-200": "253 230 138",
    "--color-primary-300": "252 211 77",
    "--color-primary-400": "251 191 36",
    "--color-primary-500": "245 158 11",
    "--color-primary-600": "217 119 6",
    "--color-primary-700": "180 83 9",
    "--color-primary-800": "146 64 14",
    "--color-primary-900": "120 53 15",
    "--color-primary-950": "69 26 3",
  },
};

function channelLuminance(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function luminance(triplet: string): number {
  const [r, g, b] = triplet.split(/\s+/).map(Number);
  return (
    0.2126 * channelLuminance(r) +
    0.7152 * channelLuminance(g) +
    0.0722 * channelLuminance(b)
  );
}

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

describe("dark-mode contrast of a filled primary surface", () => {
  const WHITE = "255 255 255";

  // The Button and the default Badge carry white labels on a primary fill.
  // Under `.dark` they sit on step 800, which the profile map leaves alone.
  it.each(Object.entries(SHIPPED_PRIMARY_RAMPS))(
    "keeps white on %s's 800 step above AA, and 700 below it",
    (_profile, ramp) => {
      const dark = resolveProfileThemeForMode(ramp, true);
      expect(
        contrast(dark["--color-primary-800"], WHITE),
      ).toBeGreaterThanOrEqual(4.5);
      // The reason the fill cannot stay on 700: that step is handed to text.
      // If this ever passes, the override in Button and Badge can go.
      expect(contrast(dark["--color-primary-700"], WHITE)).toBeLessThan(4.5);
    },
  );
});

describe("light-mode contrast of a filled primary surface", () => {
  // DateInput's selected day, the active recipe step and the shared Button
  // carry white text on step 700 in light mode.
  it.each(Object.entries(SHIPPED_PRIMARY_RAMPS))(
    "keeps white on %s's 700 step above AA",
    (_profile, ramp) => {
      const light = resolveProfileThemeForMode(ramp, false);
      expect(
        contrast(light["--color-primary-700"], "255 255 255"),
      ).toBeGreaterThanOrEqual(4.5);
    },
  );
});

describe("dark-mode contrast on tinted surfaces", () => {
  // --text-primary as the .dark block in index.css sets it — the colour
  // `text-on` resolves to in dark mode.
  const DARK_TEXT_ON = "250 250 250";

  it.each(Object.entries(SHIPPED_PRIMARY_RAMPS))(
    "keeps %s tint surfaces readable under dark text-on",
    (_profile, ramp) => {
      const dark = resolveProfileThemeForMode(ramp, true);
      // The avatar paints on 100 (hover: 200), the active chip on 50.
      expect(dark["--color-primary-50"]).toBe(ramp["--color-primary-900"]);
      expect(dark["--color-primary-100"]).toBe(ramp["--color-primary-900"]);
      expect(dark["--color-primary-200"]).toBe(ramp["--color-primary-800"]);

      for (const step of [
        "--color-primary-50",
        "--color-primary-100",
        "--color-primary-200",
      ]) {
        expect(contrast(dark[step], DARK_TEXT_ON)).toBeGreaterThanOrEqual(4.5);
      }
    },
  );
});
