import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useHasPermission } from "@/hooks/useHasPermission";
import { usePageSavePart, useUnderPageSave } from "@/module-sdk";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { useUpdateModuleSettings } from "@/modules/settings/hooks/useModuleSettings";
import type {
  ModuleSettingsField,
  ModuleSettingsSchema,
} from "@/lib/api/modules";

const MASKED_VALUE = "**********";

interface ModuleSettingsFormProps {
  moduleName: string;
  schema: ModuleSettingsSchema;
  initialValues: Record<string, unknown>;
}

type FormState = Record<string, unknown>;

function cloneValue(value: unknown): unknown {
  if (value === undefined || value === null) return value;
  return JSON.parse(JSON.stringify(value));
}

function applyDefaults(
  properties: Record<string, ModuleSettingsField>,
  prefix = "",
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(properties)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (field.type === "object" && field.properties) {
      Object.assign(out, applyDefaults(field.properties, path));
    } else if ("default" in field) {
      out[path] = cloneValue(field.default);
    }
  }
  return out;
}

/**
 * Form state is keyed by dotted path; the API speaks the schema's own shape.
 * These two translate between them — without that, a nested field like
 * `jina.api_key` was sent as the literal key `"jina.api_key"`, which the
 * backend rejects with 400 against `additionalProperties: false`, and a stored
 * value never reached the input because it arrived nested.
 */
function readPath(source: unknown, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (acc, segment) =>
        acc && typeof acc === "object"
          ? (acc as Record<string, unknown>)[segment]
          : undefined,
      source,
    );
}

function toSchemaShape(flat: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [path, value] of Object.entries(flat)) {
    const segments = path.split(".");
    let cursor = out;
    for (const segment of segments.slice(0, -1)) {
      if (typeof cursor[segment] !== "object" || cursor[segment] === null) {
        cursor[segment] = {};
      }
      cursor = cursor[segment] as Record<string, unknown>;
    }
    cursor[segments[segments.length - 1]] = value;
  }
  return out;
}

/**
 * The sentence for a number outside the schema's bounds, or null.
 *
 * The browser's own bubble answers in the browser's language, not the app's,
 * so the form switches it off (`noValidate`) and says the same thing itself —
 * for the bounds and for the whole-number check `noValidate` takes away too.
 */
