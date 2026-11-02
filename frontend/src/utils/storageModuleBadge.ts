/** What the catalogue lookup returns for a tag no module owns. */
const NOT_A_MODULE = "\u0000";

/**
 * What a location picker owes a location a module owns: whose it is.
 *
 * A module-context location only reaches a general picker when the
 * organization asked for one mixed list, or when a record already stands
 * there and the form kept it selectable — and in both cases a bare name
 * among the organization's own locations reads as one of them. The badge
 * says which module it belongs to.
 *
 * The module's display name comes from the translation catalogues
 * (modules.<tag>.name — AGENTS.md §4, "Module display names"). A tag with no
 * entry there is not a module — the backend also gives a food-behaviour
 * location the tag "food", which names a kind of place, not an owner — and a
 * badge saying "Module: food" would claim an owner that does not exist. Such
 * a location is shown like any of the organization's own.
 *
 * Structural `t` parameter rather than i18next's TFunction so the helper
 * works with the `t` a useTranslation returns and with the narrower `t`
 * props some panels take.
 */
export function storageModuleBadge(
  t: (key: string, options?: Record<string, unknown>) => string,
  contextTag: string | null | undefined,
): string | undefined {
  if (!contextTag) return undefined;
  const module = t(`modules.${contextTag}.name`, {
    ns: "modules",
    defaultValue: NOT_A_MODULE,
  });
  if (module === NOT_A_MODULE) return undefined;
  return t("picker.moduleBadge", { ns: "locations", module });
}
