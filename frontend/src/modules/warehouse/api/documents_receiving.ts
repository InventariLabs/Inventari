import { api, getEveryPage } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

/**
 * The whole row, taken from the schema rather than written out again.
 *
 * The status word was the first field to come from the contract, after the
 * hand-written union stopped agreeing with the server: a line received in
 * full arrived as "picked", a word this file has never had, and every
 * reader of it fell through to "pending". The rest of the row stayed
 * hand-written and therefore outside the gate, so a field added on the
 * server reached this file only when somebody remembered. Taking the type
 * entire is what makes `make check-api-types` answer for the row — and it
 * retires the separate status alias, which had no readers left of its own.
 */
export type WmsReceiveLine = components["schemas"]["WmsReceiveLineOut"];

export type WmsReceiveSession = components["schemas"]["WmsReceiveSessionOut"];

export interface WmsReceiveScanResult {
  status:
    | "received"
    | "short"
    | "rejected"
    | "all_received"
    | "not_found"
    | "not_in_document"
    | "already_received"
    | "over_quantity"
    | "lot_too_small"
    | "shelf_confirmed"
    | "shelf_required"
    | "wrong_shelf"
    | "identified"
    | "needs_lot_expiry"
    | "needs_surplus_confirmation"
    | "short_receive_confirmed";
  line_id: string | null;
  product_name: string | null;
  received_quantity: number;
  expected_quantity: number;
  uom_symbol: string | null;
  shelf?: string | null;
  shelf_id?: string | null;
  lot_name?: string | null;
  message: string;
  session_complete: boolean;
}

interface WmsReceiveUndoResult {
  line_id: string;
  product_name: string | null;
  restored_quantity: number;
}

export const documentsReceivingApi = {
  startWmsReceiving: async (documentId: string): Promise<WmsReceiveSession> => {
    const response = await api.post<WmsReceiveSession>(
      `/warehouse/documents/${documentId}/receiving/start`,
    );
    return response.data;
  },

  wmsReceivingScan: async (
    documentId: string,
    sessionId: string,
    data: {
      barcode?: string;
      quantity?: number;
      batch_number?: string;
      expiry_date?: string;
      /** Only name the line the code matches; count nothing. */
      identify?: boolean;
    },
    /** The worker said yes to the surplus the session asked about. */
    confirmSurplus = false,
  ): Promise<WmsReceiveScanResult> => {
    const response = await api.post<WmsReceiveScanResult>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/scan`,
      data,
      { params: confirmSurplus ? { confirm_surplus: true } : undefined },
    );
    return response.data;
  },

  wmsReceivingShortReceive: async (
    documentId: string,
    sessionId: string,
    lineId: string,
    receivedQuantity: number,
    discrepancyCode?: string,
    discrepancyReason?: string,
    replaceScans = false,
    heldQuantity = 0,
    tracking?: { batch_number?: string; expiry_date?: string },
    confirmSurplus = false,
  ): Promise<WmsReceiveScanResult> => {
    const response = await api.post<WmsReceiveScanResult>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/short-receive`,
      {
        line_id: lineId,
        received_quantity: receivedQuantity,
        // The schema takes a code from its enum or none; a blank is a 422.
        discrepancy_code: discrepancyCode || undefined,
        discrepancy_reason: discrepancyReason,
        held_quantity: heldQuantity,
        replace_scans: replaceScans,
        ...tracking,
      },
      { params: confirmSurplus ? { confirm_surplus: true } : undefined },
    );
    return response.data;
  },

  wmsReceivingComplete: async (
    documentId: string,
    sessionId: string,
  ): Promise<WmsReceiveSession> => {
    const response = await api.post<WmsReceiveSession>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/complete`,
    );
    return response.data;
  },

  wmsReceivingUndo: async (
    documentId: string,
    sessionId: string,
    lineId: string,
  ): Promise<WmsReceiveUndoResult> => {
    const response = await api.post<WmsReceiveUndoResult>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/undo`,
      null,
      { params: { line_id: lineId } },
    );
    return response.data;
  },

  wmsReceivingSkip: async (
    documentId: string,
    sessionId: string,
    lineId: string,
  ): Promise<WmsReceiveScanResult> => {
    const response = await api.post<WmsReceiveScanResult>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/skip`,
      null,
      { params: { line_id: lineId } },
    );
    return response.data;
  },

  wmsReceivingCancel: async (
    documentId: string,
    sessionId: string,
  ): Promise<void> => {
    await api.post(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/cancel`,
    );
  },

  /** The sheet closed: the session keeps its scans and stops holding the
   * document. */
  wmsReceivingPause: async (
    documentId: string,
    sessionId: string,
  ): Promise<void> => {
    await api.post(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/pause`,
    );
  },

  wmsReceivingRelease: async (
    documentId: string,
    sessionId: string,
  ): Promise<void> => {
    await api.post(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/release`,
    );
  },

  wmsReceivingTakeOver: async (
    documentId: string,
    sessionId: string,
  ): Promise<WmsReceiveSession> => {
    const response = await api.post<WmsReceiveSession>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}/take-over`,
    );
    return response.data;
  },

  listWmsReceivingSessions: async (
    documentId: string,
  ): Promise<WmsReceiveSession[]> =>
    getEveryPage<WmsReceiveSession>(
      `/warehouse/documents/${documentId}/receiving`,
    ),

  getWmsReceivingSession: async (
    documentId: string,
    sessionId: string,
  ): Promise<WmsReceiveSession> => {
    const response = await api.get<WmsReceiveSession>(
      `/warehouse/documents/${documentId}/receiving/${sessionId}`,
    );
    return response.data;
  },
};
