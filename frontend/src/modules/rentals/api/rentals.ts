import { api, getEveryPage, type components } from "@/module-sdk";

export type Booking = components["schemas"]["BookingSchema"];
export type BookingCreate = components["schemas"]["BookingCreate"];
export type BookingLineIn = components["schemas"]["BookingLineIn"];
export type BookingCheck = components["schemas"]["BookingCheckResponse"];
export type BookingCheckRequest = components["schemas"]["BookingCheckRequest"];
export type BookingListPage =
  components["schemas"]["PaginatedResponse_BookingListRow_"];
export type Calendar = components["schemas"]["CalendarResponse"];
export type CalendarGroup = components["schemas"]["CalendarGroup"];
export type CalendarBar = components["schemas"]["CalendarBar"];
export type Today = components["schemas"]["TodayResponse"];
export type TodayItem = components["schemas"]["TodayItem"];
export type Block = components["schemas"]["BlockSchema"];
export type BlockCreate = components["schemas"]["BlockCreate"];
export type BlockPage = components["schemas"]["PaginatedResponse_BlockSchema_"];
export type BufferRule = components["schemas"]["BufferRuleSchema"];
export type BufferRuleIn = components["schemas"]["BufferRuleIn"];
export type AssetOption = components["schemas"]["AssetOption"];
export type ModelOption = components["schemas"]["ModelOption"];
export type CategoryOption = components["schemas"]["CategoryOption"];
export type ReturnRequest = components["schemas"]["ReturnRequest"];
export type PickupRequest = components["schemas"]["PickupRequest"];
export type BookingStatus = Booking["status"];
export type LineCheck = components["schemas"]["LineCheck"];
export type UnitSchema = components["schemas"]["UnitSchema"];
export type ConflictDetail = components["schemas"]["ConflictDetail"];
export type Kit = components["schemas"]["KitSchema"];
export type KitListRow = components["schemas"]["KitListRow"];
export type KitCreate = components["schemas"]["KitCreate"];
export type KitMemberIn = components["schemas"]["KitMemberIn"];

export interface BookingListParams {
  status?: string;
  search?: string;
  partner_id?: string;
  item_id?: string;
  limit?: number;
  offset?: number;
}

export interface BlockListParams {
  item_id?: string;
  active_only?: boolean;
  limit?: number;
  offset?: number;
}

/** A person a booking can be made for: a partner or a member of the org. */
export interface BorrowerOption {
  id: string;
  name: string;
  email?: string | null;
}

