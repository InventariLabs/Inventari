import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { isKeyExpired } from "../expiry";
import { useApiKeyCapabilities } from "../hooks/useApiKeys";
import { usePermissionLabel } from "@/modules/shared/hooks/permissionLabel";
import { scopeLabel } from "../scopes";
import type { ApiKey } from "../types";

/** What sets a key apart beside its name: the scopes it is confined to, and whether it has expired. */
export function ApiKeyBadges({ apiKey }: { apiKey: ApiKey }) {
  const { t } = useTranslation("api_keys");
  return (
    <>
      {apiKey.scopes.map((scope) => (
        <Badge key={scope} variant="info" className="shrink-0">
          {scopeLabel(scope, t)}
        </Badge>
      ))}
      {isKeyExpired(apiKey.expires_at) && (
        <Badge variant="secondary" className="shrink-0">
          {t("table.expired")}
        </Badge>
      )}
    </>
  );
}

/**
 * What a listed key may do, in words: read off the key itself.
 *
 * The labels come from the capabilities answer the page's card already
 * holds, so every row asks the cache, not the server.
 */
export function ApiKeyPermissionsLine({
  apiKey,
  titled = false,
}: {
  apiKey: ApiKey;
  /** A phone's card has no column header, so the line names itself. */
  titled?: boolean;
}) {
  const { t } = useTranslation("api_keys");
  const { data: capabilities } = useApiKeyCapabilities();
  const label = usePermissionLabel(capabilities?.catalog);
  const line = (
    <span className="text-xs text-on-secondary">
      {apiKey.permissions.length > 0
        ? apiKey.permissions.map(label).join(", ")
        : t("table.noPermissions")}
    </span>
  );
  if (!titled) return line;
  return (
    <div>
      <p className="font-medium text-on-muted uppercase tracking-wide text-[10px] mb-0.5">
        {t("table.permissions")}
      </p>
      {line}
    </div>
  );
}
