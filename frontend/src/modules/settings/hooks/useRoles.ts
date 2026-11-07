/**
 * useRoles -- thin wrapper around GET /api/v1/roles.
 *
 * The RbacMatrix component uses
 * this to render the table of org roles. Mutations go through the
 * dedicated hooks below.
 *
 * Every route behind it asks for `system:config:write`, so the screen that
 * uses it opens to that key (SettingsShell, `components/settingsAccess.ts`).
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { components } from "@/types/api-generated";
import { queryKeys } from "@/hooks/queries/keys";
import { api, getEveryPage } from "@/lib/api/client";
import { invalidation } from "@/lib/api/invalidation";
import { useAuthStore } from "@/store/authStore";

export type Role = components["schemas"]["RoleDTO"];

/** Somebody holding a role: enough to name them on the refusal. */
export type RoleHolder = components["schemas"]["RoleHolderDTO"];

/** One permission as the backend defines it — see `PermissionDef` in
 *  `backend/app/core/module_manifest_schema.py`. */
export interface PermissionDefinition {
  key: string;
  label_key: string;
  description_key: string | null;
  default_roles: string[];
}

/** Grouped permissions for the matrix: system first, then one group per
 *  module the organisation has enabled. */
export interface PermissionCatalog {
  system: PermissionDefinition[];
  modules: Array<{
    module: string;
    /** The manifest's name; null when the registry does not know the module. */
    display_name?: string | null;
    permissions: PermissionDefinition[];
  }>;
}

/** Not exported: the shared client lives in @/lib/api/admin — a second
 *  exported one is how two screens end up asking two servers. */
const rolesApi = {
  list: async (): Promise<Role[]> => {
    return getEveryPage<Role>("/roles");
  },
  create: async (data: {
    name: string;
    permissions: string[];
  }): Promise<Role> => {
    const r = await api.post<Role>("/roles", data);
    return r.data;
  },
  updatePermissions: async (
    roleId: string,
    permissions: string[],
  ): Promise<Role> => {
    const r = await api.put<Role>(`/roles/${roleId}/permissions`, {
      permissions,
    });
    return r.data;
  },
  rename: async (roleId: string, name: string): Promise<Role> => {
    const r = await api.patch<Role>(`/roles/${roleId}`, { name });
    return r.data;
  },
  remove: async (roleId: string): Promise<void> => {
    await api.delete(`/roles/${roleId}`);
  },
  members: async (roleId: string): Promise<RoleHolder[]> => {
    return getEveryPage<RoleHolder>(`/roles/${roleId}/members`);
  },
  permissionCatalog: async (): Promise<PermissionCatalog> => {
    const r = await api.get<PermissionCatalog>("/roles/permission-catalog");
    return r.data;
  },
};

export function useRoles(enabled = true) {
  return useQuery({
    // The mutations below invalidate the "roles" prefix — the key used to be
    // parked under the audit-log list key, so creating a role in the matrix
    // never refreshed the pickers that read this hook.
    queryKey: queryKeys.roles.all,
    queryFn: () => rolesApi.list(),
    staleTime: 30_000,
    enabled,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: rolesApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.roles.all });
      // The rights of the session doing the editing may be among the ones
      // just changed; they live in the auth store, filled once at boot.
      void useAuthStore.getState().refreshUser();
    },
  });
}

export function useUpdateRolePermissions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      roleId,
      permissions,
    }: {
      roleId: string;
      permissions: string[];
    }) => rolesApi.updatePermissions(roleId, permissions),
    onSuccess: () => {
      invalidation.rights(qc);
      // The rights of the session doing the editing may be among the ones
      // just changed; they live in the auth store, filled once at boot.
      void useAuthStore.getState().refreshUser();
    },
  });
}

export function useRenameRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ roleId, name }: { roleId: string; name: string }) =>
      rolesApi.rename(roleId, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.roles.all });
      // The rights of the session doing the editing may be among the ones
      // just changed; they live in the auth store, filled once at boot.
      void useAuthStore.getState().refreshUser();
    },
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (roleId: string) => rolesApi.remove(roleId),
    onSuccess: (_removed, roleId) => {
      invalidation.rights(qc, roleId);
      // The rights of the session doing the editing may be among the ones
      // just changed; they live in the auth store, filled once at boot.
      void useAuthStore.getState().refreshUser();
    },
  });
}

/** Who holds a role — fetched only while the delete dialog is open, because
 *  that is the one moment their names matter. */
export function useRoleMembers(roleId: string | null) {
  return useQuery({
    queryKey: queryKeys.roles.members(roleId),
    queryFn: () => rolesApi.members(roleId as string),
    enabled: !!roleId,
  });
}

/** The permission catalog the matrix renders.
 *
 *  This replaces a hand-maintained copy of the backend `SystemPermission`
 *  enum. The copy could only ever show the twelve core permissions, so a
 *  module permission was undisplayable and therefore ungrantable — the
 *  endpoint guarding it would have rejected everyone forever. The catalog is
 *  org-scoped server-side: modules the organisation does not run contribute
 *  no columns. */
export function usePermissionCatalog() {
  return useQuery({
    queryKey: queryKeys.roles.permissionCatalog,
    queryFn: () => rolesApi.permissionCatalog(),
    staleTime: 5 * 60_000,
  });
}
