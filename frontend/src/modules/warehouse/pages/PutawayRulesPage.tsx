import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Pencil, Trash2, ArrowDownToLine } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { categoryLabel } from "@/lib/i18nHelpers";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { extractApiError } from "@/lib/errors";
import {
  usePutawayRules,
  useCreatePutawayRule,
  useUpdatePutawayRule,
  useDeletePutawayRule,
} from "@/modules/warehouse/hooks/usePutawayRules";
import type {
  PutawayRule,
  PutawayRuleCreate,
  PutawayRuleUpdate,
} from "@/modules/warehouse/api/putaway";
import { PutawayRuleEditorDialog } from "@/modules/warehouse/components/PutawayRuleEditorDialog";
import { SilencedHomeShelves } from "@/modules/warehouse/components/SilencedHomeShelves";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import { useLocationOffer } from "@/module-sdk";
import { toast } from "sonner";

/**
 * The putaway rules list.
 *
 * Reviewed against the nav-leave guard (`useFormGuard`) and deliberately left
 * out of it: nothing on this page is typed into the page. A rule is written
 * in `PutawayRuleEditorDialog`, which traps interaction while it is open —
 * no module tab is clickable, the route cannot change underneath it, and the
 * dialog's own close control is the exit. The guard's question could never
 * fire here, and arming it would only teach the reader to click through one.
 */
