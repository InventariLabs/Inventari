import { extractApiError } from "@/lib/errors";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, Loader2, Lock, Plus, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";
import { Input } from "@/components/ui/Input";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import {
  useCreateRole,
  usePermissionCatalog,
  useRoles,
  type Role,
} from "@/modules/settings/hooks/useRoles";
import { RolePermissionsSheet } from "./RolePermissionsSheet";
import {
  permissionGroups,
  roleDisplayName,
  summarizeRole,
  type PermissionGroup,
} from "./rolePermissions";

/** How many area names a row spells out before it starts counting. */
const AREAS_SHOWN = 3;

/**
 * "Built-in", said where the reader is looking.
 *
 * A lock with a screen-reader label answers the question for one reader and
 * nobody else, and the row's other clue — a button reading "View" — names the
 * act rather than the reason. An administrator who may change permissions
 * concluded from a column of padlocks that they may not.
 *
 * A `<Badge>` is the shape for this, but it renders a `div`, and on the phone
 * layout the chip sits inside a `<button>`, whose content model is phrasing.
 */
function BuiltInChip({ label, title }: { label: string; title: string }) {
  return (
    <span
      title={title}
      className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-surface-raised px-2 py-0.5 text-[10px] font-medium uppercase tracking-widest text-on-secondary"
    >
      <Lock size={10} aria-hidden />
      {label}
    </span>
  );
}

/**
 * The organisation's roles, and what each of them may do.
 *
 * This replaced a matrix of roles × permissions. That grid had one column per
 * permission of every installed module — thirty-three with nine modules on, and
 * one more for every module installed afterwards — so reading a single role
 * meant scrolling sideways past everything the role did *not* have. The two
 * questions an administrator actually asks are about one role at a time, and
 * this list answers the first of them without opening anything.
 */
