import { api } from "./client";
import { assertFileSize, validateFileSize } from "@/utils/fileValidation";
import type { components } from "@/types/api-generated";
import type {
  ImportRowError,
  PartnerImportOutcome,
} from "@/components/import/types";
import type {
  Partner,
  PartnerCreate,
  PartnerImportResponse,
  PartnerUpdate,
  PartnerListResponse,
} from "@/types";
type SheetAnalysis = components["schemas"]["SheetAnalysisResponse"];

export interface PartnersListParams {
  search?: string;
  type?: string;
  types?: string[];
  is_active?: boolean;
  limit?: number;
  offset?: number;
  sort_by?: "name" | "created_at" | "type";
  sort_order?: "asc" | "desc";
}

export const partnersApi = {
  list: async (params?: PartnersListParams): Promise<PartnerListResponse> => {
    const response = await api.get<PartnerListResponse>("/partners", {
      params,
      // `types` is a repeatable query parameter (?types=A&types=B); axios
      // would otherwise serialize arrays as types[]=A&types[]=B.
      paramsSerializer: {
        indexes: null,
      },
    });
    return response.data;
  },

  getById: async (id: string): Promise<Partner> => {
    const response = await api.get<Partner>(`/partners/${id}`);
    return response.data;
  },

  create: async (data: PartnerCreate): Promise<Partner> => {
    const response = await api.post<Partner>("/partners", data);
    return response.data;
  },

  update: async (id: string, data: PartnerUpdate): Promise<Partner> => {
    const response = await api.put<Partner>(`/partners/${id}`, data);
    return response.data;
  },

  deactivate: async (id: string): Promise<Partner> => {
    const response = await api.patch<Partner>(`/partners/${id}/deactivate`);
    return response.data;
  },

  activate: async (id: string): Promise<Partner> => {
    const response = await api.patch<Partner>(`/partners/${id}/activate`);
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
      "/partners/import/analyze",
      formData,
    );
    return response.data;
  },

  importPartners: async (
    file: File,
    mapping: unknown,
    defaultType: string,
  ): Promise<PartnerImportOutcome> => {
    assertFileSize(file);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mapping_json", JSON.stringify(mapping));
    formData.append("default_type", defaultType);
    const response = await api.post<PartnerImportResponse>(
      "/partners/import",
      formData,
    );
    // The contract types `errors` as open dicts; the server builds
    // { row, error } objects and the progress step renders exactly those
    // fields — the one narrowing, where the response arrives.
    return response.data as PartnerImportResponse & {
      errors: ImportRowError[];
    };
  },
};
