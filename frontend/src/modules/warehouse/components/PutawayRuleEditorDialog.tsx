import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import type { CatalogueSearchResult } from "@/modules/warehouse/api/documents";
import { useLocationsById } from "@/module-sdk";
import { LocationField } from "@/modules/warehouse/components/LocationField";
import { useCanWrite } from "@/hooks/useCanWrite";
import { usePutawayTargetStates } from "@/modules/warehouse/hooks/usePutawayTargetStates";
import type { PutawayTargetState } from "@/modules/warehouse/hooks/usePutawayTargetStates";
import { formatQuantityLocale } from "@/utils/formatters";
import type { TranslateFn } from "@/types/i18n";
import {
  ShelfSettingsSheet,
  type ShelfSettingsTarget,
} from "./ShelfSettingsSheet";
import { PutawayMatchFields } from "./PutawayMatchFields";
import type {
  PutawayRule,
  PutawayRuleCreate,
  PutawayRuleUpdate,
} from "@/modules/warehouse/api/putaway";

interface PutawayRuleEditorDialogProps {
  open: boolean;
  /** When set, the dialog edits an existing rule; otherwise creates a new one. */
  rule?: PutawayRule | null;
  onClose: () => void;
  onSubmit: (data: PutawayRuleCreate | PutawayRuleUpdate) => void;
  isPending: boolean;
  /** server-side rejection (e.g. unknown context tag, 400) rendered
   * inside the dialog so the failure is visible next to the form. */
  serverError?: string | null;
}

interface FormState {
  product_template_id: string;
  category_id: string;
  context_tag: string;
  location_type_code: string;
  /** The rule's shelves in walking order — the resolver tries them one by
   *  one, first fit wins, so the order is the policy. */
  location_ids: string[];
  priority: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  product_template_id: "",
  category_id: "",
  context_tag: "",
  location_type_code: "",
  location_ids: [],
  priority: "100",
  is_active: true,
};

type TargetOption = ShelfSettingsTarget & { path?: string };

/** What a target says about its limit, from the shared fill read. */
function targetSummary(
  state: PutawayTargetState,
  forProduct: boolean,
  t: TranslateFn,
): { text: string; limited: boolean } {
  const mix = state.singleProduct
    ? t("putaway.targets.single")
    : t("putaway.targets.mixed");
  if (forProduct) {
    if (!state.limit) {
      return {
        text: `${t("putaway.locations.limits.none")} · ${mix}`,
        limited: false,
      };
    }
    const unit = state.limit.unit ? ` ${state.limit.unit}` : "";
    const pair = `${formatQuantityLocale(state.used ?? "0")} / ${formatQuantityLocale(state.limit.max)}${unit}`;
    const gloss =
      state.status === "over"
        ? t("putaway.targets.over")
        : state.status === "nearly_full"
          ? t("putaway.targets.nearlyFull")
          : null;
    return { text: gloss ? `${pair} — ${gloss}` : pair, limited: true };
  }
  const limits =
    state.limitCount === 0
      ? t("putaway.locations.limits.none")
      : t("putaway.locations.limits.count", { count: state.limitCount });
  return { text: `${limits} · ${mix}`, limited: state.limitCount > 0 };
}

/**
 * The chosen shelves in walking order, each movable or removable, with what
 * each holds and a way to its settings. Rendered only while the editor is
 * open, so the reads behind it are not made for a closed dialog.
 */
