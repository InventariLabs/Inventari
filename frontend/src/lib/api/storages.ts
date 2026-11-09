import { api, getEveryPage, type Page } from "./client";
import type { components } from "@/types/api-generated";
import type {
  ArchivedStorageLocation,
  StorageLocation,
  StorageLocationSummary,
  StorageLocationBreadcrumb,
  StorageLocationNode,
  StorageType,
  FieldDefinition,
  Item,
} from "@/types";

export type StorageReorgOperation =
  components["schemas"]["StorageReorgOperation"];

export type StorageReorgResponse =
  components["schemas"]["StorageReorgResponse"];

export type StorageMoveScope = components["schemas"]["StorageMoveScope"];

export type StorageLocationUpdate =
  components["schemas"]["StorageLocationUpdate"];

/** How a warehouse makes its location codes, and the stickers to reprint. */
export type StorageCodes = components["schemas"]["StorageCodes"];

export type StorageNumberResponse =
  components["schemas"]["StorageNumberResponse"];

/** What a page of locations may be asked for. Every key is the endpoint's own. */
export interface StoragePageParams {
  context_tag?: string;
  exclude_module_contexts?: boolean;
  module_scope?: string;
  usage?: string;
  include_archived?: boolean;
  /** Text the name, code or path contains. */
  q?: string;
  /** Only these places — how a screen names where its rows stand. */
  ids?: string[];
  /** Only the direct children of this place. */
  parent_id?: string;
  /** Only the places below this one, at any depth. */
  under?: string;
  /** Only places with no parent. */
  top_level?: boolean;
  /** Only places that set product fields of their own. */
  with_fields?: boolean;
  /** Only places of these location types. */
  type_ids?: string[];
  /** False leaves every record count at zero and skips the aggregate. */
  counts?: boolean;
  limit?: number;
  offset?: number;
}

