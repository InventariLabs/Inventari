import { api, getEveryPage } from "./client";
import type { ModuleInfo } from "@/types";
import type { components } from "@/types/api-generated";

/** Generated schema (GET /modules/focus) — the contract lives in api-generated.ts. */
export type FocusModeResponse = components["schemas"]["FocusModeResponse"];
export type FocusModeDiff = components["schemas"]["FocusModeDiff"];
/** Generated schema (GET /modules/{name}/enable-preview). */
export type ModuleEnablePreview = components["schemas"]["ModuleEnablePreview"];

type ModuleSettingsResponse = components["schemas"]["ModuleSettingsResponse"];

/**
 * The settings response as the screens read it. The wire types
 * `settings_schema` as any JSON object; it is a JSON Schema document, and
 * this is the one place that says so — every other field comes from the
 * contract unchanged.
 */
export type ModuleSettings = Omit<ModuleSettingsResponse, "settings_schema"> & {
  settings_schema?: ModuleSettingsSchema | null;
};

export interface ModuleSettingsSchema {
  type: "object";
  properties?: Record<string, ModuleSettingsField>;
  required?: string[];
  additionalProperties?: boolean;
}

export interface ModuleSettingsField {
  type?: "string" | "integer" | "number" | "boolean" | "object" | "array";
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  format?: "secret" | string;
  default?: unknown;
  title?: string;
  description?: string;
  /** Full i18n keys (e.g. "recipes:settings.jinaApiKey") — preferred over literals. */
  title_key?: string;
  description_key?: string;
  /** Modules the setting is about; it is offered only where all are enabled. */
  requires_modules?: string[];
  properties?: Record<string, ModuleSettingsField>;
  required?: string[];
  additionalProperties?: boolean;
}

export const modulesApi = {
  getAvailable: async (): Promise<ModuleInfo[]> => {
    return getEveryPage<ModuleInfo>("/modules/available");
  },

  getMyModules: async (): Promise<string[]> => {
    const response = await api.get<string[]>("/modules/my");
    return response.data;
  },

  getFocus: async (): Promise<FocusModeResponse> => {
    const response = await api.get<FocusModeResponse>("/modules/focus");
    return response.data;
  },

  enablePreview: async (moduleName: string): Promise<ModuleEnablePreview> => {
    const response = await api.get<ModuleEnablePreview>(
      `/modules/${moduleName}/enable-preview`,
    );
    return response.data;
  },

  previewFocus: async (moduleName: string): Promise<FocusModeResponse> => {
    const response = await api.post<FocusModeResponse>(
      "/modules/focus/preview",
      {
        module_name: moduleName,
      },
    );
    return response.data;
  },

  applyFocus: async (moduleName: string): Promise<FocusModeResponse> => {
    const response = await api.post<FocusModeResponse>("/modules/focus", {
      module_name: moduleName,
    });
    return response.data;
  },

  exitFocus: async (): Promise<FocusModeResponse> => {
    const response = await api.delete<FocusModeResponse>("/modules/focus");
    return response.data;
  },

  toggleModule: async (
    moduleName: string,
    enabled: boolean,
  ): Promise<unknown> => {
    const response = await api.post("/modules/toggle", {
      module_name: moduleName,
      enabled,
    });
    return response.data;
  },

  getSettings: async (moduleName: string): Promise<ModuleSettings> => {
    const response = await api.get<ModuleSettings>(
      `/modules/${moduleName}/settings`,
    );
    return response.data;
  },

  updateSettings: async (
    moduleName: string,
    settings: Record<string, unknown>,
  ): Promise<{ status: string }> => {
    const response = await api.put<{ status: string }>(
      `/modules/${moduleName}/settings`,
      settings,
    );
    return response.data;
  },
};
