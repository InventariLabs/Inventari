import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";

/** A catalogue entry: the key and the translation key that labels it. */
type ListedPermission = { key: string; label_key: string };

/**
 * How a permission reads on this screen.
 *
 * A wording this module wrote for a key comes first — what `org:settings:write`
 * stands for is worth a sentence here that the roles editor does not need —
 * then the catalogue's own label, the one the roles editor shows, and last the
 * raw key, named as such: a permission nobody has labelled still has to read
 * as something rather than a blank line.
 */
export function usePermissionLabel(
  catalog: ListedPermission[] | undefined,
): (permission: string) => string {
  const { t } = useTranslation("api_keys");
  return useCallback(
    (permission: string) => {
      const entry = catalog?.find((option) => option.key === permission);
      const fallback = entry
        ? t(entry.label_key, {
            defaultValue: t("capabilities.unknown", { key: permission }),
          })
        : t("capabilities.unknown", { key: permission });
      return t(`capabilities.permissions.${permission.replace(/:/g, "_")}`, {
        defaultValue: fallback,
      });
    },
    [catalog, t],
  );
}

/**
 * The same label for a screen that is not the key module's — the audit log
 * names a key's permissions by it. Null for a permission the catalogue does
 * not list, so the caller keeps what it has. The catalogue is the core one
 * every module's permissions are declared in, asked for whole: the history of
 * a key reads the same whether the module that issued it, or the module a
 * permission belongs to, is switched on today. Read only while `enabled`.
 */
export function useListedPermissionLabel(
  enabled: boolean,
): (permission: string) => string | null {
  const { data } = useQuery({
    queryKey: queryKeys.roles.permissionCatalogAll,
    queryFn: async () => {
      const { data: catalog } = await api.get<{
        system: ListedPermission[];
        modules: Array<{ permissions: ListedPermission[] }>;
      }>("/roles/permission-catalog", { params: { all_modules: true } });
      return [
        ...catalog.system,
        ...catalog.modules.flatMap((group) => group.permissions),
      ];
    },
    enabled,
    staleTime: 5 * 60_000,
  });
  const label = usePermissionLabel(data);
  return useCallback(
    (permission: string) =>
      data?.some((option) => option.key === permission)
        ? label(permission)
        : null,
    [data, label],
  );
}
