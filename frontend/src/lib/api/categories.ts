import { api, getEveryPage } from "./client";
import type { CategoryDTO } from "@/types";

export const categoriesApi = {
  getAll: async (
    include_inactive?: boolean,
    exclude_module_contexts?: boolean,
    with_counts?: boolean,
  ): Promise<CategoryDTO[]> => {
    const params: Record<string, unknown> = {};
    if (include_inactive) params.include_inactive = include_inactive;
    if (exclude_module_contexts)
      params.exclude_module_contexts = exclude_module_contexts;
    if (with_counts) params.with_counts = with_counts;
    return getEveryPage<CategoryDTO>("/categories", params);
  },

  create: async (data: Partial<CategoryDTO>): Promise<CategoryDTO> => {
    const response = await api.post<CategoryDTO>("/categories", data);
    return response.data;
  },

  update: async (
    id: string,
    data: Partial<CategoryDTO>,
  ): Promise<CategoryDTO> => {
    const response = await api.put<CategoryDTO>(`/categories/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/categories/${id}`);
  },

  /**
   * Rename the group every category in it carries, or take it away.
   *
   * A group is a label repeated on categories, not a record — so this is one
   * request instead of opening each category in turn, which for a seeded
   * group means a dozen or more.
   *
   * `categoryIds` — the ids a previous call returned — acts on exactly those
   * categories, which is how a removed group is put back.
   */
  renameGroup: async (
    currentName: string,
    newName: string | null,
    categoryIds?: string[],
  ): Promise<{ updated: number; category_ids: string[] }> => {
    const response = await api.patch<{
      updated: number;
      category_ids: string[];
    }>("/categories/groups", {
      current_name: currentName,
      new_name: newName,
      category_ids: categoryIds,
    });
    return response.data;
  },
};
