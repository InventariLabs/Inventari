import { api, getEveryPage, type Page } from "@/lib/api/client";
import type { components } from "@/types/api-generated";
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderUpdate,
  PurchaseOrderListParams,
  PurchaseOrderListResponse,
  POSettings,
  POSettingsUpdate,
} from "@/modules/purchase_orders/types/purchase-orders";
import type { TargetApprovalRequest as ApprovalRequest } from "@/lib/moduleRegistry";

export type LinkedReceipt = components["schemas"]["LinkedReceiptSchema"];

export const purchaseOrdersApi = {
  getAll: async (
    params: PurchaseOrderListParams = {},
  ): Promise<PurchaseOrderListResponse> => {
    const response = await api.get<PurchaseOrderListResponse>(
      "/purchase-orders",
      { params },
    );
    return response.data;
  },

  getById: async (id: string): Promise<PurchaseOrder> => {
    const response = await api.get<PurchaseOrder>(`/purchase-orders/${id}`);
    return response.data;
  },

  create: async (data: PurchaseOrderCreate): Promise<PurchaseOrder> => {
    const response = await api.post<PurchaseOrder>("/purchase-orders", data);
    return response.data;
  },

  update: async (
    id: string,
    data: PurchaseOrderUpdate,
  ): Promise<PurchaseOrder> => {
    const response = await api.patch<PurchaseOrder>(
      `/purchase-orders/${id}`,
      data,
    );
    return response.data;
  },

  confirm: async (id: string): Promise<PurchaseOrder> => {
    const response = await api.post<PurchaseOrder>(
      `/purchase-orders/${id}/confirm`,
    );
    return response.data;
  },

  cancel: async (id: string): Promise<PurchaseOrder> => {
    const response = await api.post<PurchaseOrder>(
      `/purchase-orders/${id}/cancel`,
    );
    return response.data;
  },

  getLinkedReceipts: async (id: string): Promise<LinkedReceipt[]> => {
    return getEveryPage<LinkedReceipt>(
      `/purchase-orders/${id}/linked-receipts`,
    );
  },

  getPendingQuantities: async (id: string): Promise<Record<string, string>> => {
    const response = await api.get<Record<string, string>>(
      `/purchase-orders/${id}/pending-quantities`,
    );
    return response.data;
  },

  getPdf: async (id: string, lang = "en"): Promise<Blob> => {
    const response = await api.get(`/purchase-orders/${id}/pdf`, {
      params: { lang },
      responseType: "blob",
    });
    return response.data;
  },

  sendEmail: async (
    id: string,
    lang = "en",
  ): Promise<{ status: string; message: string }> => {
    const response = await api.post<{ status: string; message: string }>(
      `/purchase-orders/${id}/send-email`,
      null,
      { params: { lang } },
    );
    return response.data;
  },

  // ── Approval ──────────────
  requestApproval: async (id: string): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>(
      `/purchase-orders/${id}/request-approval`,
    );
    return response.data;
  },

  approvePO: async (id: string, notes?: string): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>(
      `/purchase-orders/${id}/approve`,
      { notes },
    );
    return response.data;
  },

  rejectPO: async (id: string, notes?: string): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>(
      `/purchase-orders/${id}/reject`,
      { notes },
    );
    return response.data;
  },

  // ── The approvals engine, as the order screens read it ──
  // Its HTTP routes are what the approvals module publishes. Its files are
  // not this module's to import: approvals is optional here, and an import
  // cannot be. The answers land under the approvals module's own query keys
  // (see the hooks), so the two modules share one cache entry per question.
  listApprovalRequests: async (): Promise<Page<ApprovalRequest>> => {
    const response = await api.get<Page<ApprovalRequest>>(
      "/approvals/requests",
      { params: { target_type: "purchase_order" } },
    );
    return response.data;
  },

  getApprovalRequirement: async (
    poId: string,
  ): Promise<components["schemas"]["PurchaseOrderApprovalRequirement"]> => {
    const response = await api.get<
      components["schemas"]["PurchaseOrderApprovalRequirement"]
    >(`/purchase-orders/${poId}/approval-requirement`);
    return response.data;
  },

  getApprovalWorkflowConfigured: async (): Promise<
    components["schemas"]["WorkflowConfigured"]
  > => {
    const response = await api.get<components["schemas"]["WorkflowConfigured"]>(
      "/approvals/workflows/configured",
      { params: { target_type: "purchase_order" } },
    );
    return response.data;
  },

  getPOSettings: async (): Promise<POSettings> => {
    const response = await api.get<POSettings>("/purchase-orders/settings");
    return response.data;
  },

  updatePOSettings: async (data: POSettingsUpdate): Promise<POSettings> => {
    const response = await api.put<POSettings>(
      "/purchase-orders/settings",
      data,
    );
    return response.data;
  },
};
