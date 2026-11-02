import { prepareImageUpload } from "@/lib/imageUtils";
import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";
import { assertFileSize } from "@/utils/fileValidation";

export type EquipmentSortKey =
  "name" | "created_at" | "purchase_price" | "warranty_until" | "location";

export type EquipmentSortDir = "asc" | "desc";

/**
 * The checkout an approval request asks for — who gets the asset and until
 * when (`CheckoutApprovalAsk` on the server).
 */
export type CheckoutApprovalAsk = components["schemas"]["CheckoutApprovalAsk"];

/** Item payload extended by GET /equipment/assets. */
export type EquipmentAssetItem = components["schemas"]["EquipmentAssetItem"];

export type EquipmentAssetListResponse =
  components["schemas"]["EquipmentAssetListResponse"];

export interface EquipmentAssetListParams {
  search?: string | null;
  category_id?: string | null;
  location_id?: string | null;
  status?: string | null;
  checked_out?: boolean;
  sort?: EquipmentSortKey;
  sort_dir?: EquipmentSortDir;
  offset?: number;
  limit?: number;
}

/**
 * The list's filters as the scope of a bulk action: "everything that
 * matches", not a page of ids. Same five parameters the list takes.
 */
export type AssetFilter = components["schemas"]["AssetFilter"];

export type BulkEquipmentEntry = components["schemas"]["BulkEquipmentEntry"];

/** One row a bulk purge refused. */
export type BulkPurgeError = components["schemas"]["BulkPurgeError"];

export type BulkPurgeResponse = components["schemas"]["BulkPurgeResult"];

type BulkEquipmentCreate = components["schemas"]["BulkEquipmentCreate"];

type BulkEquipmentResponse = components["schemas"]["BulkEquipmentResponse"];

export type EquipmentAttachment = components["schemas"]["AttachmentSchema"];

type BulkEditRequest = components["schemas"]["BulkEditRequest"];

type BulkEditResult = components["schemas"]["BulkEditResult"];

interface MyAsset {
  assignment_id: string;
  item_id: string;
  item_name: string;
  item_barcode: string | null;
  category_name: string | null;
  // Stable declaration code so the row label can be translated.
  category_code?: string | null;
  checked_out_at: string;
  expected_return_at: string | null;
  checkout_notes: string | null;
  equipment_status: string | null;
  warranty_until: string | null;
  serial_number: string | null;
  image_url: string | null;
  /** The model's picture, shown when the unit has none of its own. */
  model_image_url: string | null;
  /** The holder, resolved by the backend; `holder_kind` words it. */
  holder_name?: string | null;
  holder_kind?: "person" | "location" | null;
}

interface MyAssetHistory {
  assignment_id: string;
  item_id: string;
  item_name: string;
  checked_out_at: string;
  checked_in_at: string | null;
  checkin_condition: string | null;
}

interface ApprovalStatus {
  has_workflow: boolean;
  request_id: string | null;
  status: string | null;
  /**
   * An APPROVED request that already authorised a checkout: the card shows
   * a waiting approval as approved-for-the-next-checkout and a spent one as
   * needing a new request.
   */
  consumed: boolean;
}

type AssetValuation = components["schemas"]["AssetValuation"];

/**
 * Wire shape of GET /equipment/valuation — aliased to the generated schema
 * so the two cannot drift. Decimal money arrives as strings.
 */
type FleetValuation = components["schemas"]["FleetValuation"];

