/**
 * The account password policy, as the backend states it.
 *
 * `validate_password_policy` (backend/app/schemas/user.py) is the authority;
 * this is the same set of rules said in front of the reader instead of after
 * the request. Keep the two in step — a client that accepts what the server
 * rejects turns a rule into a failed submit with no explanation.
 */

/** bcrypt hashes at most 72 bytes and refuses anything longer — the length
 * that matters is bytes, not characters. */
export const PASSWORD_MAX_BYTES = 72;

export const PASSWORD_RULES = [
  "minLength",
  "lowercase",
  "uppercase",
  "digit",
  "maxBytes",
] as const;

export type PasswordRule = (typeof PASSWORD_RULES)[number];

export function checkPasswordRules(
  value: string,
): Record<PasswordRule, boolean> {
  return {
    minLength: value.length >= 8,
    lowercase: /[a-z]/.test(value),
    uppercase: /[A-Z]/.test(value),
    digit: /\d/.test(value),
    maxBytes: new TextEncoder().encode(value).length <= PASSWORD_MAX_BYTES,
  };
}

/** The first rule the value breaks, or null when it breaks none. */
export function firstBrokenRule(value: string): PasswordRule | null {
  const met = checkPasswordRules(value);
  return PASSWORD_RULES.find((rule) => !met[rule]) ?? null;
}
