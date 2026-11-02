import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import type { CategoryDTO, FieldDefinition } from "@/types";
import {
  getCategoryLabel,
  type LabelTranslate,
} from "@/modules/equipment/components/assetUtils";
import { CONSEQUENCE_STATUSES } from "@/modules/equipment/components/AssetStatusBadge";

const STATUS_LABEL_KEYS: Record<string, string> = {
  AVAILABLE: "status.available",
  DEPLOYED: "status.deployed",
  MAINTENANCE: "status.maintenance",
  RETIRED: "status.retired",
};

/**
 * Options a status select may offer. DEPLOYED/RETIRED are consequences, not
 * choices — they are set by checkout and by the guarded retire action, so the
 * picker must not propose them. A unit already carrying one keeps it as a
 * visible (but not re-selectable once left) option, so the form stays truthful
 * about what it is editing.
 */
function statusOptions(options: string[], current: string): string[] {
  const settable = options.filter(
    (opt) => !(CONSEQUENCE_STATUSES as string[]).includes(opt),
  );
  return current && !settable.includes(current)
    ? [current, ...settable]
    : settable;
}

type DynamicValue =
  string | string[] | boolean | { amount: string; currency: string } | unknown;

interface DynamicFieldProps {
  field: FieldDefinition;
  value: DynamicValue;
  onChange: (v: DynamicValue) => void;
}

function toStr(raw: unknown): string {
  if (raw && typeof raw === "object" && "amount" in raw) {
    return String((raw as { amount?: unknown }).amount ?? "");
  }
  if (Array.isArray(raw)) return raw.join(",");
  if (typeof raw === "boolean") return raw ? "true" : "false";
  return raw == null ? "" : String(raw);
}

function asBool(raw: unknown): boolean {
  if (typeof raw === "boolean") return raw;
  if (typeof raw === "string") return raw === "true" || raw === "1";
  return false;
}

function asMoney(
  raw: unknown,
  fallback: string,
): { amount: string; currency: string } {
  if (raw && typeof raw === "object" && "amount" in raw) {
    const r = raw as { amount?: unknown; currency?: unknown };
    return {
      amount: typeof r.amount === "string" ? r.amount : "",
      currency: typeof r.currency === "string" ? r.currency : fallback,
    };
  }
  return { amount: "", currency: fallback };
}

function asList(raw: unknown): string[] {
  if (Array.isArray(raw))
    return raw.filter((v): v is string => typeof v === "string");
  return [];
}