function TargetLocationList({
  ids,
  options,
  productTemplateId,
  canSetLimits,
  onOpenSettings,
  onChange,
}: {
  ids: string[];
  options: TargetOption[];
  /** The rule's product, when it matches one; its limit is the one shown. */
  productTemplateId: string | null;
  canSetLimits: boolean;
  onOpenSettings: (target: TargetOption) => void;
  onChange: (ids: string[]) => void;
}) {
  const { t } = useTranslation("warehouse");
  const { stateByLocation, isError, error, refetch } = usePutawayTargetStates(
    ids,
    productTemplateId,
  );
  if (ids.length === 0) return null;
  const swap = (a: number, b: number) => {
    const next = [...ids];
    [next[a], next[b]] = [next[b], next[a]];
    onChange(next);
  };
  const forProduct = productTemplateId !== null;
  const summaries = ids.map((id) => {
    const state = stateByLocation.get(id);
    return state ? targetSummary(state, forProduct, t) : null;
  });
  const first = stateByLocation.get(ids[0]);
  const firstIsTight =
    first?.status === "nearly_full" || first?.status === "over";
  const lastIsOpen = summaries[ids.length - 1]?.limited === false;
  return (
    <>
      {isError && <InlineQueryError error={error} onRetry={refetch} />}
      <ol className="space-y-1">
        {ids.map((id, index) => {
          const option = options.find((o) => o.id === id);
          const name = option?.name ?? id;
          const summary = summaries[index];
          return (
            <li
              key={id}
              className="flex flex-wrap items-center gap-x-2 rounded-lg border border-border px-3 py-1.5 text-sm"
            >
              <span className="text-xs text-on-muted">{index + 1}.</span>
              <span className="min-w-0 flex-1 truncate text-on">{name}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("putaway.actions.moveUp", "Move up")}
                disabled={index === 0}
                onClick={() => swap(index - 1, index)}
              >
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("putaway.actions.moveDown", "Move down")}
                disabled={index === ids.length - 1}
                onClick={() => swap(index, index + 1)}
              >
                <ArrowDown className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("putaway.actions.removeLocation", {
                  defaultValue: "Remove {{name}}",
                  name,
                })}
                onClick={() => onChange(ids.filter((x) => x !== id))}
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
              {summary && (
                <div className="flex basis-full items-center justify-between gap-2 pl-6">
                  <span className="min-w-0 text-xs text-on-secondary tabular-nums">
                    {summary.text}
                  </span>
                  {canSetLimits && option && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={t("putaway.targets.setAria", { name })}
                      onClick={() => onOpenSettings(option)}
                    >
                      {summary.limited
                        ? t("putaway.targets.set")
                        : t("putaway.targets.setLimit")}
                    </Button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {firstIsTight && (
        <p className="text-xs text-on-secondary">
          {ids.length > 1
            ? t("putaway.targets.noteNext")
            : t("putaway.targets.noteOnly")}
          {ids.length > 1 &&
            lastIsOpen &&
            ` ${t("putaway.targets.noteLastOpen")}`}
        </p>
      )}
    </>
  );
}

/**
 * Modal editor for a single putaway rule. At least one match key
 * (product template / category / context tag / storage type) must be set.
 */
export function PutawayRuleEditorDialog({
  open,
  rule,
  onClose,
  onSubmit,
  isPending,
  serverError = null,
}: PutawayRuleEditorDialogProps) {
  const { t } = useTranslation("warehouse");
  // The target picker follows the same policy as every general list: a rule
  // routing goods into a module's location is the module's workflow.
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [selectedTemplate, setSelectedTemplate] =
    useState<CatalogueSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsTarget, setSettingsTarget] =
    useState<ShelfSettingsTarget | null>(null);
  const canWrite = useCanWrite("warehouse");
  const canWriteStorages = useCanWrite("locations");

  useEffect(() => {
    if (!open) return;
    setSelectedTemplate(null);
    if (rule) {
      setForm({
        product_template_id: rule.product_template_id ?? "",
        category_id: rule.category_id ?? "",
        context_tag: rule.context_tag ?? "",
        location_type_code: rule.location_type_code ?? "",
        location_ids:
          rule.locations?.map((l) => l.location_id) ??
          (rule.target_location_id ? [rule.target_location_id] : []),
        priority: String(rule.priority),
        is_active: rule.is_active,
      });
      const templateId = rule.product_template_id;
      if (templateId) {
        let cancelled = false;
        productTemplatesApi
          .get(templateId)
          .then((tpl) => {
            if (cancelled) return;
            setSelectedTemplate({
              product_template_id: tpl.id,
              name: tpl.name,
              // The schema keeps these optional-nullable; the working shape
              // wants them settled.
              sku: tpl.sku ?? null,
              barcode: tpl.barcode ?? null,
              brand: tpl.brand ?? null,
              uom_id: tpl.uom_id ?? null,
              uom_symbol: null,
              image_url: tpl.image_url ?? null,
              is_stub: false,
            });
          })
          .catch(() => {
            // Template may have been deleted; keep the raw id in form state.
          });
        return () => {
          cancelled = true;
        };
      }
    } else {
      setForm(EMPTY_FORM);
    }
    setError(null);
  }, [open, rule]);

  // The shelves the rule already aims at are named by id; the picker below
  // searches the rest on the server. Every level is a legal target (the model
  // points at `storage_locations.id`), warehouses included, so the search is
  // not narrowed to shelves.
  const { byId: targetPlaces } = useLocationsById(form.location_ids);
  const locationOptions: TargetOption[] = useMemo(() => {
    // A shelf the rule already names carries its own name; one just picked is
    // named by the server's answer.
    const ruleNames = new Map(
      (rule?.locations ?? []).map((l) => [l.location_id, l.location_name]),
    );
    return form.location_ids.flatMap((id) => {
      const place = targetPlaces.get(id);
      const name = place?.name ?? ruleNames.get(id);
      if (!name) return [];
      return [
        {
          id,
          name,
          sequence: place?.sequence ?? null,
          full_path: place?.full_path ?? null,
        },
      ];
    });
  }, [form.location_ids, targetPlaces, rule]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  // The server refuses a rule with no match key (`_validate_match_keys`), so
  // the form does not offer one: a Create button that leads to a 400 makes
  // the reader earn the refusal by pressing it.
  const hasMatchKey = Boolean(
    form.product_template_id.trim() ||
    form.category_id.trim() ||
    form.context_tag.trim() ||
    form.location_type_code.trim(),
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (form.location_ids.length === 0) {
      setError(
        t("putaway.errors.target_required", "Target location is required"),
      );
      return;
    }
    if (!hasMatchKey) {
      setError(
        t(
          "putaway.errors.match_key_required",
          "At least one match key is required",
        ),
      );
      return;
    }
    const priorityNum = Number(form.priority);
    if (Number.isNaN(priorityNum) || priorityNum < 0) {
      setError(
        t(
          "putaway.errors.priority_invalid",
          "Priority must be a non-negative number",
        ),
      );
      return;
    }

    const data: PutawayRuleCreate | PutawayRuleUpdate = {
      product_template_id: form.product_template_id.trim() || null,
      category_id: form.category_id.trim() || null,
      context_tag: form.context_tag.trim() || null,
      location_type_code: form.location_type_code.trim() || null,
      location_ids: form.location_ids,
      priority: priorityNum,
      is_active: form.is_active,
    };
    onSubmit(data);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      {/* A 568px-tall phone showed this dialog 814px tall, centred, with no
          scrolling of its own: the close button sat above the screen and
          Create/Cancel below it, and the only exit was a page reload. The
          cap keeps the frame inside the viewport; the field body is the one
          scroll owner, so the frame's exits can never be scrolled away
          (ModelEditModal is the sibling that established the shape). */}
      <DialogContent className="inset-0 m-auto h-fit !transform-none sm:max-w-lg max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>
            {rule
              ? t("putaway.edit_title", "Edit Putaway Rule")
              : t("putaway.create_title", "New Putaway Rule")}
          </DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
            <PutawayMatchFields
              form={form}
              set={set}
              selectedTemplate={selectedTemplate}
              onTemplateChange={setSelectedTemplate}
            />

            <div className="space-y-1.5">
              {/* One picker, many shelves: choosing appends to the list.
                  The order below is the walking order, and a reader can
                  move a shelf up or down or take it off entirely. */}
              <LocationField
                label={t("putaway.fields.target_location", "Target locations")}
                title={t("putaway.fields.target_location", "Target locations")}
                scope={{ purpose: "general" }}
                except={form.location_ids}
                value=""
                onChange={(id) => {
                  if (!id) return;
                  set("location_ids", [...form.location_ids, id]);
                }}
                placeholder={t(
                  "putaway.placeholders.target_location",
                  "Select target location",
                )}
                searchPlaceholder={t("common:actions.search", "Search")}
              />
              <TargetLocationList
                ids={form.location_ids}
                options={locationOptions}
                productTemplateId={form.product_template_id.trim() || null}
                canSetLimits={canWrite}
                onOpenSettings={setSettingsTarget}
                onChange={(ids) => set("location_ids", ids)}
              />
              <p className="text-xs text-on-secondary">
                {t(
                  "putaway.hints.location_order",
                  "Goods go to the first shelf they fit; full shelves hand the line to the next one.",
                )}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                {/* The shared control owns the label wiring: the hand-rolled
                    `<label>` here had no `htmlFor`, so the field was announced
                    as a spinbutton with no name and clicking the word did
                    nothing. */}
                <Input
                  label={t("putaway.fields.priority", "Priority")}
                  type="number"
                  min={0}
                  value={form.priority}
                  onChange={(e) => set("priority", e.target.value)}
                />
                <p className="text-xs text-on-secondary">
                  {t(
                    "putaway.hints.priority",
                    "Lower number = higher priority",
                  )}
                  {". "}
                  {t(
                    "putaway.hints.priority_scope",
                    "Priority only decides between rules of the same specificity.",
                  )}
                </p>
              </div>
              <div className="flex items-end pb-6">
                {/* The shared control owns the label wiring and the focus ring
             a hand-rolled `<input type="checkbox">` did not. */}
                <Checkbox
                  checked={form.is_active}
                  onChange={(e) => set("is_active", e.target.checked)}
                  label={t("putaway.fields.active", "Active")}
                />
              </div>
            </div>
          </div>

          {(error || serverError) && (
            <p className="shrink-0 text-sm text-on-danger" role="alert">
              {error ?? serverError}
            </p>
          )}
          {/* The disabled Create is not a dead end: the sentence says what
              is missing, in the same words the refusal would have used. */}
          {!hasMatchKey && !error && !serverError && (
            <p className="shrink-0 text-xs text-on-secondary">
              {t(
                "putaway.errors.match_key_required",
                "At least one match key is required",
              )}
            </p>
          )}

          <DialogFooter className="shrink-0">
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={isPending || !hasMatchKey}>
              {rule
                ? t("common:actions.save", "Save")
                : t("putaway.actions.create", "Create Rule")}
            </Button>
          </DialogFooter>
        </form>
        {/* A sheet opened from inside a dialog (the pattern the shared
            combobox uses on a phone). Its `fixed` frame is placed against
            the viewport only while no ancestor carries a transform, which is
            why this dialog is centred with `inset-0 m-auto` rather than the
            default translate. */}
        {settingsTarget && (
          <ShelfSettingsSheet
            location={settingsTarget}
            canWrite={canWrite}
            canWriteStorages={canWriteStorages}
            zIndex="modal-nested"
            onClose={() => setSettingsTarget(null)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
