import { useState } from "react";
import { useTranslation } from "react-i18next";
import { addDays, addYears } from "date-fns";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Checkbox } from "@/module-sdk";
import { Sheet, SheetActions } from "@/components/ui/Sheet";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useApiKeyCapabilities } from "../hooks/useApiKeys";
import { usePermissionLabel } from "@/modules/shared/hooks/permissionLabel";
import { scopeLabel } from "../scopes";
import type { ApiKeyCapabilities } from "../types";
import ApiKeyPermissionList from "./ApiKeyPermissionList";

interface CreateApiKeyModalProps {
  isLoading: boolean;
  onSubmit: (
    name: string,
    expiresAt: string | null,
    scopes: string[],
    permissions: string[],
  ) => void;
  onCancel: () => void;
}

type ExpiryOption = "never" | "30days" | "90days" | "1year";

function computeExpiry(option: ExpiryOption): string | null {
  if (option === "never") return null;
  const now = new Date();
  if (option === "30days") return addDays(now, 30).toISOString();
  if (option === "90days") return addDays(now, 90).toISOString();
  return addYears(now, 1).toISOString();
}

/** What a key of `scope` gets: the scope's permissions the reader may grant. */
function scopePermissions(
  scope: string,
  capabilities: ApiKeyCapabilities,
): string[] {
  const bound =
    capabilities.scopes.find((s) => s.name === scope)?.permissions ?? [];
  return bound.filter((p) => capabilities.grantable.includes(p));
}

/**
 * The permissions an ordinary key will carry, one tick each.
 *
 * Only what the reader may grant is offered — what they hold themselves,
 * minus what no key carries — so the form cannot ask for a key the server
 * would refuse. What no key carries is named underneath, so its absence from
 * the ticks reads as a rule rather than an oversight.
 */
function PermissionPicker({
  capabilities,
  chosen,
  onToggle,
}: {
  capabilities: ApiKeyCapabilities;
  chosen: Set<string>;
  onToggle: (permission: string) => void;
}) {
  const { t } = useTranslation("api_keys");
  const label = usePermissionLabel(capabilities.catalog);
  return (
    <div className="space-y-3">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-on">
          {t("form.permissions")}
        </legend>
        <p className="text-xs text-on-muted">{t("form.permissionsHint")}</p>
        <p className="text-xs text-on-muted">{t("form.readOnlyHint")}</p>
        {capabilities.grantable.map((permission) => (
          <Checkbox
            key={permission}
            id={`api-key-permission-${permission}`}
            label={label(permission)}
            checked={chosen.has(permission)}
            onChange={() => onToggle(permission)}
          />
        ))}
      </fieldset>
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-on">
          {t("capabilities.withheldTitle")}
        </h3>
        <ApiKeyPermissionList
          permissions={capabilities.withheld_permissions}
          catalog={capabilities.catalog}
          withheld
        />
      </div>
    </div>
  );
}

/**
 * What a key of the chosen scope can do, said inside the sheet.
 *
 * A scope this screen was not written for still says what a scope means
 * rather than nothing, and lists the permissions it is bound to.
 */
function ScopeExplanation({
  scope,
  capabilities,
}: {
  scope: string;
  capabilities: ApiKeyCapabilities;
}) {
  const { t } = useTranslation("api_keys");
  return (
    <div
      aria-live="polite"
      className="rounded-lg border border-border bg-surface-raised p-3 space-y-3"
    >
      <p className="text-sm text-on-secondary">
        {scope === "printing"
          ? t("form.scopeExplain.printing")
          : t("form.scopeExplain.other", { scope: scopeLabel(scope, t) })}
      </p>
      <ApiKeyPermissionList
        permissions={scopePermissions(scope, capabilities)}
        catalog={capabilities.catalog}
      />
    </div>
  );
}

export default function CreateApiKeyModal({
  isLoading,
  onSubmit,
  onCancel,
}: CreateApiKeyModalProps) {
  const { t } = useTranslation(["api_keys", "common"]);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<ExpiryOption>("never");
  // "" is an ordinary key — the default, so a key issued without touching the
  // scope field is the kind every key was before scopes existed.
  const [scope, setScope] = useState("");
  // `null` until the reader ticks something: until then the ticks show the
  // default set, read off the server once it has answered.
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const capabilitiesQuery = useApiKeyCapabilities();
  const capabilities = capabilitiesQuery.data;
  const scopes = capabilities?.scopes ?? [];

  const chosen =
    picked ??
    new Set(
      (capabilities?.default_permissions ?? []).filter((p) =>
        capabilities?.grantable.includes(p),
      ),
    );
  const permissions = !capabilities
    ? []
    : scope
      ? scopePermissions(scope, capabilities)
      : [...chosen].sort();

  const toggle = (permission: string) => {
    const next = new Set(chosen);
    if (next.has(permission)) next.delete(permission);
    else next.add(permission);
    setPicked(next);
  };

  // Not before the server has said what may be granted: a key issued blind
  // would carry whatever the default happens to be.
  const canSubmit = !!name.trim() && !!capabilities && permissions.length > 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(
      name.trim(),
      computeExpiry(expiry),
      scope ? [scope] : [],
      permissions,
    );
  };

  return (
    <Sheet open onClose={onCancel} aria-label={t("form.title")}>
      <form
        className="flex flex-col flex-1 overflow-hidden"
        onSubmit={handleSubmit}
      >
        <div className="p-6 space-y-4 flex-1 overflow-y-auto">
          <h2 className="text-lg font-semibold text-on">{t("form.title")}</h2>

          <Input
            id="api-key-name"
            label={t("common:form.name")}
            placeholder={t("form.namePlaceholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />

          {/* `label` on the control: the loose <label> above it had no
              `htmlFor`, so the only list on this form was nameless. */}
          <NativeSelect
            label={t("form.expiration")}
            value={expiry}
            onChange={(e) => setExpiry(e.target.value as ExpiryOption)}
          >
            <option value="never">{t("form.expirationOptions.never")}</option>
            <option value="30days">{t("form.expirationOptions.30days")}</option>
            <option value="90days">{t("form.expirationOptions.90days")}</option>
            <option value="1year">{t("form.expirationOptions.1year")}</option>
          </NativeSelect>

          {/* Without the server's answer the sheet cannot say what a key
              may carry, so it says that, offers to read again, and issues
              nothing in the meantime. */}
          {capabilitiesQuery.isError && (
            <QueryFailure
              error={capabilitiesQuery.error}
              onRetry={() => void capabilitiesQuery.refetch()}
              message={t("form.scopesLoadFailed")}
            />
          )}

          {scopes.length > 0 && (
            <NativeSelect
              label={t("form.scope")}
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="">{t("form.scopeOptions.everything")}</option>
              {scopes.map(({ name: scopeName }) => (
                <option key={scopeName} value={scopeName}>
                  {scopeLabel(scopeName, t)}
                </option>
              ))}
            </NativeSelect>
          )}

          {capabilities &&
            (scope ? (
              <ScopeExplanation scope={scope} capabilities={capabilities} />
            ) : (
              <PermissionPicker
                capabilities={capabilities}
                chosen={chosen}
                onToggle={toggle}
              />
            ))}
        </div>

        <SheetActions className="px-6 pb-6">
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("common:form.cancel")}
          </Button>
          <Button type="submit" isLoading={isLoading} disabled={!canSubmit}>
            {t("form.generate")}
          </Button>
        </SheetActions>
      </form>
    </Sheet>
  );
}
