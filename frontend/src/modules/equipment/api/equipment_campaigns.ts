import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";
/** The three ways a campaign can be narrowed. */
export type ScopeType = components["schemas"]["CampaignSchema"]["scope_type"];

/** How much work a scope holds, before anybody commits to it. */
export type ScopePreview = components["schemas"]["ScopePreview"];

export type AuditResponseItemRecord =
  components["schemas"]["AuditResponseItemSchema"];

export type AuditResponseRecord = components["schemas"]["AuditResponseSchema"];
/** A response as the campaign's own page lists it, with its returned flag. */
export type CampaignResponseRecord =
  components["schemas"]["CampaignResponseSchema"];
export type ReminderRunResult = components["schemas"]["ReminderRunResult"];

type Campaign = components["schemas"]["CampaignSchema"];

type CampaignDetail = components["schemas"]["CampaignDetail"];

export type CampaignCreate = components["schemas"]["CampaignCreate"];

export interface LaunchResult {
  responses_created: number;
  skipped_no_email: number;
  /** The holders who were not asked: no e-mail address on their checkout. */
  skipped_people?: string[];
  emails_sent: number;
  emails_failed: number;
  /** No mail server: nobody was e-mailed, the links wait on the page. */
  email_unavailable?: boolean;
}

export const equipmentCampaignsApi = {
  listCampaigns: async (): Promise<Campaign[]> => {
    return getEveryPage<Campaign>("/equipment/campaigns");
  },

  getCampaign: async (campaignId: string): Promise<CampaignDetail> => {
    const response = await api.get<CampaignDetail>(
      `/equipment/campaigns/${campaignId}`,
    );
    return response.data;
  },

  /**
   * What a scope holds, before anything is created.
   *
   * The picker offered "all assets" without a number, and the launch
   * confirmation asked for an irreversible send without saying to how many
   * people. A scope covering nobody is the case worth knowing about first.
   */
  scopePreview: async (
    scopeType: ScopeType,
    scopeFilterId?: string,
  ): Promise<ScopePreview> => {
    const response = await api.get<ScopePreview>(
      "/equipment/campaigns/scope-preview",
      {
        params: {
          scope_type: scopeType,
          ...(scopeFilterId ? { scope_filter_id: scopeFilterId } : {}),
        },
      },
    );
    return response.data;
  },

  createCampaign: async (data: CampaignCreate): Promise<Campaign> => {
    const response = await api.post<Campaign>("/equipment/campaigns", data);
    return response.data;
  },

  launchCampaign: async (campaignId: string): Promise<LaunchResult> => {
    const response = await api.post<LaunchResult>(
      `/equipment/campaigns/${campaignId}/launch`,
    );
    return response.data;
  },

  sendReminders: async (campaignId: string): Promise<ReminderRunResult> => {
    const response = await api.post<ReminderRunResult>(
      `/equipment/campaigns/${campaignId}/remind`,
    );
    return response.data;
  },

  /** One person's attestation link, to hand over where no e-mail goes. */
  responseLink: async (
    campaignId: string,
    responseId: string,
  ): Promise<string> => {
    const response = await api.get<{ url: string }>(
      `/equipment/campaigns/${campaignId}/responses/${responseId}/link`,
    );
    return response.data.url;
  },

  completeCampaign: async (campaignId: string): Promise<Campaign> => {
    const response = await api.post<Campaign>(
      `/equipment/campaigns/${campaignId}/complete`,
    );
    return response.data;
  },

  /** Calls off a launched campaign, voiding the links already in inboxes. */
  cancelCampaign: async (campaignId: string): Promise<Campaign> => {
    const response = await api.post<Campaign>(
      `/equipment/campaigns/${campaignId}/cancel`,
    );
    return response.data;
  },

  /** Only a draft: a launched one holds the answers that came back. */
  deleteCampaign: async (campaignId: string): Promise<void> => {
    await api.delete(`/equipment/campaigns/${campaignId}`);
  },
};