export default function PutawayRulesPage() {
  const { t } = useTranslation("warehouse");
  const { scoped: categories } = useScopedCategories();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("warehouse");
  const { data: rules, isLoading, isError, error, refetch } = usePutawayRules();
  const createMutation = useCreatePutawayRule();
  const updateMutation = useUpdatePutawayRule();
  const deleteMutation = useDeletePutawayRule();
  const { confirm, confirmDialogProps } = useConfirm();
  // The "no location to aim a rule at" check reads the same scoped set the
  // editor's target picker offers — an organization whose locations all
  // belong to modules has nowhere a general rule can point.
  const { total: placeCount } = useLocationOffer({ purpose: "general" });

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<PutawayRule | null>(null);
  // the backend rejects rules on unknown tags/type codes with a 400 —
  // surface that message inside the open dialog instead of failing silently.
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setHeader({
      title: t("putaway.title"),
      subtitle: t("putaway.subtitle"),
      actions: canWrite ? (
        <Button
          size="sm"
          leftIcon={<Plus size={16} />}
          onClick={() => {
            setEditingRule(null);
            setSaveError(null);
            setEditorOpen(true);
          }}
        >
          {t("putaway.actions.add", "Add Rule")}
        </Button>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  const closeEditor = () => {
    setEditorOpen(false);
    setEditingRule(null);
    setSaveError(null);
  };

  const handleSubmit = (data: PutawayRuleCreate | PutawayRuleUpdate) => {
    const onError = (err: unknown) => {
      setSaveError(
        extractApiError(
          err,
          t("putaway.errors.save_failed", "Failed to save putaway rule"),
        ),
      );
    };
    if (editingRule) {
      updateMutation.mutate(
        { id: editingRule.id, data: data as PutawayRuleUpdate },
        {
          onSuccess: () => {
            // Every other create/update in these modules confirms itself;
            // these three were the exception.
            toast.success(t("putaway.updated", "Putaway rule updated"));
            closeEditor();
          },
          onError,
        },
      );
    } else {
      createMutation.mutate(data as PutawayRuleCreate, {
        onSuccess: () => {
          toast.success(t("putaway.created", "Putaway rule created"));
          closeEditor();
        },
        onError,
      });
    }
  };

  const handleDelete = async (rule: PutawayRule) => {
    const ok = await confirm({
      title: t("putaway.delete_title", "Delete putaway rule"),
      message: t(
        "putaway.confirm_delete",
        "Are you sure you want to delete this putaway rule?",
      ),
      variant: "danger",
      confirmLabel: t("common:actions.delete", "Delete"),
    });
    if (ok) {
      deleteMutation.mutate(rule.id, {
        onSuccess: () =>
          toast.success(t("putaway.deleted", "Putaway rule removed")),
      });
    }
  };

  /** Build a human-readable label for the match keys of a rule. */
  const matchKeyLabel = (rule: PutawayRule): string => {
    const parts: string[] = [];
    if (rule.product_template_id)
      parts.push(
        `${t("putaway.fields.product_template_short", "Product")}: ${rule.product_template_name ?? `${rule.product_template_id.slice(0, 8)}…`}`,
      );
    if (rule.category_id) {
      // The rule stores the category's name as of its creation; the reader
      // gets the live, translated name while the record still exists.
      const category = categories?.find((c) => c.id === rule.category_id);
      const name = category
        ? categoryLabel(t, category.code, category.name)
        : (rule.category_name ?? `${rule.category_id.slice(0, 8)}…`);
      parts.push(`${t("putaway.fields.category_short", "Category")}: ${name}`);
    }
    if (rule.context_tag)
      parts.push(
        `${t("putaway.fields.context_tag", "Context")}: ${rule.context_tag}`,
      );
    if (rule.location_type_code)
      parts.push(
        `${t("putaway.fields.storage_type_short", "Type")}: ${rule.location_type_code}`,
      );
    return parts.join(" · ");
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="warehouse" />
      {isError ? (
        <QueryFailure
          error={error}
          message={t("errors.loadPutawayRulesFailed")}
          onRetry={() => refetch()}
        />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : placeCount === 0 ? (
        // The rule editor's target field has nothing to aim at until a storage
        // exists, and the screen used to say nothing about it.
        <StorageRequired />
      ) : !rules || rules.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 text-center">
          <ArrowDownToLine size={40} className="mb-4 text-on-secondary" />
          <h2 className="text-lg font-semibold text-on">
            {t("putaway.empty_title")}
          </h2>
          <p className="mt-1 max-w-md text-sm text-on-secondary">
            {/* No inline fallback: the catalogs carry the sentence, and a
                fallback copy is a second sentence to keep truthful — the
                old one promised automation over an empty state. */}
            {t("putaway.empty_description")}
          </p>
          {canWrite && (
            <Button
              className="mt-4"
              leftIcon={<Plus size={16} />}
              onClick={() => {
                setEditingRule(null);
                setEditorOpen(true);
              }}
            >
              {t("putaway.actions.create_first", "Create your first rule")}
            </Button>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface-raised text-left text-on-secondary">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">
                  {t("putaway.columns.match", "Match")}
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  {t("putaway.columns.priority", "Priority")}
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  {t("putaway.columns.status", "Status")}
                </th>
                <th scope="col" className="px-4 py-3 text-right font-medium">
                  {t("putaway.columns.actions", "Actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rules.map((rule) => (
                <tr key={rule.id} className="hover:bg-surface-raised/50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-on">
                      {matchKeyLabel(rule)}
                    </div>
                    <div className="text-xs text-on-secondary">
                      → {t("putaway.columns.target", "Target")}:{" "}
                      {rule.target_location_name ??
                        (rule.target_location_id
                          ? `${rule.target_location_id.slice(0, 8)}…`
                          : "—")}
                      {rule.target_location_active === false && (
                        <Badge variant="warning" className="ml-2">
                          {t(
                            "putaway.status.targetInactive",
                            "Target inactive",
                          )}
                        </Badge>
                      )}
                      {/* A rule walks an ordered list; this row named only
                          its head, so a rule with one shelf and a rule with
                          four read identically. */}
                      {(rule.locations?.length ?? 0) > 1 && (
                        <span className="ml-2">
                          {t("putaway.status.moreShelves", {
                            count: (rule.locations?.length ?? 1) - 1,
                          })}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-on-secondary">
                    {rule.priority}
                  </td>
                  <td className="px-4 py-3">
                    {rule.is_active ? (
                      <Badge variant="success">
                        {t("putaway.status.active", "Active")}
                      </Badge>
                    ) : (
                      <Badge variant="outline">
                        {t("putaway.status.inactive", "Inactive")}
                      </Badge>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {canWrite && (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditingRule(rule);
                            setEditorOpen(true);
                          }}
                          aria-label={`${t("common:actions.edit", "Edit")} ${matchKeyLabel(rule)}`}
                        >
                          <Pencil size={16} />
                        </Button>
                        <span
                          aria-hidden="true"
                          className="w-px h-5 shrink-0 bg-border mx-1"
                        />
                        <Button
                          variant="ghostDanger"
                          size="sm"
                          onClick={() => handleDelete(rule)}
                          aria-label={`${t("common:actions.delete", "Delete")} ${matchKeyLabel(rule)}`}
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SilencedHomeShelves canWrite={canWrite} />

      <PutawayRuleEditorDialog
        open={editorOpen}
        rule={editingRule}
        onClose={closeEditor}
        onSubmit={handleSubmit}
        isPending={createMutation.isPending || updateMutation.isPending}
        serverError={saveError}
      />
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
