/**
 * The i18n key for the badge an archived record wears.
 *
 * Not an inventory question, though it started as one. A record is archived
 * with a reason in the core, and two modules put that reason on screen — the
 * items archive and the equipment archive — so the composition lives where
 * either can reach it without importing the other module's internals. It is
 * the same dictionary the delete dialog chooses the reason from
 * (`items:deletionReasons`): a reason is one word wherever it is chosen or
 * shown.
 *
 * A ``deletion_reason`` is stored lowercase (and older rows UPPERCASE) while
 * the locale keys are UPPERCASE, so the badge key is composed — which is also
 * why the i18n key check cannot see it: a reason the backend writes but the
 * locales miss surfaces as a raw key on the screen. Every value that can
 * reach this key is enumerated in the archive screens' tests.
 */
export const archivedReasonBadgeKey = (reason: string): string =>
  `items:deletionReasons.${reason.toUpperCase()}`;

/**
 * The word an archived record's reason is read as, on every screen that shows
 * it: the catalogue's word when it has one, else the value that was written
 * (the truth, even when no translation exists — never the composed key), and
 * "Unknown" when no reason was stored at all.
 */
export const archivedReasonLabel = (
  t: (key: string, options?: { defaultValue?: string }) => string,
  reason: string | null | undefined,
): string =>
  reason
    ? t(archivedReasonBadgeKey(reason), { defaultValue: reason })
    : t("common:unknown");
