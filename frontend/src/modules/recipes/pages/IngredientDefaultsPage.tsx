import { extractApiError } from "@/lib/errors";
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { TranslateFn } from "@/types/i18n";
import { useDebounce } from "@/module-sdk";
import { useTranslation } from "react-i18next";

import { LANGUAGE_NAMES, resolveLang } from "@/i18n/languages";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { downloadBlob } from "@/utils/helpers";
import { Button } from "@/components/ui/Button";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { NutritionToolbar } from "./NutritionToolbar";
import { QueryFailure } from "@/components/ui/QueryResult";
import { NutritionAddForm } from "./NutritionAddForm";
import { useModules } from "@/contexts/ModulesContext";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useCanWrite } from "@/hooks/useCanWrite";
import { NutritionTableRow } from "./NutritionTableRow";
import {
  useIngredientDefaultsList,
  useCreateIngredientDefault,
  useDeleteIngredientDefault,
  useImportIngredientDefaults,
} from "@/modules/recipes/hooks/useIngredientDefaults";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type {
  IngredientDefault,
  IngredientDefaultCreate,
} from "@/modules/recipes/types/nutrition-defaults";

type EditDraft = {
  calories_kcal: string;
  protein_g: string;
  fat_g: string;
  carbs_g: string;
  fiber_g: string;
  sugar_g: string;
  salt_g: string;
};

function rowToEditDraft(row: IngredientDefault): EditDraft {
  // The row's figures cross the wire as Decimal strings; the draft is what
  // the form edits — the same digits, verbatim.
  const fmt = (v: number | string | null | undefined) =>
    v == null || v === "" ? "" : String(v);
  return {
    calories_kcal: fmt(row.calories_kcal),
    protein_g: fmt(row.protein_g),
    fat_g: fmt(row.fat_g),
    carbs_g: fmt(row.carbs_g),
    fiber_g: fmt(row.fiber_g),
    sugar_g: fmt(row.sugar_g),
    salt_g: fmt(row.salt_g),
  };
}

const PAGE_SIZE = 50;

/** The dictionary as a file: a read, so it stays for every account. */
async function downloadDictionaryCsv(lang: string, t: TranslateFn) {
  try {
    const blob = await recipesApi.exportIngredientDefaults(lang, "csv");
    downloadBlob(blob, `ingredient_defaults_${lang}.csv`);
  } catch (error) {
    toast.error(extractApiError(error, t("ingredient_defaults.error_export")));
  }
}

/**
 * The dictionary's empty state, and the honesty it owes: an empty table
 * with no search running means "no entries in your language yet" — the
 * 83 English and 85 Polish rows do not translate themselves — while an
 * empty table under a search still means "nothing was found".
 */
function EmptyDictionaryState({
  searching,
  languageName,
  importInputRef,
  canWrite,
  onToggleAdd,
  t,
}: {
  searching: boolean;
  languageName: string;
  importInputRef: RefObject<HTMLInputElement | null>;
  canWrite: boolean;
  onToggleAdd: () => void;
  t: TranslateFn;
}) {
  if (searching) {
    return (
      <span className="text-on-muted">{t("ingredient_defaults.empty")}</span>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-on-muted">
        {t("ingredient_defaults.language_empty", { lang: languageName })}
      </p>
      <p className="text-xs text-on-muted">
        {t("ingredient_defaults.language_empty_hint")}
      </p>
      {canWrite && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" onClick={onToggleAdd}>
            {t("recipes:ingredient_defaults.add")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => importInputRef.current?.click()}
          >
            {t("recipes:ingredient_defaults.import")}
          </Button>
        </div>
      )}
    </div>
  );
}

