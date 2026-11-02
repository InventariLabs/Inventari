import { api } from "./client";
import type { AuditLogListResponse } from "@/types/core";

/**
 * Whether a row was written by an API key or by a person. 'human' is every
 * entry with no key recorded — the rows written before keys were named at
 * all are people's as far as the journal can tell.
 */
export type AuditActorFilter = "human" | "api_key";

export interface AuditLogFilters {
  target_type?: string;
  target_id?: string;
  user_id?: string;
  actor?: AuditActorFilter;
  since?: string; // ISO date ("yyyy-MM-dd") — the backend widens it to midnight
  until?: string; // ISO date — the other end of the range
  limit?: number;
  /**
   * Where the previous page ended — its `next_cursor`. A page is reached from
   * the one before it, so the cost of a page does not grow with the length of
   * the journal.
   */
  cursor?: string;
}

export const auditLogApi = {
  list: async (
    filters: AuditLogFilters = {},
  ): Promise<AuditLogListResponse> => {
    const params: Record<string, unknown> = {};
    if (filters.target_type) params.target_type = filters.target_type;
    if (filters.target_id) params.target_id = filters.target_id;
    if (filters.user_id) params.user_id = filters.user_id;
    if (filters.actor) params.actor = filters.actor;
    if (filters.since) params.since = filters.since;
    if (filters.until) params.until = filters.until;
    if (filters.limit !== undefined) params.limit = filters.limit;
    if (filters.cursor) params.cursor = filters.cursor;
    const response = await api.get<AuditLogListResponse>("/audit-log", {
      params,
    });
    return response.data;
  },

  /**
   * The kinds of thing this organization's log actually records.
   *
   * The filter used to offer three values written into the page, two of them
   * belonging to modules the profile does not install — so two choices could
   * only ever answer "no entries", and the things that really changed
   * (storages, members, modules) had no choice at all.
   */
  targetTypes: async (): Promise<string[]> => {
    const response = await api.get<string[]>("/audit-log/target-types");
    return response.data;
  },
};
