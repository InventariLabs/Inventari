import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";
import type { WithServerDefaults } from "@/types/request";

export type StageDefinition = components["schemas"]["StageDefinition"];

export type ApprovalWorkflow = components["schemas"]["WorkflowSchema"];

export type ApprovalDecision = components["schemas"]["ApprovalDecisionSchema"];

/**
 * What the module behind a request says about its own target.
 *
 * Every consumer fills the same shape; the document-only fields (`type`, the
 * location route) are optional because a purchase order has no equivalent.
 */
export interface ApprovalTargetSummary {
  id: string;
  number: string;
  type?: string | null;
  partner_name: string | null;
  total_value: string | null;
  currency: string | null;
  lines_count: number;
  source_location_name?: string | null;
  target_location_name?: string | null;
  // document: the one-step action submitted it to be posted, so the approval
  // moves the stock rather than leaving it for a later execution step.
  posts_on_approval?: boolean;
  // equipment_checkout: the asset's serial number names the specific unit
  // (equipment has no document-style number — ``number`` is the asset name).
  serial_number?: string | null;
}

/**
 * The wire types `target_summary` as a free dictionary and
 * `undecidable_reason` as a string; the screens read the shapes the backend
 * actually fills, so those two members are narrowed. Everything else is the
 * schema's own.
 */
export type ApprovalRequest = Omit<
  components["schemas"]["ApprovalRequestSchema"],
  "target_summary" | "undecidable_reason"
> & {
  target_summary?: ApprovalTargetSummary | null;
  undecidable_reason?: UndecidableReason | null;
};

/**
 * Why a stage has nobody who could decide it. The three dead ends: a stage
 * left open to "anyone with the grant" in an organization that has granted
 * it to nobody; a stage naming people who cannot see approvals at all; and
 * an open stage whose only holder of the grant is the requester the door
 * refuses a self-decision to.
 */
export type UndecidableReason =
  | "no_approver_in_organization"
  | "named_approvers_cannot_decide"
  | "only_the_requester_can_decide";

export type WorkflowCreate = components["schemas"]["WorkflowCreate"];

export type WorkflowUpdate = components["schemas"]["WorkflowUpdate"];

/** What a caller sends: the unsaid defaults stay the server's, a PATCH leaves what it omits unchanged. */
export type WorkflowCreateInput = WithServerDefaults<
  WorkflowCreate,
  "allow_undecidable_stages" | "is_active"
>;
export type WorkflowUpdateInput = Partial<WorkflowUpdate>;

interface ApprovalRequestListResponse {
  items: ApprovalRequest[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/**
 * What became of a workflow the user deleted. A workflow that already carries
 * decisions is archived rather than removed — the approvals taken under it
 * outlive it.
 */
export type WorkflowDeletionResult =
  components["schemas"]["WorkflowDeletionResult"];

/** What switching a workflow off would release, and what still demands approval. */
export type WorkflowWaiting = components["schemas"]["WorkflowWaiting"];

/** Whether a request for this target type would land anywhere. */
export type WorkflowConfigured = components["schemas"]["WorkflowConfigured"];

/**
 * The code the API attaches to a workflow refused for a stage nobody could
 * decide. The save offers to go ahead anyway, so the screen has to tell this
 * refusal from the other conflicts without reading a translated sentence.
 */
export const STAGE_UNSOLVABLE_CODE = "APPROVAL_STAGE_UNSOLVABLE";

/**
 * The decide routes of the targets that own one. Each decides the request and
 * moves its target in the same step: a document is confirmed or returned to
 * its draft, a purchase order released or rejected. The generic stage
 * endpoint decides the request alone, and a document approved through it
 * stays parked in PENDING_APPROVAL.
 *
 * The routes are what the warehouse and the purchase orders publish over
 * HTTP; their client files are theirs, and an import of them would make this
 * module fail to build wherever either is absent.
 */
export const targetDecisionApi: Record<
  string,
  {
    approve: (targetId: string, notes?: string) => Promise<unknown>;
    reject: (targetId: string, notes?: string) => Promise<unknown>;
  }
> = {
  document: {
    approve: async (id, notes) =>
      (await api.post(`/approvals/documents/${id}/approve`, { notes })).data,
    reject: async (id, notes) =>
      (await api.post(`/approvals/documents/${id}/reject`, { notes })).data,
  },
  purchase_order: {
    approve: async (id, notes) =>
      (await api.post(`/purchase-orders/${id}/approve`, { notes })).data,
    reject: async (id, notes) =>
      (await api.post(`/purchase-orders/${id}/reject`, { notes })).data,
  },
};

export const approvalsApi = {
  listWorkflows: async (): Promise<ApprovalWorkflow[]> => {
    return getEveryPage<ApprovalWorkflow>("/approvals/workflows");
  },

  /**
   * Whether a request for this target type would land — an active workflow
   * with at least one stage, the engine's own test before it writes one.
   *
   * Answered to any member, deliberately without `approvals:read`: the
   * account composing a request may hold only the target module's write
   * right, and the workflow list is filtered by the read grant, so for
   * that account an empty list says nothing.
   */
  getWorkflowConfigured: async (
    targetType: string,
  ): Promise<WorkflowConfigured> => {
    const response = await api.get<WorkflowConfigured>(
      "/approvals/workflows/configured",
      { params: { target_type: targetType } },
    );
    return response.data;
  },

  createWorkflow: async (
    data: WorkflowCreateInput,
  ): Promise<ApprovalWorkflow> => {
    const response = await api.post<ApprovalWorkflow>(
      "/approvals/workflows",
      data,
    );
    return response.data;
  },

  updateWorkflow: async (
    id: string,
    data: WorkflowUpdateInput,
  ): Promise<ApprovalWorkflow> => {
    const response = await api.patch<ApprovalWorkflow>(
      `/approvals/workflows/${id}`,
      data,
    );
    return response.data;
  },

  getWorkflowWaiting: async (id: string): Promise<WorkflowWaiting> => {
    const response = await api.get<WorkflowWaiting>(
      `/approvals/workflows/${id}/waiting`,
    );
    return response.data;
  },

  deleteWorkflow: async (id: string): Promise<WorkflowDeletionResult> => {
    const response = await api.delete<WorkflowDeletionResult>(
      `/approvals/workflows/${id}`,
    );
    return response.data;
  },

  listRequests: async (params?: {
    target_type?: string;
    status?: string;
    search?: string;
    offset?: number;
    limit?: number;
  }): Promise<ApprovalRequestListResponse> => {
    const response = await api.get<ApprovalRequestListResponse>(
      "/approvals/requests",
      { params },
    );
    return response.data;
  },

  getRequest: async (id: string): Promise<ApprovalRequest> => {
    const response = await api.get<ApprovalRequest>(
      `/approvals/requests/${id}`,
    );
    return response.data;
  },

  requestApproval: async (
    targetType: string,
    targetId: string,
  ): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>("/approvals/requests", {
      target_type: targetType,
      target_id: targetId,
    });
    return response.data;
  },

  approveStage: async (
    id: string,
    notes?: string,
  ): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>(
      `/approvals/requests/${id}/approve`,
      { notes },
    );
    return response.data;
  },

  rejectRequest: async (
    id: string,
    notes?: string,
  ): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>(
      `/approvals/requests/${id}/reject`,
      { notes },
    );
    return response.data;
  },

  cancelRequest: async (id: string): Promise<ApprovalRequest> => {
    const response = await api.post<ApprovalRequest>(
      `/approvals/requests/${id}/cancel`,
    );
    return response.data;
  },
};