export default function IngredientDefaultsPage() {
  const { t, i18n } = useTranslation("recipes");
  const lang = resolveLang(i18n.language);

  // Reading a label is the vision module asking the nutrition module's
  // questions, behind the permission that reads every photograph. Where any of the three
  // is missing the button is not offered — this screen belongs to recipes and
  // works without either module.
  const { isModuleEnabled } = useModules();
  // The hook is called before the module check, not inside it: a hook behind
  // a `&&` is called on some renders and not others.
  const mayReadLabels = useHasPermission("vision:extract");
  const canScanLabel =
    mayReadLabels && isModuleEnabled("vision") && isModuleEnabled("nutrition");
  // Adding, overriding and importing the dictionary are `recipes:write`'s.
  const canWrite = useCanWrite("recipes");

  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const debouncedQ = useDebounce(q, 400);
  // The empty state's import CTA opens the toolbar's hidden file input —
  // the dialog lives there and the empty state has no input of its own.
  const importInputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, isError, error, refetch } =
    useIngredientDefaultsList({
      lang,
      q: debouncedQ || undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    });

  // A new search starts on the first page: the row being looked for is not
  // on page four of the previous query's results.
  useEffect(() => {
    setPage(1);
  }, [debouncedQ]);

  const createDefault = useCreateIngredientDefault();
  const deleteDefault = useDeleteIngredientDefault();
  const importDefaults = useImportIngredientDefaults();

  // Add form state
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<Partial<IngredientDefaultCreate>>({ lang });

  // Inline edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);

  const startEdit = (row: IngredientDefault) => {
    setEditingId(row.id);
    setEditDraft(rowToEditDraft(row));
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft(null);
  };

  const saveEdit = async (row: IngredientDefault) => {
    if (!editDraft) return;
    if (editDraft.calories_kcal === "") {
      toast.error(t("ingredient_defaults.error_required_fields"));
      return;
    }
    const toNum = (v: string) => (v === "" ? null : Number(v));
    try {
      await createDefault.mutateAsync({
        name: row.name,
        lang,
        calories_kcal: Number(editDraft.calories_kcal),
        protein_g: toNum(editDraft.protein_g),
        fat_g: toNum(editDraft.fat_g),
        carbs_g: toNum(editDraft.carbs_g),
        fiber_g: toNum(editDraft.fiber_g),
        sugar_g: toNum(editDraft.sugar_g),
        salt_g: toNum(editDraft.salt_g),
      });
      toast.success(t("ingredient_defaults.edit_saved", { name: row.name }));
      cancelEdit();
    } catch (error) {
      toast.error(extractApiError(error, t("ingredient_defaults.error_save")));
    }
  };

  const resetOverride = async (row: IngredientDefault) => {
    if (!confirm(t("ingredient_defaults.confirm_delete"))) return;
    try {
      await deleteDefault.mutateAsync(row.id);
      toast.success(
        t("ingredient_defaults.override_reset", { name: row.name }),
      );
    } catch (error) {
      toast.error(
        extractApiError(error, t("ingredient_defaults.error_delete")),
      );
    }
  };

  const handleSearch = (value: string) => {
    setQ(value);
  };

  const handleAdd = async () => {
    if (!form.name || form.calories_kcal == null) {
      toast.error(t("ingredient_defaults.error_required_fields"));
      return;
    }
    try {
      await createDefault.mutateAsync({
        name: form.name,
        lang,
        calories_kcal: Number(form.calories_kcal),
        protein_g: form.protein_g != null ? Number(form.protein_g) : undefined,
        fat_g: form.fat_g != null ? Number(form.fat_g) : undefined,
        carbs_g: form.carbs_g != null ? Number(form.carbs_g) : undefined,
        fiber_g: form.fiber_g != null ? Number(form.fiber_g) : undefined,
        sugar_g: form.sugar_g != null ? Number(form.sugar_g) : undefined,
        salt_g: form.salt_g != null ? Number(form.salt_g) : undefined,
      });
      toast.success(t("ingredient_defaults.added"));
      setShowAdd(false);
      setForm({ lang });
    } catch (error) {
      toast.error(extractApiError(error, t("ingredient_defaults.error_save")));
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await importDefaults.mutateAsync({ file, lang });
      // One counted sentence per tally: one string cannot inflect the
      // words after several different numbers. A new ingredient and an
      // override founded over a system entry are told apart on purpose.
      toast.success(
        [
          t("ingredient_defaults.import_added", { count: result.created }),
          t("ingredient_defaults.import_overridden", {
            count: result.overridden,
          }),
          t("ingredient_defaults.import_updated", { count: result.updated }),
          t("ingredient_defaults.import_unchanged", {
            count: result.unchanged,
          }),
          t("ingredient_defaults.import_errors", { count: result.errors }),
        ].join(", "),
      );
    } catch (error) {
      toast.error(
        extractApiError(error, t("ingredient_defaults.error_import")),
      );
    }
    e.target.value = "";
  };

  const handleExport = () => downloadDictionaryCsv(lang, t);

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1;
  // An export of an empty dictionary is a file with a header in it. The
  // button owes the reader a "nothing to export" instead of handing over
  // the empty artifact without a word.
  const dictionaryIsEmpty = (data?.total ?? 0) === 0;

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      <ReadOnlyNotice module="recipes" />
      {/* Toolbar */}
      <NutritionToolbar
        q={q}
        onSearch={handleSearch}
        onToggleAdd={() => setShowAdd((v) => !v)}
        onImport={handleImport}
        importInputRef={importInputRef}
        onExport={handleExport}
        canWrite={canWrite}
        canExport={!isLoading && !isError && !dictionaryIsEmpty}
        exportHint={
          dictionaryIsEmpty && !isLoading
            ? t("ingredient_defaults.export_empty_hint")
            : undefined
        }
        t={t}
      />

      {/* Add form */}
      {showAdd && (
        <NutritionAddForm
          form={form}
          isPending={createDefault.isPending}
          canScanLabel={canScanLabel}
          onFormChange={setForm}
          onAdd={handleAdd}
          onCancel={() => {
            setShowAdd(false);
            setForm({ lang });
          }}
          t={t}
        />
      )}

      {/* Table */}
      <div className="rounded-xl border border-border bg-surface-card overflow-x-auto">
        <table className="w-full text-sm">
          {/* Every figure in this table shares one denominator, and it was
              written nowhere: "Protein 12" is a number without a measure. */}
          <caption className="caption-top px-4 pt-3 pb-1 text-left text-xs text-on-muted">
            {t("ingredient_defaults.per_100g")}
          </caption>
          <thead>
            <tr className="border-b border-border bg-surface">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide">
                {t("ingredient_defaults.col_name")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide">
                {t("ingredient_defaults.col_kcal")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide hidden sm:table-cell">
                {t("ingredient_defaults.col_protein")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide hidden md:table-cell">
                {t("ingredient_defaults.col_fat")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide hidden md:table-cell">
                {t("ingredient_defaults.col_carbs")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide hidden lg:table-cell">
                {t("ingredient_defaults.col_fiber")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide hidden lg:table-cell">
                {t("ingredient_defaults.col_sugar")}
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide hidden lg:table-cell">
                {t("ingredient_defaults.col_salt")}
              </th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-on-secondary uppercase tracking-wide">
                {t("ingredient_defaults.col_source")}
              </th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isError ? (
              <tr>
                <td colSpan={10}>
                  <QueryFailure error={error} onRetry={() => refetch()} />
                </td>
              </tr>
            ) : isLoading ? (
              <tr>
                <td colSpan={10} className="py-10 text-center text-on-muted">
                  <Loader2 size={20} className="animate-spin mx-auto" />
                </td>
              </tr>
            ) : data?.items.length === 0 ? (
              <tr>
                <td colSpan={10} className="py-10 text-center text-sm">
                  <EmptyDictionaryState
                    searching={Boolean(debouncedQ)}
                    languageName={LANGUAGE_NAMES[lang] ?? lang}
                    importInputRef={importInputRef}
                    canWrite={canWrite}
                    onToggleAdd={() => setShowAdd(true)}
                    t={t}
                  />
                </td>
              </tr>
            ) : (
              data?.items.map((row) => (
                <NutritionTableRow
                  key={row.id}
                  row={row}
                  canWrite={canWrite}
                  isEditing={editingId === row.id}
                  draft={editingId === row.id ? editDraft : null}
                  isPending={createDefault.isPending}
                  onStartEdit={startEdit}
                  onCancelEdit={cancelEdit}
                  onSaveEdit={saveEdit}
                  onResetOverride={resetOverride}
                  onDraftChange={(field, value) =>
                    setEditDraft((d) => (d ? { ...d, [field]: value } : d))
                  }
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm text-on-secondary">
          <span>
            {t("ingredient_defaults.showing", {
              count: data?.items.length ?? 0,
              total: data?.total ?? 0,
            })}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              aria-label={t("common:actions.previous")}
              title={t("common:actions.previous")}
              className="p-1"
            >
              <ChevronLeft size={16} />
            </Button>
            <span className="px-2 font-medium text-on-secondary">
              {page} / {totalPages}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              aria-label={t("common:actions.next")}
              title={t("common:actions.next")}
              className="p-1"
            >
              <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
