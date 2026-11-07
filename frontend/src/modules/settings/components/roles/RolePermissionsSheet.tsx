import { extractApiError } from "@/lib/errors";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Info, Lock, Pencil, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import {
  useDeleteRole,
  useRenameRole,
  useRoleMembers,
  useUpdateRolePermissions,
  type PermissionDefinition,
  type Role,
} from "@/modules/settings/hooks/useRoles";
import { PermissionGroupSection } from "./PermissionGroupSection";
import {
  invisiblePermissions,
  roleDisplayName,
  type PermissionGroup,
} from "./rolePermissions";

interface RolePermissionsSheetProps {
  role: Role;
  groups: PermissionGroup[];
  onClose: () => void;
}

/**
 * What one role may do, edited one role at a time.
 *
 * Master–detail rather than a matrix: an administrator asks "what can this role
 * do?" and "let this role also do X" far more often than "who else holds this
 * one permission?", and a grid of roles × permissions answers only the last of
 * the three. Here each permission gets its label *and* the description the
 * catalog has always sent and the matrix threw away — a column header eight
 * characters wide could never carry it.
 */
export function RolePermissionsSheet({
  role,
  groups,
  onClose,
}: RolePermissionsSheetProps) {
  const { t } = useTranslation("common");
  const moduleLabels = useModuleLabels();
  const updateMutation = useUpdateRolePermissions();
  const renameMutation = useRenameRole();
  const deleteMutation = useDeleteRole();

  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState(role.name);
  const [deleting, setDeleting] = useState(false);
  // Only while the dialog is open: their names matter at that one moment.
  const { data: holders } = useRoleMembers(deleting ? role.id : null);

  const [granted, setGranted] = useState<Set<string>>(
    () => new Set(role.permissions),
  );
  const [search, setSearch] = useState("");
  // Collapsed unless the role holds something there. Opening a role should
  // show what it can do, not ten headings the reader has to open one by one —
  // and the per-group count says what is behind the ones that stay shut.
  const [collapsed, setCollapsed] = useState<Set<string>>(
    () =>
      new Set(
        groups
          .filter(
            (g) =>
              !g.permissions.some((p) => role.permissions?.includes(p.key)),
          )
          .map((g) => g.id),
      ),
  );

  const readOnly = role.is_system;
  const displayName = roleDisplayName(role, t);
  const dirty = useMemo(() => {
    const before = new Set(role.permissions);
    return (
      before.size !== granted.size ||
      [...granted].some((key) => !before.has(key))
    );
  }, [granted, role.permissions]);

  // Keys from a module that is no longer enabled. They have no checkbox, so
  // without carrying them the save would revoke access nobody touched.
  const carried = useMemo(
    () => invisiblePermissions(granted, groups),
    [granted, groups],
  );

  function labelFor(group: PermissionGroup): string {
    return group.module
      ? moduleLabels({
          name: group.module,
          display_name: group.displayName ?? group.module,
          description: "",
        }).name
      : t("settings.rbac.systemGroup");
  }

  /** The key itself as fallback: a module shipping no translation still reads. */
  const labelOf = (permission: PermissionDefinition) =>
    t(permission.label_key, { defaultValue: permission.key });

  const descriptionOf = (permission: PermissionDefinition) =>
    permission.description_key
      ? t(permission.description_key, { defaultValue: "" }) || null
      : null;

  function toggle(key: string) {
    setGranted((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll(keys: string[], on: boolean) {
    setGranted((prev) => {
      const next = new Set(prev);
      for (const key of keys) {
        if (on) next.add(key);
        else next.delete(key);
      }
      return next;
    });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await updateMutation.mutateAsync({
        roleId: role.id,
        permissions: [...granted],
      });
      toast.success(t("settings.rbac.saveSuccess"));
      onClose();
    } catch (error) {
      toast.error(extractApiError(error, t("settings.rbac.saveError")));
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="2xl"
      aria-label={t("settings.rbac.editTitle", { name: displayName })}
    >
      <SheetHeader onClose={onClose}>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-on text-lg truncate">
            {displayName}
          </h2>
          <p className="text-xs text-on-muted mt-0.5">
            {readOnly
              ? t("settings.rbac.systemRole")
              : t("settings.rbac.editSubtitle", { n: granted.size })}
          </p>
        </div>
        {/* Renaming and deleting act on the role, not on this edit, so they
            stand beside the close button rather than adding a footer row. */}
        {!readOnly && (
          <ActionMenu
            label={t("settings.rbac.roleActions", { name: displayName })}
            layer="modal"
            actions={[
              {
                id: "rename",
                label: t("settings.rbac.rename"),
                icon: <Pencil size={16} />,
                onSelect: () => {
                  setNewName(role.name);
                  setRenaming(true);
                },
              },
              {
                id: "delete",
                label: t("actions.delete"),
                icon: <Trash2 size={16} />,
                destructive: true,
                onSelect: () => setDeleting(true),
              },
            ]}
          />
        )}
      </SheetHeader>

      <SheetBody className="space-y-3 p-5">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("settings.rbac.searchPermissions")}
          leftIcon={<Search size={16} />}
          aria-label={t("settings.rbac.searchPermissions")}
        />

        {carried.length > 0 && (
          <p className="flex items-start gap-2 rounded-lg bg-surface-raised px-3 py-2 text-xs text-on-secondary">
            <Info
              size={14}
              className="mt-0.5 shrink-0 text-on-muted"
              aria-hidden
            />
            {t("settings.rbac.carriedPermissions", { n: carried.length })}
          </p>
        )}

        {groups.map((group) => (
          <PermissionGroupSection
            key={group.id}
            group={group}
            label={labelFor(group)}
            granted={granted}
            readOnly={readOnly}
            expanded={!collapsed.has(group.id)}
            search={search}
            onToggleExpanded={() =>
              setCollapsed((prev) => {
                const next = new Set(prev);
                if (next.has(group.id)) next.delete(group.id);
                else next.add(group.id);
                return next;
              })
            }
            onToggle={toggle}
            onToggleAll={toggleAll}
            labelOf={labelOf}
            descriptionOf={descriptionOf}
            countLabel={(held, total) =>
              t("settings.rbac.groupCount", { held, total })
            }
          />
        ))}
      </SheetBody>

      {readOnly ? (
        <SheetFooter>
          <p className="flex items-center gap-2 text-xs text-on-muted">
            <Lock size={14} aria-hidden />
            {t("settings.rbac.systemRoleFooter")}
          </p>
          <Button variant="outline" onClick={onClose}>
            {t("actions.close")}
          </Button>
        </SheetFooter>
      ) : (
        <FormSheetFooter
          isPending={updateMutation.isPending}
          lineCount={0}
          cancelText={t("actions.cancel")}
          submitText={t("actions.save")}
          submitDisabled={!dirty}
          onCancel={onClose}
          onSubmit={(event) => void save(event)}
        />
      )}

      <ConfirmDialog
        open={renaming}
        title={t("settings.rbac.rename")}
        message={t("settings.rbac.renameMessage")}
        confirmLabel={t("actions.save")}
        cancelLabel={t("actions.cancel")}
        confirmDisabled={
          !newName.trim() ||
          newName.trim() === role.name ||
          renameMutation.isPending
        }
        onConfirm={() => {
          renameMutation.mutate(
            { roleId: role.id, name: newName.trim() },
            {
              onSuccess: () => {
                setRenaming(false);
                toast.success(t("settings.rbac.renameSuccess"));
              },
              onError: (err: unknown) =>
                toast.error(
                  extractApiError(err, t("settings.rbac.renameError")),
                ),
            },
          );
        }}
        onCancel={() => setRenaming(false)}
      >
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          aria-label={t("settings.rbac.roleNameLabel")}
          autoFocus
        />
      </ConfirmDialog>

      {/* Held roles get an informational dialog, not a confirmation: the
          answer is to change those people's role first, and a red button
          offering to do it anyway would be offering the wrong thing. */}
      <ConfirmDialog
        open={deleting}
        variant="danger"
        title={t("settings.rbac.deleteTitle", { name: role.name })}
        message={
          holders && holders.length > 0
            ? t("settings.rbac.deleteBlocked")
            : t("settings.rbac.deleteMessage")
        }
        confirmLabel={t("actions.delete")}
        cancelLabel={
          holders && holders.length > 0
            ? t("actions.close")
            : t("actions.cancel")
        }
        hideConfirm={!!holders && holders.length > 0}
        confirmDisabled={deleteMutation.isPending}
        onConfirm={() => {
          deleteMutation.mutate(role.id, {
            onSuccess: () => {
              setDeleting(false);
              toast.success(t("settings.rbac.deleteSuccess"));
              onClose();
            },
            // The holders this sheet read are a snapshot; the server is the
            // authority and says which rule stopped the delete.
            onError: (err: unknown) =>
              toast.error(extractApiError(err, t("settings.rbac.deleteError"))),
          });
        }}
        onCancel={() => setDeleting(false)}
      >
        {holders && holders.length > 0 && (
          <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg bg-surface-raised p-3 text-sm">
            {holders.map((holder) => (
              // One string rather than two nodes: a name and an address read
              // out as separate fragments is not how anyone says a person.
              <li key={holder.id} className="truncate text-on-secondary">
                {holder.full_name
                  ? `${holder.full_name} · ${holder.email}`
                  : holder.email}
              </li>
            ))}
          </ul>
        )}
      </ConfirmDialog>
    </Sheet>
  );
}
