import { extractApiError } from "@/lib/errors";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { resolveLang } from "@/i18n/languages";
import { Pencil, Check, X, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  useUnitConversions,
  useCreateUnitConversion,
  useUpdateUnitConversion,
  useDeleteUnitConversion,
} from "@/modules/recipes/hooks/useUnitConversions";
import type {
  UnitConversion,
  UnitConversionCreate,
} from "@/modules/recipes/types/nutrition-defaults";
import { ConversionToolbar } from "./ConversionToolbar";
import { ConversionAddForm, categoryLabel } from "./ConversionAddForm";
import { UnitConversionsEmptyState } from "./UnitConversionsEmptyState";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { unitLabel } from "@/lib/i18nHelpers";

const CATEGORY_ORDER = ["dry", "liquid", "fat", "other"] as const;

type EditDraft = {
  ingredient_name: string;
  metric_quantity: string;
  metric_unit: string;
};

export default function UnitConversionsPage() {
  const { t, i18n } = useTranslation(["recipes", "common"]);
  const canWrite = useCanWrite("recipes");
  const lang = resolveLang(i18n.language);

  const { data: conversions, isLoading } = useUnitConversions(lang);
  const createMutation = useCreateUnitConversion();
  const updateMutation = useUpdateUnitConversion();
  const deleteMutation = useDeleteUnitConversion();

  const [q, setQ] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<Partial<UnitConversionCreate>>({
    metric_unit: "g",
    category: "dry",
    lang,
  });

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);

  // Filter + group by category
  const grouped = useMemo(() => {
    if (!conversions) return {};
    const lq = q.toLowerCase();
    const filtered = lq
      ? conversions.filter(
          (c) =>
            c.ingredient_name.toLowerCase().includes(lq) ||
            c.ingredient_key.toLowerCase().includes(lq) ||
            c.source_unit.toLowerCase().includes(lq),
        )
      : conversions;

    const groups: Record<string, UnitConversion[]> = {};
    for (const c of filtered) {
      const cat = c.category || "other";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(c);
    }
    // Sort each group by ingredient_name then source_unit
    for (const arr of Object.values(groups)) {
      arr.sort((a, b) =>
        a.ingredient_name === b.ingredient_name
          ? a.source_unit.localeCompare(b.source_unit)
          : a.ingredient_name.localeCompare(b.ingredient_name),
      );
    }
    return groups;
  }, [conversions, q]);

  const totalFiltered = useMemo(
    () => Object.values(grouped).reduce((s, arr) => s + arr.length, 0),
    [grouped],
  );

  const startEdit = (row: UnitConversion) => {
    setEditingId(row.id);
    setEditDraft({
      ingredient_name: row.ingredient_name,
      metric_quantity: String(row.metric_quantity),
      metric_unit: row.metric_unit,
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft(null);
  };

  const saveEdit = async (row: UnitConversion) => {
    if (!editDraft || !editDraft.metric_quantity) return;
    try {
      await updateMutation.mutateAsync({
        id: row.id,
        data: {
          ingredient_name: editDraft.ingredient_name,
          metric_quantity: Number(editDraft.metric_quantity),
          metric_unit: editDraft.metric_unit,
        },
      });
      toast.success(t("unit_conversions.updated"));
      cancelEdit();
    } catch (error) {
      toast.error(extractApiError(error, t("unit_conversions.error_save")));
    }
  };

  const handleDelete = async (row: UnitConversion) => {
    if (row.is_system) {
      toast.error(t("unit_conversions.cannot_delete_system"));
      return;
    }
    try {
      await deleteMutation.mutateAsync(row.id);
      toast.success(
        row.organization_id
          ? t("unit_conversions.deleted")
          : t("unit_conversions.override_reset", {
              name: row.ingredient_name,
            }),
      );
    } catch (error) {
      toast.error(extractApiError(error, t("unit_conversions.error_delete")));
    }
  };

  const handleAdd = async () => {
    if (
      !form.ingredient_key ||
      !form.ingredient_name ||
      !form.source_unit ||
      !form.metric_quantity
    ) {
      toast.error(t("unit_conversions.error_required"));
      return;
    }
    try {
      await createMutation.mutateAsync({
        ingredient_key: form.ingredient_key,
        ingredient_name: form.ingredient_name,
        source_unit: form.source_unit,
        metric_quantity: Number(form.metric_quantity),
        metric_unit: form.metric_unit || "g",
        category: form.category || "other",
        lang,
      });
      toast.success(t("unit_conversions.added"));
      setShowAdd(false);
      setForm({ metric_unit: "g", category: "dry", lang });
    } catch (error) {
      toast.error(extractApiError(error, t("unit_conversions.error_save")));
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      <ReadOnlyNotice module="recipes" />
      <ConversionToolbar
        q={q}
        onSearch={setQ}
        onToggleAdd={() => setShowAdd((p) => !p)}
        canWrite={canWrite}
        t={t}
      />

      {showAdd && (
        <ConversionAddForm
          form={form}
          onFormChange={setForm}
          onAdd={handleAdd}
          onCancel={() => setShowAdd(false)}
          t={t}
        />
      )}

      {/* Loading */}
      {isLoading && <LoadingSpinner />}

      {/* Empty state */}
      {!isLoading && totalFiltered === 0 && <UnitConversionsEmptyState t={t} />}

      {/* Grouped tables */}
      {!isLoading &&
        CATEGORY_ORDER.filter((cat) => grouped[cat]?.length).map((cat) => (
          <div key={cat}>
            <h3 className="text-sm font-semibold text-on-secondary mb-2">
              {categoryLabel(t, cat)}
            </h3>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-surface-raised text-left text-xs font-medium text-on-secondary">
                    <th className="px-3 py-2">
                      {t("unit_conversions.col_ingredient")}
                    </th>
                    <th className="px-3 py-2">
                      {t("unit_conversions.col_unit")}
                    </th>
                    <th className="px-3 py-2">
                      {t("unit_conversions.col_metric")}
                    </th>
                    <th className="px-3 py-2">
                      {t("unit_conversions.col_source")}
                    </th>
                    {canWrite && <th className="px-3 py-2 w-24" />}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {grouped[cat]!.map((row) => {
                    const isEditing = editingId === row.id;
                    return (
                      <tr key={row.id} className="hover:bg-surface-inset/50">
                        {isEditing ? (
                          <>
                            <td className="px-3 py-1.5">
                              <Input
                                aria-label={t("form.ingredient_name")}
                                value={editDraft?.ingredient_name || ""}
                                onChange={(e) =>
                                  setEditDraft((d) =>
                                    d
                                      ? {
                                          ...d,
                                          ingredient_name: e.target.value,
                                        }
                                      : d,
                                  )
                                }
                                className="h-7 text-xs"
                              />
                            </td>
                            <td className="px-3 py-1.5 text-on-secondary">
                              {unitLabel(t, row.source_unit)}
                            </td>
                            <td className="px-3 py-1.5">
                              <div className="flex items-center gap-1">
                                <Input
                                  wrapperClassName="w-20"
                                  type="number"
                                  aria-label={t("unit_conversions.col_metric")}
                                  value={editDraft?.metric_quantity || ""}
                                  onChange={(e) =>
                                    setEditDraft((d) =>
                                      d
                                        ? {
                                            ...d,
                                            metric_quantity: e.target.value,
                                          }
                                        : d,
                                    )
                                  }
                                  className="h-7 text-xs"
                                />
                                <NativeSelect
                                  className="text-xs"
                                  aria-label={t("unit_conversions.col_metric")}
                                  value={editDraft?.metric_unit || "g"}
                                  onChange={(e) =>
                                    setEditDraft((d) =>
                                      d
                                        ? {
                                            ...d,
                                            metric_unit: e.target.value,
                                          }
                                        : d,
                                    )
                                  }
                                >
                                  <option value="g">g</option>
                                  <option value="ml">ml</option>
                                </NativeSelect>
                              </div>
                            </td>
                            <td className="px-3 py-1.5" />
                            <td className="px-3 py-1.5">
                              <div className="flex gap-1">
                                <Button
                                  type="button"
                                  size="iconSm"
                                  variant="ghost"
                                  onClick={() => saveEdit(row)}
                                  className="rounded text-accent-700"
                                  aria-label={t("common:actions.save")}
                                  title={t("common:actions.save")}
                                >
                                  <Check size={16} />
                                </Button>
                                <Button
                                  type="button"
                                  size="iconSm"
                                  variant="ghost"
                                  onClick={cancelEdit}
                                  className="rounded text-on-muted hover:text-on hover:bg-transparent active:bg-transparent"
                                  aria-label={t("common:actions.cancel")}
                                  title={t("common:actions.cancel")}
                                >
                                  <X size={16} />
                                </Button>
                              </div>
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="px-3 py-1.5">
                              <span className="font-medium text-on">
                                {row.ingredient_name}
                              </span>
                              {/* system rows already carry a localized
                                  name — the raw key would show "Dried fruit
                                  (dried_fruit)". Custom rows keep it, the user
                                  typed it on purpose. */}
                              {!row.is_system && (
                                <span className="ml-1.5 text-xs text-on-muted">
                                  ({row.ingredient_key})
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 text-on-secondary">
                              {unitLabel(t, row.source_unit)}
                            </td>
                            <td className="px-3 py-1.5 font-mono text-on-secondary">
                              {Number(row.metric_quantity)} {row.metric_unit}
                            </td>
                            <td className="px-3 py-1.5">
                              <Badge
                                variant={
                                  row.is_system ? "secondary" : "default"
                                }
                              >
                                {row.is_system
                                  ? t("unit_conversions.system")
                                  : t("unit_conversions.custom")}
                              </Badge>
                            </td>
                            {canWrite && (
                              <td className="px-3 py-1.5">
                                <div className="flex gap-1">
                                  <Button
                                    type="button"
                                    size="iconSm"
                                    variant="ghost"
                                    onClick={() => startEdit(row)}
                                    className="rounded text-on-muted hover:text-on hover:bg-transparent active:bg-transparent"
                                    aria-label={t(
                                      "unit_conversions.tooltip_edit",
                                    )}
                                    title={t("unit_conversions.tooltip_edit")}
                                  >
                                    <Pencil size={16} />
                                  </Button>
                                  {row.is_system ? (
                                    row.organization_id && (
                                      <Button
                                        type="button"
                                        size="iconSm"
                                        variant="ghost"
                                        onClick={() => handleDelete(row)}
                                        className="rounded text-on-muted hover:text-amber-600 hover:bg-transparent active:bg-transparent"
                                        aria-label={t(
                                          "unit_conversions.tooltip_reset",
                                        )}
                                        title={t(
                                          "unit_conversions.tooltip_reset",
                                        )}
                                      >
                                        <RotateCcw size={16} />
                                      </Button>
                                    )
                                  ) : (
                                    <Button
                                      type="button"
                                      size="iconSm"
                                      variant="ghostDanger"
                                      onClick={() => handleDelete(row)}
                                      className="rounded"
                                      aria-label={t("common:actions.delete")}
                                      title={t("common:actions.delete")}
                                    >
                                      <Trash2 size={16} />
                                    </Button>
                                  )}
                                </div>
                              </td>
                            )}
                          </>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}

      {/* Footer count */}
      {!isLoading && totalFiltered > 0 && (
        <p className="text-xs text-on-muted text-center">
          {t("unit_conversions.showing", { count: totalFiltered })}
        </p>
      )}
    </div>
  );
}