export default function RolesPage() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();
  const moduleLabels = useModuleLabels();
  const { data: roles, isLoading, isError, error, refetch } = useRoles();
  const { data: catalog, isLoading: catalogLoading } = usePermissionCatalog();
  const createMutation = useCreateRole();

  const [editing, setEditing] = useState<Role | null>(null);
  const [creating, setCreating] = useState(false);
  const [newRoleName, setNewRoleName] = useState("");

  useEffect(() => {
    setHeader({
      title: t("settings.rbac.title"),
      subtitle: t("settings.rbac.subtitle"),
      actions: (
        <Button leftIcon={<Plus size={18} />} onClick={() => setCreating(true)}>
          {t("settings.rbac.createRole")}
        </Button>
      ),
    });
  }, [setHeader, t]);

  const groups = useMemo(() => permissionGroups(catalog), [catalog]);

  function areaLabel(group: PermissionGroup): string {
    return group.module
      ? moduleLabels({
          name: group.module,
          display_name: group.displayName ?? group.module,
          description: "",
        }).name
      : t("settings.rbac.systemGroup");
  }

  /** "Documents, Stock takes, Products +2" — the areas, not the count. */
  function scopeOf(role: Role): string {
    const { areas } = summarizeRole(role, groups);
    if (areas.length === 0) return t("settings.rbac.noPermissions");
    const byId = new Map(groups.map((g) => [g.id, g]));
    const names = areas
      .slice(0, AREAS_SHOWN)
      .map((id) => areaLabel(byId.get(id)!));
    const rest = areas.length - names.length;
    return rest > 0
      ? t("settings.rbac.scopeMore", { areas: names.join(", "), n: rest })
      : names.join(", ");
  }

  async function createRole(event: React.FormEvent) {
    event.preventDefault();
    const name = newRoleName.trim();
    if (!name) return;
    try {
      const role = await createMutation.mutateAsync({ name, permissions: [] });
      setNewRoleName("");
      setCreating(false);
      toast.success(t("settings.rbac.createSuccess"));
      // Straight into the editor: a role with no permissions does nothing, so
      // creating one and being returned to the list is never the whole task.
      setEditing(role);
    } catch (error) {
      toast.error(extractApiError(error, t("settings.rbac.createError")));
    }
  }

  if (isLoading || catalogLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-on-muted" />
      </div>
    );
  }

  const list = roles ?? [];
  const hasCustomRole = list.some((role) => !role.is_system);

  return (
    <div className="space-y-6">
      {/* "No custom roles yet" is an answer about this organization. A failed
          read knows nothing about it — and there were seven. */}
      {isError ? (
        <QueryFailure error={error} onRetry={() => refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title={t("settings.rbac.emptyTitle")}
          description={t("settings.rbac.emptyDescription")}
          primaryAction={
            <Button
              leftIcon={<Plus size={18} />}
              onClick={() => setCreating(true)}
            >
              {t("settings.rbac.createRole")}
            </Button>
          }
        />
      ) : (
        <Card className="p-0 overflow-hidden">
          {/* Desktop: a list of records is a table (§14.1). */}
          <table
            data-testid="roles-table"
            className="hidden sm:table w-full table-fixed text-sm"
          >
            <colgroup>
              <col className="w-[30%]" />
              <col className="w-[40%]" />
              <col className="w-[11%]" />
              <col className="w-[11%]" />
              <col className="w-[8%]" />
            </colgroup>
            <thead className="bg-surface-raised border-b border-border">
              <tr>
                <th
                  scope="col"
                  className="px-4 py-2.5 text-left font-medium text-on-secondary"
                >
                  {t("settings.rbac.roleColumn")}
                </th>
                <th
                  scope="col"
                  className="px-4 py-2.5 text-left font-medium text-on-secondary"
                >
                  {t("settings.rbac.scopeColumn")}
                </th>
                <th
                  scope="col"
                  className="px-4 py-2.5 text-right font-medium text-on-secondary"
                >
                  {t("settings.rbac.countColumn")}
                </th>
                {/* Deleting a role somebody holds is refused, so the number
                    that decides it belongs on the row, not in the refusal. */}
                <th
                  scope="col"
                  className="px-4 py-2.5 text-right font-medium text-on-secondary"
                >
                  {t("settings.rbac.membersColumn")}
                </th>
                <th scope="col" className="px-4 py-2.5">
                  <span className="sr-only">{t("actions.edit")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((role) => (
                <tr
                  key={role.id}
                  className="border-b border-border/60 last:border-0 hover:bg-surface-raised/50"
                >
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-2 min-w-0">
                      <span className="font-medium text-on truncate">
                        {roleDisplayName(role, t)}
                      </span>
                      {role.is_system && (
                        <BuiltInChip
                          label={t("settings.rbac.builtInBadge")}
                          title={t("settings.rbac.systemRole")}
                        />
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-on-secondary truncate">
                    {scopeOf(role)}
                  </td>
                  <td className="px-4 py-3 text-right text-on-muted tabular-nums">
                    {(role.permissions ?? []).length}
                  </td>
                  <td className="px-4 py-3 text-right text-on-muted tabular-nums">
                    {role.member_count}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setEditing(role)}
                    >
                      {role.is_system
                        ? t("actions.view")
                        : t("settings.rbac.editPermissions")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Phone: the same records as cards. */}
          <ul
            data-testid="roles-cards"
            className="sm:hidden divide-y divide-border/60"
          >
            {list.map((role) => (
              <li key={role.id}>
                {/* eslint-disable-next-line no-restricted-syntax -- full-width content target with the card's own layout, not a chrome button; Button variants would impose padding/height/rounding */}
                <button
                  type="button"
                  onClick={() => setEditing(role)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-raised/50"
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="font-medium text-on truncate">
                        {roleDisplayName(role, t)}
                      </span>
                      {role.is_system && (
                        <BuiltInChip
                          label={t("settings.rbac.builtInBadge")}
                          title={t("settings.rbac.systemRole")}
                        />
                      )}
                    </span>
                    <span className="block text-xs text-on-muted truncate mt-0.5">
                      {scopeOf(role)}
                    </span>
                  </span>
                  <ChevronRight
                    size={16}
                    aria-hidden
                    className="shrink-0 text-on-muted"
                  />
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!isError && list.length > 0 && (
        <div className="space-y-1.5 text-xs text-on-muted">
          {/* Why the locked rows are locked, and what to do instead — a
              standing fact about the built-in levels, so it does not go away
              once the organisation has a role of its own. */}
          <p>
            {t("settings.rbac.builtInNote")}{" "}
            <Button
              variant="ghost"
              size="inline"
              className="text-xs underline"
              onClick={() => setCreating(true)}
            >
              {t("settings.rbac.createRole")}
            </Button>
          </p>
          {/* The empty state carried this sentence, and the list is never
              empty now that the built-in levels are on it. The advice is
              still the advice: the four levels answer most of it, and a
              custom role is for the case they do not. */}
          {!hasCustomRole && <p>{t("settings.rbac.emptyDescription")}</p>}
        </div>
      )}

      {editing && (
        <RolePermissionsSheet
          role={editing}
          groups={groups}
          onClose={() => setEditing(null)}
        />
      )}

      {creating && (
        <Sheet
          open
          onClose={() => setCreating(false)}
          maxWidth="sm"
          aria-label={t("settings.rbac.createRole")}
        >
          <SheetHeader
            title={t("settings.rbac.createRole")}
            onClose={() => setCreating(false)}
          />
          <SheetBody className="p-5">
            <label
              htmlFor="new-role-name"
              className="block text-sm font-medium text-on-secondary mb-1.5"
            >
              {t("settings.rbac.roleNameLabel")}
            </label>
            <Input
              id="new-role-name"
              value={newRoleName}
              onChange={(e) => setNewRoleName(e.target.value)}
              placeholder={t("settings.rbac.newRolePlaceholder")}
              autoFocus
            />
            <p className="mt-1.5 text-xs text-on-muted">
              {t("settings.rbac.createHint")}
            </p>
          </SheetBody>
          <FormSheetFooter
            isPending={createMutation.isPending}
            lineCount={0}
            cancelText={t("actions.cancel")}
            submitText={t("actions.create")}
            submitDisabled={!newRoleName.trim()}
            onCancel={() => setCreating(false)}
            onSubmit={(event) => void createRole(event)}
          />
        </Sheet>
      )}
    </div>
  );
}
