import type { ApiKey } from "./types";

/**
 * Whether a key has stopped authenticating.
 *
 * Compared as an instant rather than as a day. The shared `isExpired` in
 * `@/utils/helpers` rounds "now" down to midnight, which is right for a
 * carton of milk and wrong here: the server refuses a key the moment
 * `now > expires_at`, so a key that lapsed three hours ago is already dead
 * while a day-granularity check would still call it live until tomorrow.
 */
export function isKeyExpired(
  expiresAt: string | null,
  now: number = Date.now(),
): boolean {
  if (expiresAt === null) return false;
  const expires = new Date(expiresAt).getTime();
  return Number.isFinite(expires) && expires < now;
}

/**
 * Live keys first, expired ones after, each group in the order it arrived.
 *
 * Five keys rendered with identical classes and no badge left the only
 * difference in one date cell the reader had to compare against today. The
 * one they are looking for — the key an integration just stopped
 * authenticating with — is now the one at the bottom.
 */
export function liveKeysFirst(
  keys: ApiKey[],
  now: number = Date.now(),
): ApiKey[] {
  const live = keys.filter((key) => !isKeyExpired(key.expires_at, now));
  const expired = keys.filter((key) => isKeyExpired(key.expires_at, now));
  return [...live, ...expired];
}
