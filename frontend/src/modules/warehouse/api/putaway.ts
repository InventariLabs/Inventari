import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";

/**
 * Putaway rule — automated receiving location routing.
 *
 * Backend: app/modules/warehouse/_router_putaway.py (mounted under
 * /api/v1/warehouse/putaway-rules). Match order on the server is
 * product_template > category > context_tag > location_type_code, priority ASC.
 */
export type PutawayRule = components["schemas"]["PutawayRuleOut"];

/** Where one not-yet-saved receipt line will land, and who decided. */
export type PutawayPreviewLine = components["schemas"]["PutawayPreviewLineOut"];

export type PutawayPreviewLineInput =
  components["schemas"]["PutawayPreviewLineIn"];

export type PutawayRuleCreate = components["schemas"]["PutawayRuleCreate"];

export type PutawayRuleUpdate = components["schemas"]["PutawayRuleUpdate"];

export const putawayApi = {
  /**
   * The shelf each line will land on, before the receipt exists.
   *
   * Answered by the same planner the posting runs, so the shelf the form
   * shows and the shelf the goods reach cannot disagree. Nothing is stored:
   * the plan is computed from the rules as they stand now.
   */
  previewReceiptPlan: async (
    targetLocationId: string,
    lines: PutawayPreviewLineInput[],
  ): Promise<PutawayPreviewLine[]> => {
    const response = await api.post<PutawayPreviewLine[]>(
      "/warehouse/putaway/preview",
      { target_location_id: targetLocationId, lines },
    );
    return response.data;
  },

  list: async (): Promise<PutawayRule[]> =>
    getEveryPage<PutawayRule>("/warehouse/putaway-rules"),

  getById: async (id: string): Promise<PutawayRule> => {
    const response = await api.get<PutawayRule>(
      `/warehouse/putaway-rules/${id}`,
    );
    return response.data;
  },

  create: async (data: PutawayRuleCreate): Promise<PutawayRule> => {
    const response = await api.post<PutawayRule>(
      "/warehouse/putaway-rules",
      data,
    );
    return response.data;
  },

  update: async (id: string, data: PutawayRuleUpdate): Promise<PutawayRule> => {
    const response = await api.put<PutawayRule>(
      `/warehouse/putaway-rules/${id}`,
      data,
    );
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/warehouse/putaway-rules/${id}`);
  },
};

export interface PutawayCapacityEntry {
  id: string;
  organization_id: string;
  location_id: string;
  product_template_id: string;
  /** In the product's stock unit; the wire carries a Decimal as text. */
  max_quantity: string;
  location_name?: string | null;
  product_template_name?: string | null;
  /** The unit the limit is counted in; null when the template has none. */
  product_unit_symbol?: string | null;
  /** The replenishment side of the pair, read at response time. */
  reorder_max_quantity?: string | null;
  reorder_over_capacity?: boolean;
}

export type PutawayCapacityCreate =
  components["schemas"]["PutawayCapacityCreate"];

export type PutawayLocationSetting =
  components["schemas"]["PutawayLocationSettingOut"];

/** One warehouse's occupancy: every shelf under it, plus the signals. */
export type PutawayOccupancy = components["schemas"]["PutawayOccupancyOut"];

/** Every warehouse and shelf of the organization, rolled up on the server. */
export type PutawayOccupancyOverview =
  components["schemas"]["PutawayOccupancyOverview"];

export const putawayCapacityApi = {
  /** The occupancy screen's one read: the whole floor, in walk order. */
  occupancyOverview: async (): Promise<PutawayOccupancyOverview> => {
    const response = await api.get<PutawayOccupancyOverview>(
      "/warehouse/putaway/occupancy",
    );
    return response.data;
  },

  list: async (params?: {
    location_id?: string;
    product_template_id?: string;
  }): Promise<PutawayCapacityEntry[]> =>
    getEveryPage<PutawayCapacityEntry>("/warehouse/putaway/capacity", params),

  create: async (
    data: PutawayCapacityCreate,
  ): Promise<PutawayCapacityEntry> => {
    const response = await api.post<PutawayCapacityEntry>(
      "/warehouse/putaway/capacity",
      data,
    );
    return response.data;
  },

  update: async (
    entryId: string,
    maxQuantity: string,
  ): Promise<PutawayCapacityEntry> => {
    const response = await api.put<PutawayCapacityEntry>(
      `/warehouse/putaway/capacity/${entryId}`,
      { max_quantity: maxQuantity },
    );
    return response.data;
  },

  remove: async (entryId: string): Promise<void> => {
    await api.delete(`/warehouse/putaway/capacity/${entryId}`);
  },

  /**
   * Every shelf of the organization whose product mix was chosen.
   *
   * A shelf nobody restricted has no row — mixed is the default — so this
   * tells a chosen "different products" apart from one never touched.
   */
  listSettings: async (params?: {
    location_id?: string;
  }): Promise<PutawayLocationSetting[]> =>
    getEveryPage<PutawayLocationSetting>(
      "/warehouse/putaway/capacity-settings",
      params,
    ),

  getSetting: async (locationId: string): Promise<PutawayLocationSetting> => {
    const response = await api.get<PutawayLocationSetting>(
      `/warehouse/putaway/capacity-settings/${locationId}`,
    );
    return response.data;
  },

  putSetting: async (
    locationId: string,
    singleProduct: boolean,
  ): Promise<PutawayLocationSetting> => {
    const response = await api.put<PutawayLocationSetting>(
      `/warehouse/putaway/capacity-settings/${locationId}`,
      { single_product: singleProduct },
    );
    return response.data;
  },
};

/** How one warehouse receives; a warehouse missing from the list receives in one step. */
export type WarehouseReceiving = components["schemas"]["WarehouseReceivingOut"];

export const receivingModesApi = {
  list: async (): Promise<WarehouseReceiving[]> =>
    getEveryPage<WarehouseReceiving>("/warehouse/putaway/receiving-modes"),

  /** Only the choices given are changed; the others stay as they were. */
  set: async (vars: {
    warehouseId: string;
    twoStep?: boolean;
    freePlacement?: boolean;
  }): Promise<WarehouseReceiving> => {
    const response = await api.put<WarehouseReceiving>(
      `/warehouse/putaway/receiving-modes/${vars.warehouseId}`,
      {
        ...(vars.twoStep === undefined ? {} : { two_step: vars.twoStep }),
        ...(vars.freePlacement === undefined
          ? {}
          : { free_placement: vars.freePlacement }),
      },
    );
    return response.data;
  },
};

/**
 * What a put-away says about the location the goods were put on: the offer to
 * make it the product's home, or why it cannot be one.
 */
export type HomeShelfOffer = components["schemas"]["HomeShelfOffer"];

/** A product whose put-away does not ask for a home location. */
export type HomeShelfSilenced = components["schemas"]["HomeShelfSilencedOut"];

export const homeShelfApi = {
  /** Make the location the product's home: the head of its own rule. */
  set: async (vars: {
    productTemplateId: string;
    locationId: string;
  }): Promise<void> => {
    await api.put("/warehouse/putaway/home-shelf", {
      product_template_id: vars.productTemplateId,
      location_id: vars.locationId,
    });
  },

  listSilenced: async (): Promise<HomeShelfSilenced[]> =>
    getEveryPage<HomeShelfSilenced>("/warehouse/putaway/home-shelf/silenced"),

  /** Stop asking about this product's home location. */
  silence: async (productTemplateId: string): Promise<void> => {
    await api.put(
      `/warehouse/putaway/home-shelf/silenced/${productTemplateId}`,
    );
  },

  /** Ask about this product's home location again. */
  unsilence: async (productTemplateId: string): Promise<void> => {
    await api.delete(
      `/warehouse/putaway/home-shelf/silenced/${productTemplateId}`,
    );
  },
};

/**
 * The shared fill read: one location's cell (and every location below it),
 * with each product's pair and the whole shelf's state.
 *
 * Every screen that draws a fill asks for it here — the Locations table and
 * the rule editor's target list — so no two screens can show different
 * numbers for the same shelf.
 */
export const putawayOccupancyApi = {
  get: async (locationId: string): Promise<PutawayOccupancy> => {
    const response = await api.get<PutawayOccupancy>(
      `/warehouse/putaway/occupancy/${locationId}`,
    );
    return response.data;
  },
};
