import { prepareImageUpload } from "@/lib/imageUtils";
import i18next from "i18next";
import { ReadableError } from "@/lib/errors";
import { api, type Page } from "./client";
import {
  IMAGE_UPLOAD_MAX_BYTES,
  assertFileSize,
  validateFileSize,
} from "@/utils/fileValidation";
import type { components } from "@/types/api-generated";
import type {
  ImportProgress,
  ImportRowError,
  ItemImportOutcome,
} from "@/components/import/types";
import type {
  ArchivedItemListResponse,
  AttentionCounts,
  Item,
  ItemAggregates,
  ItemCreate,
  ItemUpdate,
  ItemBulkUpdate,
  ItemImportResponse,
  ItemListResponse,
  ItemHistory,
  LowStockProduct,
  ProductLookupResult,
} from "@/types";
type SheetAnalysis = components["schemas"]["SheetAnalysisResponse"];
type ItemImportJob = components["schemas"]["ItemImportJobResponse"];

/** How long to wait between two looks at an import running in the background. */
const IMPORT_POLL_MS = 1500;

/** Follows an import the server moved to the background until it ends.
 *
 * A long sheet is answered with a job instead of a result: its rows take
 * minutes, longer than a request is allowed to last. The job's answer, once
 * done, is the one the synchronous import would have given, so the caller
 * cannot tell the two apart. `onProgress` hears each look at the running job,
 * so the screen can show a number rather than a spinner for those minutes.
 *
 * A job that fails keeps what its batches had already committed, so the
 * refusal says how many rows that was: a half-imported sheet and one that
 * imported nothing ask for different things from the reader. */
async function followImportJob(
  jobId: string,
  onProgress?: (progress: ImportProgress) => void,
): Promise<ItemImportResponse> {
  for (;;) {
    const { data: job } = await api.get<ItemImportJob>(
      `/items/import/jobs/${jobId}`,
    );
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "failed") {
      const error = job.error ?? i18next.t("common:import.jobFailedUnknown");
      throw new ReadableError(
        job.processed > 0
          ? i18next.t("common:import.jobFailedPartly", {
              error,
              done: job.processed,
              total: job.total,
            })
          : i18next.t("common:import.jobFailedNothing", { error }),
      );
    }
    onProgress?.({ processed: job.processed, total: job.total });
    await new Promise((resolve) => setTimeout(resolve, IMPORT_POLL_MS));
  }
}

/** What an import does with a row whose Label Code is already taken. */
export type LabelMatchMode = "add" | "skip" | "overwrite";

