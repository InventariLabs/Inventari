/**
 * What an administrator may set a member to — mirrors the backend's
 * `_VALID_MEMBER_ROLES`.
 *
 * Shared because two screens offer the same choice: the member list changes an
 * existing account's role, and the invitation carries the role the account
 * that redeems it will get.
 */
export const MEMBER_ROLES = ["admin", "manager", "user", "viewer"] as const;

export type MemberRoleName = (typeof MEMBER_ROLES)[number];
