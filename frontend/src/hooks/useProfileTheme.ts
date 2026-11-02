import { useEffect } from "react";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { useThemeStore } from "@/store/themeStore";
import { applyThemeVariables } from "@/lib/moduleRegistry/registryI18nTheme";

/**
 * profile palettes declare light-mode ramps. Applied inline on
 * `<html>` they beat the `.dark` token overrides in index.css, so in dark
 * mode the fix was bypassed — e.g. the active nav tab in the
 * equipment profile (blue-700 on surface-card) measured 2.22:1. In dark
 * mode the tint steps are remapped the same way index.css remaps the
 * default palette: low tints take the ramp's dark end, and the text step
 * 700 takes 400 (hue-safe — blue-400 ≈ 5.9:1 on surface-card, whereas
 * blue-500 would be ≈ 4.0:1, below WCAG AA). Steps without a counterpart
 * in the profile's own ramp pass through unchanged.
 */
const DARK_STEP_MAP: Record<string, string> = {
  "50": "900",
  "100": "900",
  "200": "800",
  "300": "700",
  "400": "700",
  "700": "400",
};

export function resolveProfileThemeForMode(
  theme: Record<string, string>,
  isDark: boolean,
): Record<string, string> {
  if (!isDark) return theme;
  const resolved: Record<string, string> = {};
  Object.entries(theme).forEach(([varName, value]) => {
    const match = /^(--color-.+-)(\d{2,3})$/.exec(varName);
    const target = match ? DARK_STEP_MAP[match[2]] : undefined;
    if (match && target) {
      const replacement = theme[`${match[1]}${target}`];
      // A partial ramp is the dangerous case: keeping the light value for a
      // tint step paints a near-white blob on a dark surface — a filled Select
      // trigger uses `bg-primary-50`, and is what that looks like.
      // Dropping the override instead lets the `.dark` block in index.css
      // supply its own dark tint for that step.
      if (replacement === undefined) return;
      resolved[varName] = replacement;
      return;
    }
    resolved[varName] = value;
  });
  // Brand text (`text-on-primary`) takes the ramp's light 300, read from the
  // profile's own declaration before the remap: the remapped 700 (blue-400)
  // is only 4.1:1 on surface-raised. The default dark value is a teal that
  // would clash with the profile's hue. Without a 300 it falls back to the
  // remapped 700.
  const brandText =
    theme["--color-primary-300"] ?? resolved["--color-primary-700"];
  if (brandText !== undefined) resolved["--on-primary"] = brandText;
  return resolved;
}

/**
 * Applies the active profile's `theme` map as CSS variables on `<html>`.
 *
 * Switching profile must visibly change the
 * app. Ordering matters — module theme overrides are applied first
 * (ModulesContext/ModuleShell), this hook runs afterwards, so the profile
 * wins on conflicting keys. Originals are saved and restored when the
 * profile changes (or the hook unmounts), mirroring the module theme
 * save/restore semantics.
 */
export function useProfileTheme() {
  const profile = useActiveProfile();
  const theme = profile?.theme ?? null;
  // The resolved theme, not the chosen mode: on "system" the mode says nothing
  // about which palette is on screen.
  const resolved = useThemeStore((s) => s.resolved);

  useEffect(() => {
    if (!theme || Object.keys(theme).length === 0) return;
    return applyThemeVariables(
      resolveProfileThemeForMode(theme, resolved === "dark"),
    );
  }, [theme, resolved]);
}