export const rentalsApi = {
  today: async (): Promise<Today> => {
    const response = await api.get<Today>("/rentals/today");
    return response.data;
  },

  calendar: async (params: {
    starts_at: string;
    ends_at: string;
    model?: string;
    category_id?: string;
  }): Promise<Calendar> => {
    const response = await api.get<Calendar>("/rentals/calendar", { params });
    return response.data;
  },

  bookings: async (params?: BookingListParams): Promise<BookingListPage> => {
    const response = await api.get<BookingListPage>("/rentals/bookings", {
      params,
    });
    return response.data;
  },

  pickList: async (id: string, lang: string): Promise<Blob> => {
    const response = await api.get<Blob>(`/rentals/bookings/${id}/pick-list`, {
      params: { lang },
      responseType: "blob",
    });
    return response.data;
  },

  handoverSheet: async (id: string, lang: string): Promise<Blob> => {
    const response = await api.get<Blob>(
      `/rentals/bookings/${id}/handover-sheet`,
      { params: { lang }, responseType: "blob" },
    );
    return response.data;
  },

  kits: async (): Promise<KitListRow[]> => {
    const response = await api.get<KitListRow[]>("/rentals/kits");
    return response.data;
  },

  kit: async (id: string): Promise<Kit> => {
    const response = await api.get<Kit>(`/rentals/kits/${id}`);
    return response.data;
  },

  createKit: async (data: KitCreate): Promise<Kit> => {
    const response = await api.post<Kit>("/rentals/kits", data);
    return response.data;
  },

  updateKit: async (id: string, data: KitCreate): Promise<Kit> => {
    const response = await api.put<Kit>(`/rentals/kits/${id}`, data);
    return response.data;
  },

  deleteKit: async (id: string): Promise<void> => {
    await api.delete(`/rentals/kits/${id}`);
  },

  booking: async (id: string): Promise<Booking> => {
    const response = await api.get<Booking>(`/rentals/bookings/${id}`);
    return response.data;
  },

  createBooking: async (data: BookingCreate): Promise<Booking> => {
    const response = await api.post<Booking>("/rentals/bookings", data);
    return response.data;
  },

  check: async (data: BookingCheckRequest): Promise<BookingCheck> => {
    const response = await api.post<BookingCheck>(
      "/rentals/bookings/check",
      data,
      { readOnly: true },
    );
    return response.data;
  },

  cancel: async (id: string): Promise<Booking> => {
    const response = await api.post<Booking>(`/rentals/bookings/${id}/cancel`);
    return response.data;
  },

  pickup: async (id: string, data: PickupRequest): Promise<Booking> => {
    const response = await api.post<Booking>(
      `/rentals/bookings/${id}/pickup`,
      data,
    );
    return response.data;
  },

  returnUnits: async (id: string, data: ReturnRequest): Promise<Booking> => {
    const response = await api.post<Booking>(
      `/rentals/bookings/${id}/return`,
      data,
    );
    return response.data;
  },

  extend: async (id: string, ends_at: string): Promise<Booking> => {
    const response = await api.post<Booking>(`/rentals/bookings/${id}/extend`, {
      ends_at,
    });
    return response.data;
  },

  blocks: async (params?: BlockListParams): Promise<BlockPage> => {
    const response = await api.get<BlockPage>("/rentals/blocks", { params });
    return response.data;
  },

  createBlock: async (data: BlockCreate): Promise<Block> => {
    const response = await api.post<Block>("/rentals/blocks", data);
    return response.data;
  },

  updateBlock: async (id: string, data: BlockCreate): Promise<Block> => {
    const response = await api.patch<Block>(`/rentals/blocks/${id}`, data);
    return response.data;
  },

  deleteBlock: async (id: string): Promise<void> => {
    await api.delete(`/rentals/blocks/${id}`);
  },

  bufferRules: async (): Promise<BufferRule[]> => {
    const response = await api.get<BufferRule[]>("/rentals/buffer-rules");
    return response.data;
  },

  setBufferRule: async (data: BufferRuleIn): Promise<BufferRule> => {
    const response = await api.put<BufferRule>("/rentals/buffer-rules", data);
    return response.data;
  },

  deleteBufferRule: async (id: string): Promise<void> => {
    await api.delete(`/rentals/buffer-rules/${id}`);
  },

  assets: async (params?: {
    search?: string;
    category_id?: string;
  }): Promise<AssetOption[]> => {
    const response = await api.get<AssetOption[]>("/rentals/assets", {
      params,
    });
    return response.data;
  },

  models: async (): Promise<ModelOption[]> => {
    const response = await api.get<ModelOption[]>("/rentals/models");
    return response.data;
  },

  categories: async (): Promise<CategoryOption[]> => {
    const response = await api.get<CategoryOption[]>("/rentals/categories");
    return response.data;
  },

  partners: async (): Promise<BorrowerOption[]> => {
    const rows = await getEveryPage<{
      id: string;
      name: string;
      email?: string | null;
    }>("/partners", { is_active: true });
    return rows.map((row) => ({
      id: row.id,
      name: row.name,
      email: row.email ?? null,
    }));
  },

  members: async (): Promise<BorrowerOption[]> => {
    const rows = await getEveryPage<{
      id: string;
      full_name?: string | null;
      email: string;
    }>("/users/org-members");
    return rows.map((row) => ({
      id: row.id,
      name: row.full_name || row.email,
      email: row.email,
    }));
  },
};