export const itemsApi = {
  getAll: async (params?: {
    location_id?: string;
    category_id?: string;
    context_tag?: string;
    exclude_module_contexts?: boolean;
    search?: string;
    expiring_days?: number;
    only_expired?: boolean;
    only_low_stock?: boolean;
    needs_attention?: boolean;
    /** Records with nothing left join the rows — see `ItemsParams`. */
    include_empty?: boolean;
    offset?: number;
    limit?: number;
    sort_by?: "created_at" | "name" | "quantity" | "expiry_date";
    sort_order?: "asc" | "desc";
    /** Comma-separated product template ids — see `ItemsParams`. */
    template_ids?: string;
  }): Promise<ItemListResponse> => {
    const response = await api.get<ItemListResponse>("/items", { params });
    return response.data;
  },

  /** Totals over the whole filtered set — the same params as `getAll`,
   * minus pagination and sorting. */
  getAggregates: async (params?: {
    location_id?: string;
    category_id?: string;
    context_tag?: string;
    exclude_module_contexts?: boolean;
    search?: string;
    expiring_days?: number;
    only_expired?: boolean;
    only_low_stock?: boolean;
    needs_attention?: boolean;
    include_empty?: boolean;
    template_ids?: string;
  }): Promise<ItemAggregates> => {
    const response = await api.get<ItemAggregates>("/items/aggregates", {
      params,
    });
    return response.data;
  },

  /** What needs attention — expired, expiring soon, short products — from
   * the one service the statistics overview reads too. Uncapped, and
   * product-level for low stock; the dashboard heading and the statistics
   * health card both call it, so they cannot compute different answers. */
  getAttentionCounts: async (params?: {
    exclude_module_contexts?: boolean;
  }): Promise<AttentionCounts> => {
    const response = await api.get<AttentionCounts>("/items/attention-counts", {
      params,
    });
    return response.data;
  },

  /** The emptiest short products behind the overview's low-stock number, one
   * row each — the first hundred, the top of the list the card shows.
   * `exclude_module_contexts` narrows them the way the attention counts and
   * the item list are narrowed, so a heading and its rows agree. */
  getLowStockProducts: async (params?: {
    exclude_module_contexts?: boolean;
  }): Promise<LowStockProduct[]> => {
    const response = await api.get<Page<LowStockProduct>>("/stats/low-stock", {
      params: { ...params, limit: 100 },
    });
    return response.data.items;
  },

  create: async (data: ItemCreate): Promise<Item> => {
    const response = await api.post<Item>("/items", data);
    return response.data;
  },

  /** One product by id. An archived product answers only when the caller
   * names the archive in the ask — a screen whose card stays reachable
   * (Equipment, linked from assignment history) does; live lists don't. */
  getById: async (
    id: string,
    options?: { includeArchived?: boolean },
  ): Promise<Item> => {
    const response = await api.get<Item>(`/items/${id}`, {
      params: options?.includeArchived ? { include_archived: true } : undefined,
    });
    return response.data;
  },

  update: async (id: string, data: ItemUpdate): Promise<Item> => {
    const response = await api.put<Item>(`/items/${id}`, data);
    return response.data;
  },

  delete: async (
    id: string,
    reason?: string,
    notes?: string,
  ): Promise<void> => {
    await api.delete(`/items/${id}`, {
      data: reason ? { reason, notes } : undefined,
    });
  },

  updateQuantity: async (id: string, quantity: number): Promise<Item> => {
    const response = await api.patch<Item>(`/items/${id}/quantity`, {
      quantity,
    });
    return response.data;
  },

  consume: async (
    id: string,
    quantity: number = 1,
    reason: string = "USED",
    notes?: string,
  ): Promise<Item> => {
    const response = await api.patch<Item>(`/items/${id}/consume`, {
      quantity,
      reason,
      notes,
    });
    return response.data;
  },

  /** Opens a package, or says how much of an open one is left. `left` absent
   * only marks the package as opened; 0 says it is finished. */
  openPartly: async (
    id: string,
    body: { left?: number; left_uom_id?: string; use_by?: string },
  ): Promise<Item> => {
    const response = await api.post<Item>(`/items/${id}/use-partially`, body);
    return response.data;
  },

  /** Edits the use-by of an opened package; `null` clears it. */
  setUseBy: async (id: string, useBy: string | null): Promise<Item> => {
    const response = await api.put<Item>(`/items/${id}/use-by`, {
      use_by: useBy,
    });
    return response.data;
  },

  discard: async (
    id: string,
    quantity: number = 1,
    reason: string = "DISPOSED",
    notes?: string,
  ): Promise<Item> => {
    const response = await api.patch<Item>(`/items/${id}/discard`, {
      quantity,
      reason,
      notes,
    });
    return response.data;
  },

  move: async (
    id: string,
    to_location_id: string,
    notes?: string,
  ): Promise<Item> => {
    const response = await api.patch<Item>(`/items/${id}/move`, {
      to_location_id,
      notes,
    });
    return response.data;
  },

  getHistory: async (limit: number = 20): Promise<ItemHistory[]> => {
    const response = await api.get<{
      items: ItemHistory[];
      next_cursor: string | null;
      has_more: boolean;
    }>("/items/history", {
      params: { limit },
    });
    return response.data.items;
  },

  getItemHistory: async (itemId: string, limit = 50, cursor?: string) => {
    const response = await api.get<{
      items: ItemHistory[];
      next_cursor: string | null;
      has_more: boolean;
    }>(`/items/${itemId}/history`, {
      params: { limit, cursor },
    });
    return response.data;
  },

  search: async (query: string, limit = 5): Promise<Item[]> => {
    // No dedicated /items/search route on the backend; the list endpoint
    // supports a `search` param (name/barcode/template match).
    // include_empty: a record the reader consumed to zero sits outside the
    // internal default — the one place a reader searches by name should be
    // the place that still finds it.
    const response = await api.get<ItemListResponse>("/items", {
      params: { search: query, limit, include_empty: true },
    });
    return response.data.items;
  },

  bulkUpdate: async (data: ItemBulkUpdate): Promise<{ updated: number }> => {
    const response = await api.patch<{ updated: number }>("/items/bulk", data);
    return response.data;
  },

  analyzeImport: async (file: File): Promise<SheetAnalysis> => {
    if (!validateFileSize(file))
      return {
        headers: [],
        preview_rows: [],
        total_rows: 0,
        filled_counts: {},
      };
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<SheetAnalysis>(
      "/items/import/analyze",
      formData,
    );
    return response.data;
  },

  /** The two creation flags travel separately: the backend gates founding
   * locations on `locations:write` and founding categories on
   * `categories:write`, so one switch wired to both left an account holding
   * only one of the keys no setting under which its permission worked.
   * `onLabelMatch` decides what a row whose Label Code names a product
   * already here does: add it anyway ("add", the default), leave the
   * product alone ("skip") or write the row onto it ("overwrite").
   * `onProgress` is told how far a background import has got. */
  importItems: async (
    file: File,
    mapping: unknown,
    createLocations: boolean = true,
    createCategories: boolean = true,
    onLabelMatch: LabelMatchMode = "add",
    onProgress?: (progress: ImportProgress) => void,
  ): Promise<ItemImportOutcome> => {
    assertFileSize(file);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mapping_json", JSON.stringify(mapping));
    formData.append("create_missing_locations", String(createLocations));
    formData.append("create_missing_categories", String(createCategories));
    formData.append("on_label_match", onLabelMatch);
    const response = await api.post<ItemImportResponse | ItemImportJob>(
      "/items/import",
      formData,
    );
    const outcome =
      response.status === 202
        ? await followImportJob((response.data as ItemImportJob).id, onProgress)
        : (response.data as ItemImportResponse);
    // The contract types `errors` as open dicts; the server builds
    // { row, error } objects and the progress step renders exactly those
    // fields — the one narrowing, where the response arrives.
    return outcome as ItemImportResponse & {
      errors: ImportRowError[];
    };
  },

  /** The rows the list shows for the same params — pass `getAggregates`'s
   * params to export what is on screen; `location_usage: "any"` is the
   * backup export asking for every location. */
  exportXlsx: async (params?: {
    location_id?: string;
    category_id?: string;
    context_tag?: string;
    exclude_module_contexts?: boolean;
    location_usage?: "any";
    search?: string;
    expiring_days?: number;
    only_expired?: boolean;
    only_low_stock?: boolean;
    needs_attention?: boolean;
    template_ids?: string;
  }): Promise<Blob> => {
    const response = await api.get("/items/export/xlsx", {
      params,
      responseType: "blob",
    });
    return response.data;
  },

  lookup: async (barcode: string): Promise<ProductLookupResult | null> => {
    try {
      const response = await api.get<ProductLookupResult>(
        `/items/lookup/${barcode}`,
      );
      return response.data;
    } catch {
      return null;
    }
  },

  uploadImage: async (
    id: string,
    file: File,
  ): Promise<{ image_url: string }> => {
    const image = await prepareImageUpload(file);
    assertFileSize(image, IMAGE_UPLOAD_MAX_BYTES);
    const form = new FormData();
    form.append("image", image);
    const response = await api.post<{ image_url: string }>(
      `/items/${id}/image`,
      form,
    );
    return response.data;
  },

  deleteImage: async (id: string): Promise<void> => {
    await api.delete(`/items/${id}/image`);
  },

  getArchived: async (params?: {
    context_tag?: string;
    exclude_module_contexts?: boolean;
    // Everything one module counts as its own — the category it claims plus
    // the records saved without one. A module's Archive asks this, not
    // context_tag, which alone loses exactly those records.
    module_scope?: string;
    offset?: number;
    limit?: number;
    search?: string;
  }): Promise<ArchivedItemListResponse> => {
    const response = await api.get<ArchivedItemListResponse>(
      "/items/archived",
      {
        params,
      },
    );
    return response.data;
  },

  restore: async (id: string): Promise<Item> => {
    const response = await api.post<Item>(`/items/${id}/restore`);
    return response.data;
  },

  purge: async (id: string, reason?: string): Promise<void> => {
    const params = reason ? { reason } : undefined;
    await api.delete(`/items/${id}/purge`, { params });
  },
};
