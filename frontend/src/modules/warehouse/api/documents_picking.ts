import { api, getEveryPage } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

export type WmsPickLine = components["schemas"]["WmsPickLineOut"];

export type WmsPickSession = components["schemas"]["WmsPickSessionOut"];

/** A dispatch of a selection that stock cannot cover, and what is missing. */
export type WmsPickUncoveredDocument =
  components["schemas"]["WmsPickUncoveredDocumentOut"];

export interface WmsPickScanResult {
  status:
    | "picked"
    | "rejected"
    | "all_picked"
    | "not_found"
    | "not_in_document"
    | "already_picked"
    | "line_skipped"
    | "over_quantity"
    | "wrong_lot"
    | "lot_too_small"
    | "shelf_confirmed"
    | "shelf_required"
    | "wrong_shelf"
    | "short_pick_confirmed";
  line_id: string | null;
  product_name: string | null;
  picked_quantity: number;
  expected_quantity: number;
  uom_symbol: string | null;
  bin_location: string | null;
  lot_name: string | null;
  planned_lot_name: string | null;
  shelf?: string | null;
  shelf_id?: string | null;
  message: string;
  session_complete: boolean;
}

export const documentsPickingApi = {
  startWmsPicking: async (documentId: string): Promise<WmsPickSession> => {
    const response = await api.post<WmsPickSession>(
      `/warehouse/documents/${documentId}/picking/start`,
    );
    return response.data;
  },

  /** The paper pick list of a confirmed dispatch, lines in walk order. */
  dispatchPickListPdf: async (
    documentId: string,
    lang: string,
  ): Promise<Blob> => {
    const response = await api.get<Blob>(
      `/warehouse/documents/${documentId}/pick-list`,
      { params: { lang }, responseType: "blob" },
    );
    return response.data;
  },

  /** The paper pick list of a session, over all its dispatches, in the screen's order. */
  sessionPickListPdf: async (
    documentId: string,
    sessionId: string,
    lang: string,
  ): Promise<Blob> => {
    const response = await api.get<Blob>(
      `/warehouse/documents/${documentId}/picking/${sessionId}/pick-list`,
      { params: { lang }, responseType: "blob" },
    );
    return response.data;
  },

  /** One session over several confirmed dispatches, in the order given. */
  startWmsPickingDocuments: async (
    documentIds: string[],
  ): Promise<WmsPickSession> => {
    const response = await api.post<WmsPickSession>(
      "/warehouse/picking/start",
      {
        document_ids: documentIds,
      },
    );
    return response.data;
  },

  /** The dispatches of a selection that stock cannot cover; empty when all are covered. */
  wmsPickingCoverage: async (
    documentIds: string[],
  ): Promise<WmsPickUncoveredDocument[]> => {
    const response = await api.post<
      components["schemas"]["WmsPickCoverageOut"]
    >("/warehouse/picking/coverage", { document_ids: documentIds });
    return response.data.documents;
  },

  wmsPickingScan: async (
    documentId: string,
    sessionId: string,
    data: { barcode: string; quantity?: number; lot_name?: string },
  ): Promise<WmsPickScanResult> => {
    const response = await api.post<WmsPickScanResult>(
      `/warehouse/documents/${documentId}/picking/${sessionId}/scan`,
      data,
    );
    return response.data;
  },

  wmsPickingShortPick: async (
    documentId: string,
    sessionId: string,
    lineId: string,
    pickedQuantity: number,
    discrepancyCode?: string,
    discrepancyReason?: string,
    replaceScans = false,
  ): Promise<WmsPickScanResult> => {
    const response = await api.post<WmsPickScanResult>(
      `/warehouse/documents/${documentId}/picking/${sessionId}/short-pick`,
      {
        line_id: lineId,
        picked_quantity: pickedQuantity,
        discrepancy_code: discrepancyCode,
        discrepancy_reason: discrepancyReason,
        replace_scans: replaceScans,
      },
    );
    return response.data;
  },

  wmsPickingComplete: async (
    documentId: string,
    sessionId: string,
  ): Promise<WmsPickSession> => {
    const response = await api.post<WmsPickSession>(
      `/warehouse/documents/${documentId}/picking/${sessionId}/complete`,
    );
    return response.data;
  },

  wmsPickingUndo: async (
    documentId: string,
    sessionId: string,
    lineId: string,
  ): Promise<{
    line_id: string;
    product_name: string | null;
    restored_quantity: number;
  }> => {
    const response = await api.post(
      `/warehouse/documents/${documentId}/picking/${sessionId}/undo`,
      null,
      { params: { line_id: lineId } },
    );
    return response.data;
  },

  wmsPickingSkip: async (
    documentId: string,
    sessionId: string,
    lineId: string,
  ): Promise<WmsPickScanResult> => {
    const response = await api.post<WmsPickScanResult>(
      `/warehouse/documents/${documentId}/picking/${sessionId}/skip`,
      null,
      { params: { line_id: lineId } },
    );
    return response.data;
  },

  wmsPickingCancel: async (
    documentId: string,
    sessionId: string,
  ): Promise<void> => {
    await api.post(
      `/warehouse/documents/${documentId}/picking/${sessionId}/cancel`,
    );
  },

  /** The sheet closed: the session keeps its scans and stops holding the
   * document. */
  wmsPickingPause: async (
    documentId: string,
    sessionId: string,
  ): Promise<void> => {
    await api.post(
      `/warehouse/documents/${documentId}/picking/${sessionId}/pause`,
    );
  },

  wmsPickingRelease: async (
    documentId: string,
    sessionId: string,
  ): Promise<void> => {
    await api.post(
      `/warehouse/documents/${documentId}/picking/${sessionId}/release`,
    );
  },

  wmsPickingTakeOver: async (
    documentId: string,
    sessionId: string,
  ): Promise<WmsPickSession> => {
    const response = await api.post<WmsPickSession>(
      `/warehouse/documents/${documentId}/picking/${sessionId}/take-over`,
    );
    return response.data;
  },

  listWmsPickingSessions: async (
    documentId: string,
  ): Promise<WmsPickSession[]> =>
    getEveryPage<WmsPickSession>(`/warehouse/documents/${documentId}/picking`),
};
