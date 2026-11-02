import { apiErrorStatus } from "@/lib/errors";

/**
 * Which sentence a failed sign-in deserves.
 *
 * The login form used to answer every failure with "invalid email or
 * password": a rate-limited reader changed a password that was correct, and
 * a reader with no connection did the same. The status separates the four
 * cases the reader can act on differently.
 */
export function loginFailureKey(error: unknown): string {
  const status = apiErrorStatus(error);
  // No response at all — the request never reached the server.
  if (status === null) return "login.networkError";
  if (status === 401 || status === 403) return "invalidCredentials";
  if (status === 429) return "login.tooManyAttempts";
  if (status >= 500) return "login.serverError";
  return "login.failed";
}
