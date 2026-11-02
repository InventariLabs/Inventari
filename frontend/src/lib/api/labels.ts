import { api } from "./client";
import type {
  LabelPool,
  LabelPoolListResponse,
  LabelScanResponse,
  LabelScanView,
  LabelAssignRequest,
  Item,
} from "@/types";

export const labelsApi = {
  generatePool: async (data: {
    count: number;
    label_type?: string;
    description?: string;
    target_location_id?: string;
    prefix?: string;
    context_tag?: string;
  }): Promise<LabelPool[]> => {
    const response = await api.post<LabelPool[]>("/labels/pool/generate", data);
    return response.data;
  },

  createFromCodes: async (data: {
    codes: { short_code: string; description?: string }[];
    label_type?: string;
    context_tag?: string;
  }): Promise<LabelPool[]> => {
    const response = await api.post<LabelPool[]>(
      "/labels/pool/from-codes",
      data,
    );
    return response.data;
  },

  getPool: async (params?: {
    unassigned_only?: boolean;
    label_type?: string;
    status?: string;
    offset?: number;
    limit?: number;
  }): Promise<LabelPoolListResponse> => {
    const response = await api.get<LabelPoolListResponse>("/labels/pool", {
      params,
    });
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/labels/pool/${id}`);
  },

  getStats: async (): Promise<{
    total: number;
    assigned: number;
    unassigned: number;
  }> => {
    const response = await api.get("/labels/pool/stats");
    return response.data;
  },

  /**
   * Scanning a code answers `LabelScanResponse`, whose payload fields the
   * backend declares `dict`; screens read the shapes the server actually
   * builds into them, so the response crosses into the app once, here, as
   * the view that states them (`LabelScanView`).
   */
  scan: async (shortCode: string): Promise<LabelScanView> => {
    const encodedCode = encodeURIComponent(shortCode);
    const response = await api.get<LabelScanResponse>(
      `/labels/scan/${encodedCode}`,
    );
    return response.data as LabelScanView;
  },

  assign: async (
    shortCode: string,
    data: LabelAssignRequest,
  ): Promise<Item> => {
    const response = await api.post<Item>(
      `/labels/scan/${shortCode}/assign`,
      data,
    );
    return response.data;
  },

  unassign: async (shortCode: string): Promise<void> => {
    await api.post(`/labels/pool/${shortCode}/unassign`);
  },

  assignToExistingItem: async (
    shortCode: string,
    itemId: string,
  ): Promise<LabelPool> => {
    const response = await api.post<LabelPool>(
      `/labels/pool/${shortCode}/assign-item`,
      null,
      { params: { item_id: itemId } },
    );
    return response.data;
  },

  exportPng: async (params: {
    count?: number;
    labelIds?: string[];
    shortCodes?: string[];
    width?: number;
    height?: number;
    baseUrl?: string;
    description?: string;
    qrOnly?: boolean;
    /** Print the short code beside the QR (off by default). */
    showCode?: boolean;
    /** False for the preview: showing the file must not spend the pool. */
    markPrinted?: boolean;
  }): Promise<Blob> => {
    const {
      count = 50,
      labelIds,
      shortCodes,
      width = 50,
      height = 24,
      baseUrl,
      description,
      qrOnly,
      showCode,
      markPrinted,
    } = params;
    const response = await api.get("/labels/pool/export/png", {
      params: {
        count,
        label_ids: labelIds,
        short_codes: shortCodes,
        width,
        height,
        base_url: baseUrl,
        description,
        qr_only: qrOnly,
        show_code: showCode,
        mark_printed: markPrinted,
      },
      paramsSerializer: {
        indexes: null,
      },
      responseType: "blob",
    });
    return response.data;
  },
};
