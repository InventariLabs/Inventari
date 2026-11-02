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
