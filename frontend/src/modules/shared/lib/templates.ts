import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";

/**
 * URL path segment under which the backend mounts the templates API.
 * NOTE: it is the route segment, not the module directory name —
 * "purchase-orders" (hyphen) vs the directory "purchase_orders".
 */
export type TemplateUrlSegment = "warehouse" | "equipment" | "purchase-orders";

/** Backend module name stored in the `module` column of template rows. */
export type TemplateModuleName = "equipment" | "warehouse" | "purchase_orders";

/** Maps a URL segment to the module name the backend stores/validates. */
export const TEMPLATE_MODULE_NAME_BY_SEGMENT: Record<
  TemplateUrlSegment,
  TemplateModuleName
> = {
  warehouse: "warehouse",
  equipment: "equipment",
  "purchase-orders": "purchase_orders",
};

export type DocumentTemplate = components["schemas"]["DocumentTemplateSchema"];

export interface DocumentTemplateCreate {
  name: string;
  module?: TemplateModuleName;
  document_type?: string;
  body_html: string;
  is_default?: boolean;
}

export interface DocumentTemplateUpdate {
  name?: string;
  document_type?: string;
  body_html?: string;
  is_default?: boolean;
}

export type PlaceholderInfo = components["schemas"]["PlaceholderInfo"];

/** A layout shipped with the module, before anyone has copied it. */
export type BuiltInTemplate = components["schemas"]["BuiltInTemplate"];

export const templatesApi = {
  list: async (module: TemplateUrlSegment): Promise<DocumentTemplate[]> =>
    getEveryPage<DocumentTemplate>(`/${module}/templates`),

  get: async (
    module: TemplateUrlSegment,
    templateId: string,
  ): Promise<DocumentTemplate> => {
    const response = await api.get<DocumentTemplate>(
      `/${module}/templates/${templateId}`,
    );
    return response.data;
  },

  create: async (
    module: TemplateUrlSegment,
    data: DocumentTemplateCreate,
  ): Promise<DocumentTemplate> => {
    const response = await api.post<DocumentTemplate>(
      `/${module}/templates`,
      data,
    );
    return response.data;
  },

  update: async (
    module: TemplateUrlSegment,
    templateId: string,
    data: DocumentTemplateUpdate,
  ): Promise<DocumentTemplate> => {
    const response = await api.put<DocumentTemplate>(
      `/${module}/templates/${templateId}`,
      data,
    );
    return response.data;
  },

  delete: async (
    module: TemplateUrlSegment,
    templateId: string,
  ): Promise<void> => {
    await api.delete(`/${module}/templates/${templateId}`);
  },

  getPlaceholders: async (
    module: TemplateUrlSegment,
  ): Promise<PlaceholderInfo[]> => {
    const response = await api.get<PlaceholderInfo[]>(
      `/${module}/templates/placeholders`,
    );
    return response.data;
  },

  getBuiltIns: async (
    module: TemplateUrlSegment,
  ): Promise<BuiltInTemplate[]> => {
    const response = await api.get<BuiltInTemplate[]>(
      `/${module}/templates/built-in`,
    );
    return response.data;
  },

  /**
   * What a layout prints, rendered on a document made up for the purpose.
   *
   * The same rendering the PDF goes through — a preview that showed the
   * source answered "what does this template say", not "what will the paper
   * look like".
   */
  preview: async (
    module: TemplateUrlSegment,
    bodyHtml: string,
  ): Promise<string> => {
    const response = await api.post<{ html: string }>(
      `/${module}/templates/preview`,
      { body_html: bodyHtml },
    );
    return response.data.html;
  },

  /**
   * Copy the current built-in next to an organization's older copy.
   *
   * Alongside, never over: an organization's own edits are not something an
   * upgrade gets to discard, so this creates a second template and does not
   * change which one prints.
   */
  refreshCopy: async (
    module: TemplateUrlSegment,
    templateId: string,
  ): Promise<DocumentTemplate> => {
    const response = await api.post<DocumentTemplate>(
      `/${module}/templates/${templateId}/refresh-copy`,
    );
    return response.data;
  },

  seedDefaults: async (
    module: TemplateUrlSegment,
  ): Promise<DocumentTemplate[]> => {
    const response = await api.post<DocumentTemplate[]>(
      `/${module}/templates/seed-defaults`,
    );
    return response.data;
  },

  /**
   * The template as one file, ready to import on another installation.
   *
   * The file carries no instance identity — no ids, no timestamps — so it
   * lands elsewhere as if the template had been typed there.
   */
  exportTemplate: async (
    module: TemplateUrlSegment,
    templateId: string,
  ): Promise<Blob> => {
    const response = await api.get<Blob>(
      `/${module}/templates/${templateId}/export`,
      { responseType: "blob" },
    );
    return response.data;
  },

  /**
   * Save a template from an exported file: validated on the server, then
   * saved through the same door a hand-typed template uses. A refusal
   * comes back as the API's own sentence — an unknown placeholder is
   * named in it.
   */
  importTemplate: async (
    module: TemplateUrlSegment,
    file: File,
  ): Promise<DocumentTemplate> => {
    const form = new FormData();
    form.append("file", file);
    const response = await api.post<DocumentTemplate>(
      `/${module}/templates/import`,
      form,
    );
    return response.data;
  },
};
