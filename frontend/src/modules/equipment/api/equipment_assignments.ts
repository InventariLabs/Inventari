import type { components } from "@/types/api-generated";
import axios from "axios";

import { api } from "@/lib/api/client";

export type EquipmentAssignment = components["schemas"]["AssignmentSchema"];

type AssignmentListResponse = components["schemas"]["AssignmentListResponse"];

export type AssignmentCreate = components["schemas"]["AssignmentCreate"];

export type AssignmentCheckin = components["schemas"]["AssignmentCheckin"];

// E14: overdue assignments surfaced from /equipment/assignments/overdue.
export type OverdueAssignmentItem =
  components["schemas"]["OverdueAssignmentItem"];

type OverdueAssignmentListResponse =
  components["schemas"]["OverdueAssignmentListResponse"];

export const equipmentAssignmentsApi = {
  checkout: async (data: AssignmentCreate): Promise<EquipmentAssignment> => {
    const response = await api.post<EquipmentAssignment>(
      "/equipment/assignments",
      data,
    );
    return response.data;
  },

  checkin: async (
    assignmentId: string,
    data: AssignmentCheckin,
  ): Promise<EquipmentAssignment> => {
    const response = await api.post<EquipmentAssignment>(
      `/equipment/assignments/${assignmentId}/checkin`,
      data,
    );
    return response.data;
  },

  listActiveAssignments: async (): Promise<AssignmentListResponse> => {
    const response = await api.get<AssignmentListResponse>(
      "/equipment/assignments",
    );
    return response.data;
  },

  // List assignments whose expected_return_at has passed without checkin.
  listOverdueAssignments: async (
    limit = 20,
    offset = 0,
  ): Promise<OverdueAssignmentListResponse> => {
    const response = await api.get<OverdueAssignmentListResponse>(
      "/equipment/assignments/overdue",
      { params: { limit, offset } },
    );
    return response.data;
  },

  getItemAssignmentHistory: async (
    itemId: string,
  ): Promise<EquipmentAssignment[]> => {
    const response = await api.get<{ items: EquipmentAssignment[] }>(
      `/equipment/assignments/item/${itemId}`,
    );
    return response.data.items;
  },

  getProtocolHtmlUrl: (assignmentId: string, templateId?: string): string => {
    const base = `/api/v1/equipment/assignments/${assignmentId}/protocol/html`;
    return templateId ? `${base}?template_id=${templateId}` : base;
  },

  getProtocolPdfUrl: (assignmentId: string, templateId?: string): string => {
    const base = `/api/v1/equipment/assignments/${assignmentId}/protocol/pdf`;
    return templateId ? `${base}?template_id=${templateId}` : base;
  },

  fetchProtocolHtml: async (
    assignmentId: string,
    templateId?: string,
  ): Promise<string> => {
    const params = templateId ? { template_id: templateId } : {};
    try {
      const response = await api.get<string>(
        `/equipment/assignments/${assignmentId}/protocol/html`,
        { params, responseType: "text" },
      );
      return response.data;
    } catch (error) {
      // With responseType "text" a refusal body arrives as an unparsed JSON
      // string, and extractApiError reads no detail out of a string — the
      // backend's sentence stopped at this seam. The shape of this transport
      // is known here, so this is where the body gets parsed once. Decision,
      // asked for in review: the address, not the client seam — "text" is one
      // route's transport choice (an HTML protocol only this endpoint
      // serves), where the blob unwrap earned the shared interceptor by
      // being a dozen call sites' shape; promoting this to client.ts would
      // tax every text request with a body only one of them produces.
      if (
        axios.isAxiosError(error) &&
        typeof error.response?.data === "string"
      ) {
        try {
          error.response.data = JSON.parse(error.response.data);
        } catch {
          // not JSON — hand the raw body on, the fallback sentence covers it
        }
      }
      throw error;
    }
  },

  downloadProtocolPdf: async (
    assignmentId: string,
    templateId?: string,
  ): Promise<Blob> => {
    const params = templateId ? { template_id: templateId } : {};
    const response = await api.get(
      `/equipment/assignments/${assignmentId}/protocol/pdf`,
      { params, responseType: "blob" },
    );
    return response.data as Blob;
  },
};
