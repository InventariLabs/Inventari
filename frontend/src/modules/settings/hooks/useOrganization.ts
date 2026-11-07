import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { organizationsApi } from "@/lib/api/organizations";
import type {
  FailedEmail,
  Invitation,
  InvitationCode,
  InvitationRequest,
  MemberRoleChoice,
} from "@/lib/api/organizations";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import type { Organization } from "@/types";
import { setOrganizationCountry } from "@/utils/formatters";
// ─── Queries ─────────────────────────────────────────────────────────────────

export function useOrganization() {
  return useQuery<Organization>({
    queryKey: queryKeys.organization.detail,
    // The formatters read the organization's country to pick English's
    // regional variant; set it before the data reaches a component, so the
    // first render already writes dates the organization's way.
    queryFn: async () => {
      const org = await organizationsApi.getMe();
      setOrganizationCountry(org.country);
      return org;
    },
  });
}

/**
 * Whether the general lists show data a vertical module claims as its own.
 *
 * Off is the default and stays the default while the organization loads:
 * laptops among the cucumbers is nobody's intent, and starting permissive
 * would show a mixed list for a beat before tidying itself. Turning it on is
 * for the organization that wants one list of everything — and for reaching
 * data a module left behind after being switched off, which stays hidden
 * otherwise (the claim outlives the module, by design).
 */
export function useShowModuleData(): boolean {
  const { data: org } = useOrganization();
  return org?.settings?.show_module_data === true;
}

/**
 * One page of the organization's members, as a query: the hook below mounts
 * it, and a caller that needs the answer at once (a save that must not
 * outrun a check) fetches the same entry from the cache.
 */
export function organizationMembersQuery(
  offset = 0,
  limit = 20,
  search?: string,
) {
  return {
    queryKey: [...queryKeys.organization.members, offset, limit, search ?? ""],
    queryFn: () => organizationsApi.getMembers(offset, limit, search),
  };
}

export function useOrganizationMembers(
  offset = 0,
  limit = 20,
  search?: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    ...organizationMembersQuery(offset, limit, search),
    enabled: options?.enabled ?? true,
  });
}

// ─── Mutations ───────────────────────────────────────────────────────────────

export function useUpdateOrganization() {
  return useAppMutation(
    (data: Parameters<typeof organizationsApi.update>[0]) =>
      organizationsApi.update(data),
    (qc) => {
      invalidation.organization(qc);
    },
  );
}

/** Upload the logo printed on documents. */
export function useUploadOrganizationLogo() {
  return useAppMutation(
    (file: File) => organizationsApi.uploadLogo(file),
    (qc) => {
      invalidation.organization(qc);
    },
  );
}

/** Remove the logo; documents print without one. */
export function useDeleteOrganizationLogo() {
  return useAppMutation(
    () => organizationsApi.deleteLogo(),
    (qc) => {
      invalidation.organization(qc);
    },
  );
}

export function useTestEmail() {
  return useAppMutation(
    (smtpConfig: unknown) => organizationsApi.testEmail(smtpConfig),
    () => {},
  );
}

export function useCreateInvitationCode() {
  return useAppMutation<InvitationCode, InvitationRequest>(
    (invite: InvitationRequest) =>
      organizationsApi.createInvitationCode(invite),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.organization.invitations });
    },
  );
}

/** Send a pending invitation again; the code stays, the clock restarts. */
export function useResendInvitation() {
  return useAppMutation<InvitationCode, string>(
    (invitationId: string) => organizationsApi.resendInvitation(invitationId),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.organization.invitations });
    },
  );
}

/** Withdraw an invitation nobody has redeemed yet. */
export function useRevokeInvitation() {
  return useAppMutation<void, string>(
    (invitationId: string) => organizationsApi.revokeInvitation(invitationId),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.organization.invitations });
    },
  );
}

/** Which invitations exist, and whether anyone has used them. */
export function useInvitations(enabled = true) {
  return useQuery<Invitation[]>({
    queryKey: queryKeys.organization.invitations,
    queryFn: () => organizationsApi.listInvitations(),
    enabled,
  });
}

/** Mail this organization sent that the queue eventually gave up on. */
export function useFailedEmails(enabled = true) {
  return useQuery<FailedEmail[]>({
    queryKey: queryKeys.organization.failedEmails,
    queryFn: () => organizationsApi.listFailedEmails(),
    enabled,
  });
}

export function useRemoveMember() {
  return useAppMutation(
    (userId: string) => organizationsApi.removeMember(userId),
    (qc) => {
      invalidation.organization(qc);
      invalidation.rights(qc);
    },
  );
}

export function useChangeMemberRole() {
  return useAppMutation(
    ({ userId, ...choice }: { userId: string } & MemberRoleChoice) =>
      organizationsApi.changeMemberRole(userId, choice),
    (qc) => {
      invalidation.organization(qc);
      invalidation.rights(qc);
    },
  );
}

export function useJoinOrganization() {
  return useAppMutation(
    (code: string) => organizationsApi.join(code),
    (qc) => {
      invalidation.organization(qc);
    },
  );
}

/**
 * Whether a join link still opens, asked without an account.
 *
 * The /join page runs this before it forwards a signed-out visitor anywhere:
 * a dead link answers here, as "invalid or expired" on the screen, instead of
 * coming back later as a registration form that refuses at submit — or as the
 * silent drop on /login an old link used to end with.
 */
export function useInvitationCheck(code: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.organization.invitations, "check", code] as const,
    queryFn: () => organizationsApi.checkInvitation(code ?? ""),
    enabled: enabled && Boolean(code),
    retry: false,
  });
}
