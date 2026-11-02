import type { TFunction } from "i18next";

/**
 * What a key scope is called on screen.
 *
 * Scope names come from the server (`/api-keys/capabilities`), which may know
 * one this screen was not written for; such a scope shows its own name rather
 * than nothing.
 */
export function scopeLabel(scope: string, t: TFunction): string {
  if (scope === "printing") return t("api_keys:scopes.printing");
  return scope;
}