function rangeError(
  field: ModuleSettingsField,
  value: unknown,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | null {
  const isNumber = field.type === "integer" || field.type === "number";
  if (!isNumber || typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  if (field.type === "integer" && !Number.isInteger(value)) {
    return t("settings.moduleSettings.notWholeNumber");
  }
  const { minimum: min, maximum: max } = field;
  const below = min !== undefined && value < min;
  const above = max !== undefined && value > max;
  if (!below && !above) return null;
  if (min !== undefined && max !== undefined) {
    return t("settings.moduleSettings.outOfRangeBetween", { min, max });
  }
  return below
    ? t("settings.moduleSettings.outOfRangeMin", { min })
    : t("settings.moduleSettings.outOfRangeMax", { max });
}

function isMasked(value: unknown): boolean {
  return typeof value === "string" && value === MASKED_VALUE;
}

export function ModuleSettingsForm({
  moduleName,
  schema,
  initialValues,
}: ModuleSettingsFormProps) {
  const { t } = useTranslation("common");
  // A module's settings decide what the module may do, and the endpoint that
  // saves them is `get_current_admin_user`. The settings screens are reached
  // under the admin-gated shell; this is the same rule where the form can
  // state it, so the form cannot be mounted without it.
  const canManageSettings = useHasPermission("admin:access");
  const enabledModules = useEnabledModulesOptional();
  // Under a page that has one Save the form hands its edit to it, and keeps
  // neither its own button nor its own confirmation.
  const underPageSave = useUnderPageSave();
  const mutation = useUpdateModuleSettings(moduleName, {
    quiet: underPageSave,
  });
  const fields = useMemo(() => {
    const list: Array<{ path: string; field: ModuleSettingsField }> = [];
    function walk(props: Record<string, ModuleSettingsField>, prefix: string) {
      for (const [key, field] of Object.entries(props)) {
        const path = prefix ? `${prefix}.${key}` : key;
        if (field.type === "object" && field.properties) {
          walk(field.properties, path);
        } else if (
          field.requires_modules?.every((m) => enabledModules.includes(m)) ??
          true
        ) {
          // A setting about another module's concept is not offered where
          // that module is off: switching it on would promise records in a
          // register the organization cannot open.
          list.push({ path, field });
        }
      }
    }
    walk(schema.properties ?? {}, "");
    return list;
  }, [schema, enabledModules]);

  const flattenInitial = useMemo(() => {
    const flat: FormState = applyDefaults(schema.properties ?? {});
    for (const { path } of fields) {
      const stored = readPath(initialValues, path);
      if (stored !== undefined) flat[path] = stored;
    }
    return flat;
  }, [fields, schema, initialValues]);

  const [values, setValues] = useState<FormState>(flattenInitial);
  // What `values` is compared with to know an edit is waiting. It moves in the
  // same step as `values` when the stored settings change, so a refetch is
  // never read as an edit for the one render in between.
  const [baseline, setBaseline] = useState<FormState>(flattenInitial);
  const [secretEdited, setSecretEdited] = useState<Set<string>>(new Set());

  useEffect(() => {
    setValues(flattenInitial);
    setBaseline(flattenInitial);
    setSecretEdited(new Set());
  }, [moduleName, flattenInitial]);

  function updateField(path: string, value: unknown, isSecret: boolean) {
    setValues((prev) => ({ ...prev, [path]: value }));
    if (isSecret) {
      setSecretEdited((prev) => {
        const next = new Set(prev);
        next.add(path);
        return next;
      });
    }
  }

  function buildPayload(): FormState {
    const payload: FormState = {};
    for (const { path } of fields) {
      const raw = values[path];
      const edited = secretEdited.has(path);
      if (edited && (raw === "" || raw === undefined || raw === null)) {
        continue;
      }
      if (isMasked(raw) && !edited) {
        continue;
      }
      payload[path] = raw;
    }
    return toSchemaShape(payload);
  }

  const hasOutOfRange = fields.some(
    ({ path, field }) => rangeError(field, values[path], t) !== null,
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (hasOutOfRange) return;
    // `mutate`, not `mutateAsync`: only `mutate` carries the factory's error
    // toast, and nothing here waits for the result.
    mutation.mutate(buildPayload());
  }

  const dirty =
    secretEdited.size > 0 ||
    fields.some(
      ({ path }) =>
        JSON.stringify(values[path]) !== JSON.stringify(baseline[path]),
    );
  usePageSavePart(`moduleSettings:${moduleName}`, dirty, async () => {
    if (hasOutOfRange) {
      throw new Error(t("settings.moduleSettings.outOfRangeSave"));
    }
    await mutation.mutateAsync(buildPayload());
  });

  if (!canManageSettings) {
    return (
      <ReadOnlyNotice
        module={moduleName}
        permission="admin:access"
        right="manage"
      />
    );
  }

  if (fields.length === 0) {
    return (
      <EmptyState
        title={t("settings.moduleSettings.empty", "No configurable settings")}
        description={t(
          "settings.moduleSettings.emptyHint",
          "This module has no settings declared yet.",
        )}
      />
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {fields.map(({ path, field }) => (
        <FieldRow
          key={path}
          path={path}
          field={field}
          value={values[path]}
          onChange={(v) => updateField(path, v, field.format === "secret")}
        />
      ))}
      {!underPageSave && (
        <div className="flex justify-end pt-2">
          <Button
            type="submit"
            isLoading={mutation.isPending}
            leftIcon={<Save size={16} />}
          >
            {t("common:actions.save", "Save")}
          </Button>
        </div>
      )}
    </form>
  );
}

interface FieldRowProps {
  path: string;
  field: ModuleSettingsField;
  value: unknown;
  onChange: (value: unknown) => void;
}

function FieldRow({ path, field, value, onChange }: FieldRowProps) {
  const { t } = useTranslation("common");
  // schema-provided i18n keys win; literals are the fallback so
  // modules without keys keep rendering exactly as before.
  const label =
    (field.title_key &&
      t(field.title_key, {
        defaultValue: field.title ?? prettifyPath(path),
      })) ||
    field.title ||
    prettifyPath(path);
  const description =
    (field.description_key &&
      t(field.description_key, { defaultValue: field.description })) ||
    field.description;
  const isSecret = field.format === "secret";

  if (field.enum) {
    return (
      <Card className="p-4">
        <NativeSelect
          label={label}
          description={description}
          data-testid={`field-${path}`}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          {field.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </NativeSelect>
      </Card>
    );
  }

  if (field.type === "boolean") {
    return (
      <Card className="p-4 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-on">{label}</p>
          {description && (
            <p className="text-xs text-on-muted mt-0.5">{description}</p>
          )}
        </div>
        {/* The label is the target, not the square: at 390px this
            checkbox measured 13x20 — a 20px box squeezed by the row beside it —
            and a thumb that lands next to a bare square hits the card and
            nothing happens. The square keeps its size, the label carries the
            44px floor, and it is what gives the field its name. */}
        <label className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center">
          <input
            data-testid={`field-${path}`}
            type="checkbox"
            className="h-6 w-6 md:h-5 md:w-5"
            checked={Boolean(value)}
            aria-label={label}
            onChange={(e) => onChange(e.target.checked)}
          />
        </label>
      </Card>
    );
  }

  if (isSecret) {
    // A stored secret comes back masked, and an input cannot show it. Say so —
    // the same placeholder for "stored" and "never set" left the user guessing
    // whether their key had been saved at all.
    const placeholder = isMasked(value)
      ? t("settings.moduleSettings.secretStored")
      : t("settings.moduleSettings.secretUnset");
    return (
      <Card className="p-4">
        <Input
          label={label}
          description={description}
          data-testid={`field-${path}`}
          type="password"
          autoComplete="new-password"
          placeholder={placeholder}
          value={typeof value === "string" && !isMasked(value) ? value : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </Card>
    );
  }

  const inputType =
    field.type === "integer" || field.type === "number" ? "number" : "text";
  return (
    <Card className="p-4">
      <Input
        label={label}
        description={description}
        data-testid={`field-${path}`}
        type={inputType}
        min={field.minimum}
        max={field.maximum}
        error={rangeError(field, value, t) ?? undefined}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) =>
          onChange(
            inputType === "number" && e.target.value !== ""
              ? Number(e.target.value)
              : e.target.value,
          )
        }
      />
    </Card>
  );
}

function prettifyPath(path: string): string {
  const last = path.split(".").pop() ?? path;
  return last
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/^./, (s) => s.toUpperCase());
}
