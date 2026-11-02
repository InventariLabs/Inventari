import { prepareImageUpload } from "@/lib/imageUtils";
import type { components } from "@/types/api-generated";
import { api, getEveryPage, type Page } from "./client";
import axios from "axios";
import { IMAGE_UPLOAD_MAX_BYTES, assertFileSize } from "@/utils/fileValidation";
import type { Organization, OrganizationMember } from "@/types";

/** A freshly issued code, and what the account redeeming it becomes. */
export type InvitationCode = components["schemas"]["InvitationCodeResponse"];

export interface Invitation {
  id: string;
  code: string;
  role: string;
  role_id: string | null;
  is_used: boolean;
  expires_at: string;
  created_at: string;
  invited_email: string | null;
  used_by_user_id: string | null;
  used_at: string | null;
  /** How the mail carrying this code ended: "sent", "failed", or still in
   *  flight ("pending" / "sending"). Null when there was no mail to send —
   *  a bearer code, or an installation without SMTP where the administrator
   *  hands the link over themselves. */
  email_status: string | null;
}

/** One message the queue gave up on, as the email screen lists them. */
export interface FailedEmail {
  id: string;
  to_email: string;
  subject: string;
  attempts: number;
  max_attempts: number;
  /** What the relay said on the last attempt. */
  last_error: string | null;
  created_at: string;
}

/** What a member becomes: a built-in level (`role`) or one org-scoped custom
 *  role (`roleId`). Exactly one — the backend refuses both and neither. */
export interface MemberRoleChoice {
  role?: string;
  roleId?: string;
}

/** Who the invitation is for, and what they become on arrival. */
export interface InvitationRequest extends MemberRoleChoice {
  email: string;
}

interface PaginatedMembers {
  items: OrganizationMember[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** What a live join link says about itself, for the person it was sent to. */
export type InvitationCheck = components["schemas"]["InvitationCheckResponse"];

export const organizationsApi = {
  getAll: async (): Promise<Organization[]> => {
    return getEveryPage<Organization>("/organizations/all");
  },

  getMe: async (): Promise<Organization> => {
    const response = await api.get<Organization>("/organizations/my");
    return response.data;
  },

  update: async (data: {
    name?: string;
    currency?: string;
    timezone?: string;
    settings?: unknown;
    /** Issuer identity printed on documents. */
    tax_id?: string | null;
    country?: string | null;
    address?: {
      street?: string | null;
      city?: string | null;
      postal_code?: string | null;
    } | null;
  }): Promise<Organization> => {
    const response = await api.put<Organization>("/organizations", data);
    return response.data;
  },

  uploadLogo: async (file: File): Promise<{ logo_url: string }> => {
    const image = await prepareImageUpload(file);
    assertFileSize(image, IMAGE_UPLOAD_MAX_BYTES);
    const form = new FormData();
    form.append("image", image);
    const response = await api.post<{ logo_url: string }>(
      "/organizations/logo",
      form,
    );
    return response.data;
  },

  deleteLogo: async (): Promise<void> => {
    await api.delete("/organizations/logo");
  },

  createInvitationCode: async (
    invite: InvitationRequest,
  ): Promise<InvitationCode> => {
    const response = await api.post<InvitationCode>(
      "/organizations/my/invitation-code",
      invite.roleId
        ? { role_id: invite.roleId, email: invite.email }
        : { role: invite.role, email: invite.email },
    );
    return response.data;
  },

  /** Send a pending invitation again, and give it another seven days. */
  resendInvitation: async (invitationId: string): Promise<InvitationCode> => {
    const response = await api.post<InvitationCode>(
      `/organizations/my/invitations/${invitationId}/resend`,
    );
    return response.data;
  },

  /** Withdraw an invitation nobody has redeemed yet. */
  revokeInvitation: async (invitationId: string): Promise<void> => {
    await api.delete(`/organizations/my/invitations/${invitationId}`);
  },

  /**
   * Invitations issued for this organization, newest first.
   *
   * The screen showed a freshly generated link and nothing else, so whether
   * an earlier one had been used could only be inferred from who turned up
   * in the member list.
   */
  listInvitations: async (): Promise<Invitation[]> => {
    return getEveryPage<Invitation>("/organizations/my/invitations");
  },

  /**
   * Mail this organization sent that never arrived.
   *
   * The queue retries for about seven and a half minutes and then gives up.
   * Until this read existed, the row it left behind was the end of the
   * message for everyone outside the container log.
   */
  listFailedEmails: async (): Promise<FailedEmail[]> => {
    // The newest page only, as before the envelope: the card is a warning, not
    // an archive of every bounce.
    const response = await api.get<Page<FailedEmail>>(
      "/organizations/my/failed-emails",
    );
    return response.data.items;
  },

  join: async (code: string): Promise<Organization> => {
    const response = await api.post<Organization>("/organizations/join", {
      code,
    });
    return response.data;
  },

  /**
   * Whether a join link still opens, asked without an account.
   *
   * The endpoint is public on purpose — the caller is the person the
   * invitation was emailed to, arriving before they have anything to
   * authenticate with — and lives outside /api/v1, so this call bypasses
   * the authed client. The 404 is what lets the /join screen say "invalid
   * or expired" instead of forwarding a dead link's reader to /login.
   */
  checkInvitation: async (code: string): Promise<InvitationCheck> => {
    const response = await axios.get<InvitationCheck>(
      `/public/invitation/${encodeURIComponent(code)}`,
    );
    return response.data;
  },

  getMembers: async (
    offset = 0,
    limit = 20,
    search?: string,
  ): Promise<PaginatedMembers> => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    if (search) params.set("search", search);
    const response = await api.get<PaginatedMembers>(
      `/organizations/my/members?${params.toString()}`,
    );
    return response.data;
  },

  removeMember: async (userId: string): Promise<void> => {
    await api.post(`/organizations/my/remove-member/${userId}`);
  },

  changeMemberRole: async (
    userId: string,
    choice: MemberRoleChoice,
  ): Promise<void> => {
    await api.patch(
      `/organizations/my/members/${userId}/role`,
      choice.roleId ? { role_id: choice.roleId } : { role: choice.role },
    );
  },

  leave: async (): Promise<void> => {
    await api.post("/organizations/my/leave");
  },

  testEmail: async (smtpConfig: unknown): Promise<{ message: string }> => {
    const response = await api.post("/organizations/my/test-email", smtpConfig);
    return response.data;
  },
};
