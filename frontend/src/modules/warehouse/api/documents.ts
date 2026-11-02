import { api, getEveryPage } from "@/lib/api/client";
import type { components } from "@/types/api-generated";
import type { TargetApprovalRequest } from "@/lib/moduleRegistry";
import type {
  CorrectionCreate,
  DocumentCompletePayload,
  DocumentDiscrepancyCode,
  DocumentSummary,
  InventoryPeriod,
  WarehouseDocument,
  DocumentCreate,
  DocumentUpdate,
  DocumentListResponse,
  DocumentRowListResponse,
  DocumentsTodoResponse,
  WorkItem,
  WorkItemMeasures,
  OpeningStockImportResponse,
  DocumentTrackingPayload,
  DocumentType,
  DocumentStatus,
  DocumentProfile,
  DocumentProfileUpdate,
  PickOrderStrategy,
  DocumentApproval,
  DocumentApprovalRequirement,
  RegisterParams,
  RegisterResponse,
  RegisterRowsParams,
  RegisterRowsResponse,
  ReplenishmentMove,
  ReplenishmentProposal,
  ReturnCreate,
} from "@/modules/warehouse/types";
import { documentsProductsApi } from "./documents_products";
import { documentsPickingApi } from "./documents_picking";

export type {
  ProductSearchResult,
  CatalogueSearchResult,
} from "./documents_products";
export type { WmsPickLine, WmsPickSession } from "./documents_picking";

type SheetAnalysis = components["schemas"]["SheetAnalysisResponse"];

/** The posted move of a put-away, and the home-location offer it raised. */
type PutawayDone = components["schemas"]["PutawayDone"];

export interface DocumentsListParams {
  search?: string;
  /** Only these documents, organization-scoped — a trail naming its sources. */
  ids?: string[];
  /** One type, or several joined by commas ("IN,OUT") for a mixed list. */
  type?: DocumentType | string;
  /** One status, or several joined by commas ("DRAFT,CONFIRMED"). */
  status?: DocumentStatus | string;
  discrepancy_code?: DocumentDiscrepancyCode;
  partner_id?: string;
  date_from?: string;
  date_to?: string;
  /** Only documents posted at or after this moment (ISO instant). */
  completed_from?: string;
  /** Only documents posted at or before this moment (ISO instant). */
  completed_to?: string;
  /** Only documents on this place or a place under it — one warehouse. */
  location_id?: string;
  /**
   * Filters modules add to the list, each `<module>:<name>` as the module
   * registered it on the server; several narrow together.
   */
  module_filter?: string[];
  limit?: number;
  offset?: number;
  sort_by?:
    | "number"
    | "document_date"
    | "created_at"
    | "completed_at"
    | "type"
    | "status";
  sort_order?: "asc" | "desc";
}

export type PriceHint = components["schemas"]["PriceHintResponse"];