export const equipmentAssetsApi = {
  // module-level asset list — server-side status / checked-out
  // filters (Core /items cannot filter by meta_data.equipment.equipment_status).
  listAssets: async (
    params: EquipmentAssetListParams = {},
  ): Promise<EquipmentAssetListResponse> => {
    const response = await api.get<EquipmentAssetListResponse>(
      "/equipment/assets",
      {
        params: {
          search: params.search || undefined,
          category_id: params.category_id || undefined,
          location_id: params.location_id || undefined,
          status: params.status || undefined,
          checked_out: params.checked_out || undefined,
          sort: params.sort || undefined,
          sort_dir: params.sort_dir || undefined,
          offset: params.offset ?? 0,
          limit: params.limit ?? 50,
        },
      },
    );
    return response.data;
  },

  bulkCreateItems: async (
    data: BulkEquipmentCreate,
  ): Promise<BulkEquipmentResponse> => {
    const response = await api.post<BulkEquipmentResponse>(
      "/equipment/items/bulk",
      data,
    );
    return response.data;
  },

  retireItem: async (itemId: string): Promise<void> => {
    await api.post(`/equipment/items/${itemId}/retire`);
  },

  archiveItem: async (itemId: string): Promise<void> => {
    await api.post(`/equipment/items/${itemId}/archive`);
  },

  bulkRetire: async (
    itemIds: string[],
  ): Promise<{
    retired: number;
    errors: { item_id: string; error: string }[];
  }> => {
    const response = await api.post("/equipment/items/bulk-retire", itemIds);
    return response.data;
  },

  bulkArchive: async (
    itemIds: string[],
  ): Promise<{
    archived: number;
    errors: { item_id: string; error: string }[];
  }> => {
    const response = await api.post("/equipment/items/bulk-archive", itemIds);
    return response.data;
  },

  retireMatching: async (
    scope: AssetFilter,
  ): Promise<{
    retired: number;
    errors: { item_id: string; error: string }[];
  }> => {
    const response = await api.post("/equipment/assets/matching/retire", scope);
    return response.data;
  },

  archiveMatching: async (
    scope: AssetFilter,
  ): Promise<{
    archived: number;
    errors: { item_id: string; error: string }[];
  }> => {
    const response = await api.post(
      "/equipment/assets/matching/archive",
      scope,
    );
    return response.data;
  },

  bulkReturn: async (payload: {
    item_ids: string[];
    checkin_condition: string;
    checkin_notes?: string;
    return_location_id?: string;
  }): Promise<{
    checked_in: number;
    errors: { item_id: string; error: string }[];
  }> => {
    const response = await api.post("/equipment/items/bulk-return", payload);
    return response.data;
  },

  bulkPurge: async (itemIds: string[]): Promise<BulkPurgeResponse> => {
    const response = await api.post("/equipment/items/bulk-purge", itemIds);
    return response.data;
  },

  bulkEdit: async (data: BulkEditRequest): Promise<BulkEditResult> => {
    const response = await api.patch<BulkEditResult>(
      "/equipment/assets/bulk",
      data,
    );
    return response.data;
  },

  listAttachments: async (itemId: string): Promise<EquipmentAttachment[]> => {
    return getEveryPage<EquipmentAttachment>(
      `/equipment/${itemId}/attachments`,
    );
  },

  uploadAttachment: async (
    itemId: string,
    file: File,
    fileType: string = "OTHER",
  ): Promise<EquipmentAttachment> => {
    const upload = await prepareImageUpload(file, { imageOnly: false });
    assertFileSize(upload);
    const formData = new FormData();
    formData.append("file", upload);
    formData.append("file_type", fileType);
    const response = await api.post<EquipmentAttachment>(
      `/equipment/${itemId}/attachments`,
      formData,
    );
    return response.data;
  },

  deleteAttachment: async (
    itemId: string,
    attachmentId: string,
  ): Promise<void> => {
    await api.delete(`/equipment/${itemId}/attachments/${attachmentId}`);
  },

  getMyAssets: async (): Promise<MyAsset[]> => {
    return getEveryPage<MyAsset>("/equipment/my-assets");
  },

  getMyAssetHistory: async (): Promise<MyAssetHistory[]> => {
    const response = await api.get<{ items: MyAssetHistory[] }>(
      "/equipment/my-assets/history",
    );
    return response.data.items;
  },

  getApprovalStatus: async (itemId: string): Promise<ApprovalStatus> => {
    const response = await api.get<ApprovalStatus>(
      `/equipment/${itemId}/approval-status`,
    );
    return response.data;
  },

  /**
   * Ask for the approval of one checkout. ``ask`` names who gets the asset
   * and until when; the approval then covers that checkout only.
   */
  requestApproval: async (
    itemId: string,
    ask?: CheckoutApprovalAsk,
  ): Promise<{ request_id: string; status: string }> => {
    const response = await api.post(
      `/equipment/${itemId}/request-approval`,
      ask,
    );
    return response.data;
  },

  getAssetValuation: async (itemId: string): Promise<AssetValuation> => {
    const response = await api.get<AssetValuation>(
      `/equipment/${itemId}/valuation`,
    );
    return response.data;
  },

  getFleetValuation: async (): Promise<FleetValuation> => {
    const response = await api.get<FleetValuation>("/equipment/valuation");
    return response.data;
  },
};