function camelCaseKey(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

export function DynamicField({ field, value, onChange }: DynamicFieldProps) {
  const { t } = useTranslation("equipment");
  // organization currency fallback for money fields — hoisted
  // because hooks must not sit inside a switch branch.
  const orgCurrency = useOrganizationCurrency();
  const labelId = `dyn-${field.key}`;
  // The persisted label is an English literal — resolve
  // it through i18n when a key exists, keeping the literal as the fallback
  // for org-defined custom fields.
  const labelText = t(`form.fields.${camelCaseKey(field.key)}`, {
    defaultValue: field.label ?? undefined,
  });
  const label = (
    <label
      htmlFor={labelId}
      className="block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide"
    >
      {labelText}
      {field.required && <span className="text-red-500 ml-1">*</span>}
    </label>
  );

  switch (field.type) {
    case "select":
      return (
        <div className="w-full space-y-1.5">
          {label}
          <NativeSelect
            id={labelId}
            value={toStr(value)}
            onChange={(e) => onChange(e.target.value)}
            required={field.required}
          >
            <option value="">
              {field.placeholder ?? t("form.placeholders.select")}
            </option>
            {(field.key === "equipment_status"
              ? statusOptions(field.options ?? [], toStr(value))
              : (field.options ?? [])
            ).map((opt) => (
              <option key={opt} value={opt}>
                {field.key === "equipment_status" && STATUS_LABEL_KEYS[opt]
                  ? t(STATUS_LABEL_KEYS[opt])
                  : opt}
              </option>
            ))}
          </NativeSelect>
        </div>
      );
    case "textarea":
      return (
        <div className="sm:col-span-2 w-full space-y-1.5">
          {label}
          <Textarea
            id={labelId}
            value={toStr(value)}
            onChange={(e) => onChange(e.target.value)}
            required={field.required}
            rows={2}
            placeholder={field.placeholder ?? ""}
            className="w-full rounded-lg border border-border bg-surface-card text-on px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none placeholder:text-on-muted"
          />
        </div>
      );
    case "date":
      return (
        <div className="w-full space-y-1.5">
          {label}
          <DateInput
            id={labelId}
            value={toStr(value)}
            onChange={(e) => onChange(e)}
            required={field.required}
          />
        </div>
      );
    case "number":
      return (
        <div className="w-full space-y-1.5">
          {label}
          <Input
            id={labelId}
            type="number"
            value={toStr(value)}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder ?? ""}
            required={field.required}
          />
        </div>
      );
    case "money": {
      const cur = field.default_currency ?? orgCurrency ?? "USD";
      const v = asMoney(value, cur);
      return (
        <div className="w-full space-y-1.5">
          {label}
          <div className="flex items-stretch gap-2">
            <Input
              wrapperClassName="flex-1"
              id={labelId}
              type="number"
              inputMode="decimal"
              step="any"
              value={v.amount}
              onChange={(e) =>
                onChange({ amount: e.target.value, currency: v.currency })
              }
              placeholder="0.00"
              required={field.required}
            />
            <span
              aria-label={t("common:a11y.currency")}
              className="inline-flex items-center px-3 rounded-lg border border-border bg-surface text-sm font-semibold text-on-secondary"
            >
              {v.currency}
            </span>
          </div>
        </div>
      );
    }
    case "multi-select": {
      const selected = new Set(asList(value));
      const options = field.options ?? [];
      return (
        <div className="sm:col-span-2 w-full space-y-1.5">
          {label}
          <div className="flex flex-wrap gap-2">
            {options.map((opt) => {
              const checked = selected.has(opt);
              return (
                <label
                  key={opt}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-surface-card cursor-pointer hover:bg-surface text-sm"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = new Set(selected);
                      if (checked) next.delete(opt);
                      else next.add(opt);
                      onChange([...next].sort());
                    }}
                    className="rounded border-border"
                  />
                  <span className="text-on-secondary">{opt}</span>
                </label>
              );
            })}
          </div>
        </div>
      );
    }
    case "boolean":
      return (
        <div className="w-full space-y-1.5">
          {label}
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              id={labelId}
              type="checkbox"
              checked={asBool(value)}
              onChange={(e) => onChange(e.target.checked)}
              className="rounded border-border"
            />
            <span className="text-sm text-on-secondary">{t("form.yes")}</span>
          </label>
        </div>
      );
    default:
      return (
        <div className="w-full space-y-1.5">
          {label}
          <Input
            id={labelId}
            value={toStr(value)}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder ?? ""}
            required={field.required}
          />
        </div>
      );
  }
}

interface DynamicFieldsCardProps {
  visibleFields: FieldDefinition[];
  activeCategory: CategoryDTO | undefined;
  formDynamic: Record<string, DynamicValue>;
  onSetDynamic: (key: string, value: DynamicValue) => void;
  t: LabelTranslate;
}

export function DynamicFieldsCard({
  visibleFields,
  activeCategory,
  formDynamic,
  onSetDynamic,
  t,
}: DynamicFieldsCardProps) {
  if (visibleFields.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {activeCategory
            ? getCategoryLabel(t, activeCategory)
            : t("form.sections.details")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {visibleFields.map((field: FieldDefinition) => (
            <DynamicField
              key={field.key}
              field={field}
              value={formDynamic[field.key]}
              onChange={(v) => onSetDynamic(field.key, v)}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