export const documentsApi = {
  /** Headers and the first rows of a sheet, for a document import mapping step. */
  analyzeImportSheet: async (file: File): Promise<SheetAnalysis> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<SheetAnalysis>(
      "/warehouse/import/analyze",
      formData,
    );
    return response.data;
  },

  /** One draft receipt, flagged as opening stock, out of a whole sheet. */
  importOpeningStock: async (
    file: File,
    mapping: unknown,
    targetLocationId: string,
  ): Promise<OpeningStockImportResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mapping_json", JSON.stringify(mapping));
    formData.append("target_location_id", targetLocationId);
    const response = await api.post<OpeningStockImportResponse>(
      "/warehouse/import/opening-stock",
      formData,
    );
    return response.data;
  },

  list: async (
    params?: DocumentsListParams,
  ): Promise<DocumentRowListResponse> => {
    const response = await api.get<DocumentRowListResponse>(
      "/warehouse/documents",
      {
        params,
        // `ids` and `module_filter` repeat (?ids=a&ids=b); axios would
        // otherwise send ids[]=a, a name the server does not read, and the
        // list came back unfiltered.
        paramsSerializer: { indexes: null },
      },
    );
    return response.data;
  },

  /** The floor's queue: the tasks, and what waits for a decision. */
  todo: async (params: {
    date_to: string;
    limit?: number;
    /** Tasks to list when that is more than `limit` (the server caps it). */
    work_limit?: number;
    /** Narrow the tasks on the server, before they are cut to a page. */
    view?: "all" | "mine" | "overdue";
    /** Only the tasks in one board column. */
    state?: "todo" | "in_progress" | "done";
    /** Only one person's tasks (a user id), or `none` for nobody's. */
    assignee?: string;
    /** Only the documents and put-away tasks of one warehouse. */
    location_id?: string;
    /** Also list what was finished in the last day, after the open tasks. */
    include_done?: boolean;
    /** Also list what was finished since this instant (at most a day back). */
    done_since?: string;
  }): Promise<DocumentsTodoResponse> => {
    const response = await api.get<DocumentsTodoResponse>("/warehouse/todo", {
      params,
    });
    return response.data;
  },

  /** This week's dock-to-stock time and same-day shipping, from the records. */
  workMeasures: async (): Promise<WorkItemMeasures> => {
    const response = await api.get<WorkItemMeasures>(
      "/warehouse/work-items/measures",
    );
    return response.data;
  },

  /** Begin the count a schedule asks for; answers with the stock take made. */
  startCount: async (scheduleId: string): Promise<{ id: string }> => {
    const response = await api.post<{ id: string }>(
      `/stock-takes/cycle-count-schedules/${scheduleId}/run`,
    );
    return response.data;
  },

  /** Give a task to a person, or to nobody with `null`. With
   * `onlyIfUnassigned` the server claims it only while nobody holds it and
   * answers 409 when somebody else took it first. */
  assignWorkItem: async (
    sourceKind: string,
    sourceId: string,
    assigneeId: string | null,
    options: { onlyIfUnassigned?: boolean } = {},
  ): Promise<void> => {
    await api.put(`/warehouse/work-items/${sourceKind}/${sourceId}/assignee`, {
      assignee_id: assigneeId,
      ...(options.onlyIfUnassigned ? { only_if_unassigned: true } : {}),
    });
  },

  createCustomWorkItem: async (payload: {
    title: string;
    due_date?: string | null;
    assignee_id?: string | null;
  }): Promise<WorkItem> => {
    const response = await api.post<WorkItem>(
      "/warehouse/work-items/custom",
      payload,
    );
    return response.data;
  },

  setCustomWorkItemDone: async (id: string, done: boolean): Promise<void> => {
    await api.put(`/warehouse/work-items/custom/${id}/done`, { done });
  },

  deleteCustomWorkItem: async (id: string): Promise<void> => {
    await api.delete(`/warehouse/work-items/custom/${id}`);
  },

  /** Put away what a receipt line left in a receiving area: posts the move to `locationId`. */
  putAwayWorkItem: async (vars: {
    lineId: string;
    locationId: string;
    /** The shelf label scanned to confirm the place, when the profile asks. */
    scannedCode?: string;
  }): Promise<PutawayDone> => {
    const response = await api.post<PutawayDone>(
      `/warehouse/work-items/putaway/${vars.lineId}`,
      { location_id: vars.locationId, scanned_code: vars.scannedCode ?? null },
    );
    return response.data;
  },

  /** The reserve move a reorder rule's alert proposes, with its lines. */
  getReplenishmentProposal: async (
    ruleId: string,
  ): Promise<ReplenishmentProposal> => {
    const response = await api.get<ReplenishmentProposal>(
      `/purchase-orders/replenishment/proposals/${ruleId}`,
    );
    return response.data;
  },

  /** Post the proposed move; the shelf scan is required where the profile says so. */
  postReplenishmentProposal: async (vars: {
    ruleId: string;
    scannedCode?: string;
  }): Promise<ReplenishmentMove> => {
    const response = await api.post<ReplenishmentMove>(
      `/purchase-orders/replenishment/proposals/${vars.ruleId}/move`,
      null,
      {
        params: vars.scannedCode
          ? { scanned_code: vars.scannedCode }
          : undefined,
      },
    );
    return response.data;
  },

  listAwaitingMyApproval: async (params?: {
    offset?: number;
    limit?: number;
  }): Promise<DocumentListResponse> => {
    const response = await api.get<DocumentListResponse>(
      "/warehouse/awaiting-my-approval",
      { params },
    );
    return response.data;
  },

  // suggested unit price for a product on a document.
  priceHint: async (params: {
    template_id: string;
    partner_id?: string | null;
  }): Promise<PriceHint> => {
    const response = await api.get<PriceHint>("/warehouse/price-hint", {
      params: {
        template_id: params.template_id,
        ...(params.partner_id ? { partner_id: params.partner_id } : {}),
      },
    });
    return response.data;
  },

  getById: async (id: string): Promise<WarehouseDocument> => {
    const response = await api.get<WarehouseDocument>(
      `/warehouse/documents/${id}`,
    );
    return response.data;
  },

  create: async (data: DocumentCreate): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      "/warehouse/documents",
      data,
    );
    return response.data;
  },

  /**
   * Create a whole document and post it in one transaction — the one-screen
   * receive, issue and move actions. Answers the document at COMPLETED, or
   * at PENDING_APPROVAL when the profile requires an approval first. A
   * refusal writes nothing. The key names the press: sent again, it is
   * answered with the document the first send made instead of a second.
   */
  postNew: async (
    data: DocumentCreate,
    key: string,
    /** The reader said yes to the surplus the server asked about. */
    confirmSurplus = false,
  ): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      "/warehouse/documents/post",
      data,
      {
        headers: { "Idempotency-Key": key },
        params: confirmSurplus ? { confirm_surplus: true } : undefined,
      },
    );
    return response.data;
  },

  update: async (
    id: string,
    data: DocumentUpdate,
  ): Promise<WarehouseDocument> => {
    const response = await api.put<WarehouseDocument>(
      `/warehouse/documents/${id}`,
      data,
    );
    return response.data;
  },

  setLineTarget: async (
    docId: string,
    lineId: string,
    targetLocationId: string | null,
  ): Promise<WarehouseDocument> => {
    const response = await api.patch<WarehouseDocument>(
      `/warehouse/documents/${docId}/lines/${lineId}`,
      { target_location_id: targetLocationId },
    );
    return response.data;
  },

  /** Replace one module's fields on the document, or on one of its lines. */
  setMetaData: async ({
    docId,
    lineId,
    module,
    values,
  }: {
    docId: string;
    lineId?: string;
    module: string;
    values: Record<string, unknown> | null;
  }): Promise<WarehouseDocument> => {
    const key = encodeURIComponent(module);
    const body = values ?? {};
    const response = lineId
      ? await api.put<WarehouseDocument>(
          `/warehouse/documents/${docId}/lines/${lineId}/meta-data/${key}`,
          body,
        )
      : await api.put<WarehouseDocument>(
          `/warehouse/documents/${docId}/meta-data/${key}`,
          body,
        );
    return response.data;
  },

  confirm: async (id: string): Promise<WarehouseDocument> => {
    const response = await api.patch<WarehouseDocument>(
      `/warehouse/documents/${id}/confirm`,
    );
    return response.data;
  },

  /**
   * Confirm and complete a draft as one action. Returns the document at
   * COMPLETED, or at PENDING_APPROVAL when the profile requires an approval
   * (which will complete it when granted).
   */
  postNow: async (
    id: string,
    data?: DocumentTrackingPayload,
  ): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      `/warehouse/documents/${id}/post`,
      data,
    );
    return response.data;
  },

  duplicate: async (id: string): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      `/warehouse/documents/${id}/duplicate`,
    );
    return response.data;
  },

  complete: async (
    id: string,
    data?: DocumentCompletePayload,
  ): Promise<WarehouseDocument> => {
    const response = await api.patch<WarehouseDocument>(
      `/warehouse/documents/${id}/complete`,
      data,
    );
    return response.data;
  },

  cancel: async (id: string): Promise<WarehouseDocument> => {
    const response = await api.patch<WarehouseDocument>(
      `/warehouse/documents/${id}/cancel`,
    );
    return response.data;
  },

  /** Reverse a just-posted receipt, issue or move in one call. Answers with
   * the reversing document — a correction, or a return for a move. */
  undo: async (id: string): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      `/warehouse/documents/${id}/undo`,
    );
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/warehouse/documents/${id}`);
  },

  downloadPdf: async (id: string, lang = "en"): Promise<Blob> => {
    const response = await api.get<Blob>(`/warehouse/documents/${id}/pdf`, {
      params: { lang },
      responseType: "blob",
    });
    return response.data;
  },

  /** The chosen documents as one PDF, in the order of ``ids``. */
  downloadPdfBatch: async (ids: string[], lang = "en"): Promise<Blob> => {
    const query = new URLSearchParams(ids.map((id) => ["ids", id]));
    query.set("lang", lang);
    const response = await api.get<Blob>(`/warehouse/documents/pdf?${query}`, {
      responseType: "blob",
    });
    return response.data;
  },

  createCorrection: async (
    data: CorrectionCreate,
  ): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      "/warehouse/corrections",
      data,
    );
    return response.data;
  },

  listCorrections: async (documentId: string): Promise<DocumentSummary[]> =>
    getEveryPage<DocumentSummary>(
      `/warehouse/documents/${documentId}/corrections`,
    ),

  createReturn: async (
    documentId: string,
    data: ReturnCreate,
  ): Promise<WarehouseDocument> => {
    const response = await api.post<WarehouseDocument>(
      `/warehouse/documents/${documentId}/return`,
      data,
    );
    return response.data;
  },

  getRegisterSummary: async (
    params: RegisterParams,
  ): Promise<RegisterResponse> => {
    const response = await api.get<RegisterResponse>(
      "/warehouse/register/summary",
      {
        params,
      },
    );
    return response.data;
  },

  getRegisterRows: async (
    params: RegisterRowsParams,
  ): Promise<RegisterRowsResponse> => {
    const response = await api.get<RegisterRowsResponse>(
      "/warehouse/register/rows",
      { params },
    );
    return response.data;
  },

  getRegisterCsv: async (params: RegisterParams): Promise<Blob> => {
    const response = await api.get<Blob>("/warehouse/register", {
      params: { ...params, output_format: "csv" },
      responseType: "blob",
      headers: { Accept: "text/csv" },
    });
    return response.data;
  },

  ...documentsProductsApi,
  ...documentsPickingApi,
};

export const documentProfileApi = {
  getProfile: async (): Promise<DocumentProfile> => {
    const response = await api.get<DocumentProfile>("/warehouse/profile");
    return response.data;
  },

  updateProfile: async (
    data: DocumentProfileUpdate,
  ): Promise<DocumentProfile> => {
    const response = await api.put<DocumentProfile>("/warehouse/profile", data);
    return response.data;
  },

  applyPreset: async (preset: string): Promise<DocumentProfile> => {
    const response = await api.post<DocumentProfile>(
      `/warehouse/profile/apply-preset/${encodeURIComponent(preset)}`,
    );
    return response.data;
  },

  getPresets: async (): Promise<string[]> => {
    const response = await api.get<string[]>("/warehouse/profile/presets");
    return response.data;
  },

  /** The registered pick orders, for the profile's chooser. */
  getPickOrderStrategies: async (): Promise<PickOrderStrategy[]> => {
    const response = await api.get<PickOrderStrategy[]>(
      "/warehouse/profile/pick-order-strategies",
    );
    return response.data;
  },

  getPresetValues: async (name: string): Promise<DocumentProfileUpdate> => {
    const response = await api.get<DocumentProfileUpdate>(
      `/warehouse/profile/presets/${encodeURIComponent(name)}`,
    );
    return response.data;
  },
};

export const documentApprovalApi = {
  requestApproval: async (
    docId: string,
    notes?: string,
  ): Promise<DocumentApproval> => {
    // Must go through the document's own approval route: it parks the
    // document in PENDING_APPROVAL. The generic
    // POST /approvals/requests creates the request but leaves the document
    // status untouched, so the doc becomes invisible to the "Pending
    // Approval" status filter on the Documents list.
    const response = await api.post<DocumentApproval>(
      `/approvals/documents/${docId}/request-approval`,
      null,
      { params: notes ? { notes } : undefined },
    );
    return response.data;
  },
  approve: async (docId: string, notes?: string): Promise<DocumentApproval> => {
    const response = await api.post<DocumentApproval>(
      `/approvals/documents/${docId}/approve`,
      null,
      { params: notes ? { notes } : undefined },
    );
    return response.data;
  },
  reject: async (docId: string, notes?: string): Promise<DocumentApproval> => {
    // The route the inline Documents queue uses: it finds the document's
    // open request itself. The rejection returns the doc to DRAFT (rework
    // loop) and notifies the requester whichever door decides it.
    const response = await api.post<DocumentApproval>(
      `/approvals/documents/${docId}/reject`,
      null,
      { params: notes ? { notes } : undefined },
    );
    return response.data;
  },
  get: async (docId: string): Promise<TargetApprovalRequest | null> => {
    const response = await api.get<TargetApprovalRequest | null>(
      `/approvals/documents/${docId}/approval`,
    );
    return response.data ?? null;
  },
  getRequirement: async (
    docId: string,
  ): Promise<DocumentApprovalRequirement> => {
    const response = await api.get<DocumentApprovalRequirement>(
      `/approvals/documents/${docId}/approval-requirement`,
    );
    return response.data;
  },
};

export const inventoryPeriodsApi = {
  list: async (year?: number): Promise<InventoryPeriod[]> =>
    getEveryPage<InventoryPeriod>(
      "/warehouse/periods",
      year ? { year } : undefined,
    ),

  close: async (
    year: number,
    month: number,
    notes?: string,
  ): Promise<InventoryPeriod> => {
    const response = await api.post<InventoryPeriod>(
      `/warehouse/periods/${year}/${month}/close`,
      notes ? { notes } : undefined,
    );
    return response.data;
  },

  reopen: async (
    year: number,
    month: number,
    notes?: string,
  ): Promise<InventoryPeriod> => {
    const response = await api.post<InventoryPeriod>(
      `/warehouse/periods/${year}/${month}/reopen`,
      notes ? { notes } : undefined,
    );
    return response.data;
  },
};
