import { api, getEveryPage } from "./client";
import type { components } from "@/types/api-generated";
import type { User, Uom, UomCategory } from "@/types";

export const usersApi = {
  getAll: async (): Promise<User[]> => {
    return getEveryPage<User>("/users");
  },

  getOrgMembers: async (): Promise<User[]> => {
    return getEveryPage<User>("/users/org-members");
  },

  activate: async (userId: string): Promise<User> => {
    const response = await api.post<User>(`/users/${userId}/activate`);
    return response.data;
  },

  block: async (userId: string, reason?: string): Promise<User> => {
    const response = await api.post<User>(`/users/${userId}/block`, { reason });
    return response.data;
  },

  unblock: async (userId: string): Promise<User> => {
    const response = await api.post<User>(`/users/${userId}/unblock`);
    return response.data;
  },
};

export const uomsApi = {
  getAll: async (): Promise<Uom[]> => {
    return getEveryPage<Uom>("/uoms");
  },

  getCategories: async (): Promise<UomCategory[]> => {
    return getEveryPage<UomCategory>("/uoms/categories");
  },
};

type Role = components["schemas"]["RoleDTO"];

export const rolesApi = {
  list: async (): Promise<Role[]> => {
    return getEveryPage<Role>("/roles");
  },
  /** Who holds an organization's own role; a built-in level has no holder
   * rows (it lives on the member's `role`), so it is not asked here. */
  members: async (roleId: string): Promise<{ id: string }[]> => {
    return getEveryPage<{ id: string }>(`/roles/${roleId}/members`);
  },
};