export const storagesApi = {
  /**
   * One page of locations, as the endpoint answers it. A screen shows the
   * places it needs: it searches, names a set of ids or opens one branch, and
   * leaves the catalogue where it is. `getAll` below reads every page and is
   * for the lists that stay small (one module's own places).
   */
  getPage: async (
    params: StoragePageParams,
  ): Promise<Page<StorageLocationSummary>> => {
    const { data } = await api.get<Page<StorageLocationSummary>>("/locations", {
      params,
      // axios writes an array as `ids[]=…`; the endpoint reads repeated `ids=…`.
      paramsSerializer: { indexes: null },
    });
    return data;
  },

  getAll: async (params?: {
    context_tag?: string;
    exclude_module_contexts?: boolean;
    module_scope?: string;
    usage?: string;
    include_archived?: boolean;
  }): Promise<StorageLocationSummary[]> => {
    // The route answers with pages of `StorageLocationSummary`
    // (backend/app/api/storages/__init__.py). Declaring the fuller
    // `StorageLocation` here promised every caller five fields the endpoint
    // never sends — `description`, `location_details`, `location_type_id`,
    // `created_at`, `organization_id` — and one screen was reading two of them.
    return getEveryPage<StorageLocationSummary>("/locations", params);
  },

  create: async (data: Partial<StorageLocation>): Promise<StorageLocation> => {
    const response = await api.post<StorageLocation>("/locations", data);
    return response.data;
  },

  /** `dryRun` validates the batch and answers what each move would carry. */
  reorg: async (
    operations: StorageReorgOperation[],
    { dryRun = false }: { dryRun?: boolean } = {},
  ): Promise<StorageReorgResponse> => {
    const response = await api.post<StorageReorgResponse>("/locations/reorg", {
      operations,
      ...(dryRun ? { dry_run: true } : {}),
    });
    return response.data;
  },

  getById: async (id: string): Promise<StorageLocation> => {
    const response = await api.get<StorageLocation>(`/locations/${id}`);
    return response.data;
  },

  update: async (
    id: string,
    data: StorageLocationUpdate,
  ): Promise<StorageLocation> => {
    const response = await api.put<StorageLocation>(`/locations/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/locations/${id}`);
  },

  archive: async (
    id: string,
    moveItemsTo?: string,
  ): Promise<StorageLocation> => {
    const response = await api.post<StorageLocation>(
      `/locations/${id}/archive`,
      {
        ...(moveItemsTo ? { move_items_to: moveItemsTo } : {}),
      },
    );
    return response.data;
  },

  unarchive: async (id: string): Promise<StorageLocation> => {
    const response = await api.post<StorageLocation>(
      `/locations/${id}/unarchive`,
    );
    return response.data;
  },

  listArchived: async (options?: {
    excludeModuleContexts?: boolean;
  }): Promise<ArchivedStorageLocation[]> => {
    return getEveryPage<ArchivedStorageLocation>(
      "/locations/archived",
      options?.excludeModuleContexts
        ? { exclude_module_contexts: true }
        : undefined,
    );
  },

  printLabel: async (
    id: string,
    base_url?: string,
    showDescription?: boolean,
  ): Promise<Blob> => {
    const response = await api.get(`/locations/${id}/print`, {
      params: {
        ...(base_url ? { base_url } : {}),
        ...(showDescription !== undefined
          ? { show_description: showDescription }
          : {}),
      },
      responseType: "blob",
    });
    return response.data;
  },

  generateCode: async (id: string): Promise<StorageLocation> => {
    const response = await api.post<StorageLocation>(
      `/locations/${id}/generate-code`,
    );
    return response.data;
  },

  /** The code template of the warehouse holding `id`, and what waits to be
   *  relabelled there. */
  codes: async (id: string): Promise<StorageCodes> => {
    const response = await api.get<StorageCodes>(`/locations/${id}/codes`);
    return response.data;
  },

  /** A warehouse's own template; null follows the profile again. Rewrites
   *  no code. */
  setCodeTemplate: async (
    id: string,
    template: string | null,
  ): Promise<StorageCodes> => {
    const response = await api.put<StorageCodes>(
      `/locations/${id}/code-template`,
      { template },
    );
    return response.data;
  },

  /** Number a warehouse or a branch by its template; `renumber` numbers
   *  every family afresh. Old codes keep scanning. */
  number: async (
    id: string,
    renumber: boolean,
  ): Promise<StorageNumberResponse> => {
    const response = await api.post<StorageNumberResponse>(
      `/locations/${id}/number`,
      { renumber },
    );
    return response.data;
  },

  /** The new stickers of these locations are on the shelves. */
  markReprinted: async (locationIds: string[]): Promise<void> => {
    await api.post("/locations/reprinted", { location_ids: locationIds });
  },

  getSummary: async (id: string): Promise<StorageLocationSummary> => {
    const response = await api.get<StorageLocationSummary>(
      `/locations/${id}/summary`,
    );
    return response.data;
  },

  getItems: async (
    id: string,
    {
      includeInside = false,
      excludeModuleContexts = false,
    }: { includeInside?: boolean; excludeModuleContexts?: boolean } = {},
  ): Promise<Item[]> => {
    const params: Record<string, boolean> = {};
    if (includeInside) params.include_inside = true;
    if (excludeModuleContexts) params.exclude_module_contexts = true;
    return getEveryPage<Item>(
      `/locations/${id}/items`,
      Object.keys(params).length > 0 ? params : undefined,
    );
  },

  getTree: async (
    usage?: string,
    options?: {
      excludeModuleContexts?: boolean;
      /** The levels below this place instead of from the roots. */
      parentId?: string;
      /** How many levels to answer; the last carries `children_count`. */
      depth?: number;
      /** False leaves the record counts at zero and skips the aggregate. */
      counts?: boolean;
    },
  ): Promise<StorageLocationNode[]> => {
    const params: Record<string, string | number | boolean> = {};
    if (usage) params.usage = usage;
    if (options?.excludeModuleContexts) params.exclude_module_contexts = true;
    if (options?.parentId) params.parent_id = options.parentId;
    if (options?.depth) params.depth = options.depth;
    if (options?.counts === false) params.counts = false;
    const response = await api.get<StorageLocationNode[]>("/locations/tree", {
      params: Object.keys(params).length > 0 ? params : undefined,
    });
    return response.data;
  },

  getBreadcrumb: async (id: string): Promise<StorageLocationBreadcrumb[]> => {
    const response = await api.get<StorageLocationBreadcrumb[]>(
      `/locations/${id}/breadcrumb`,
    );
    return response.data;
  },

  getStorageTypes: async (): Promise<StorageType[]> => {
    return getEveryPage<StorageType>("/location-types");
  },

  createHierarchy: async (data: {
    /**
     * The location the chain hangs under. Omitted: the chain hangs under
     * nothing, and its first named step becomes a root (ADR-018).
     */
    parent_id?: string;
    /**
     * The chain, walking downwards. A step with an `id` is that location;
     * a step with a `name` is resolved among the previous step's children
     * and created when there is none. Every field below describes the last
     * step, so finishing higher up is a shorter chain (ADR-018).
     */
    steps: { id?: string; name?: string }[];
    description?: string;
    short_code?: string;
    location_type_id?: string;
    context_schema?: string[];
    field_definitions?: FieldDefinition[];
    context_tag?: string;
    location_type?: {
      name: string;
      type_code?: string;
      icon: string;
      behavior_mode: string;
      context_schema: string[];
      field_definitions: FieldDefinition[];
    };
  }): Promise<StorageLocation> => {
    const response = await api.post<StorageLocation>(
      "/locations/hierarchy",
      data,
    );
    return response.data;
  },
};
