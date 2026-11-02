import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { copyTextOrExplain } from "@/lib/clipboard";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useApiKeyCapabilities } from "../hooks/useApiKeys";
import ApiKeyPermissionList from "./ApiKeyPermissionList";

/**
 * What a key may carry, and how to send it.
 *
 * Each key carries the permissions chosen when it was issued, so the card
 * says how that choice works and what no key may ever hold; each key's own
 * list stands beside it in the table. The header and the example name the
 * key's own header, and the reader is told the Bearer form is on its way out.
 *
 * Everything here is read from `/api-keys/capabilities`, which reports the
 * constants the authentication path uses. A sentence typed on this screen
 * would drift; a reading cannot. When the reading fails the card says so and
 * offers to read again: an empty space there read as "nothing to say".
 */
export default function ApiKeyCapabilitiesCard() {
  const { t } = useTranslation("api_keys");
  const {
    data: capabilities,
    error,
    isError,
    refetch,
  } = useApiKeyCapabilities();

  if (isError) {
    return (
      <Card>
        <QueryFailure
          error={error}
          onRetry={() => void refetch()}
          message={t("capabilities.loadFailed")}
        />
      </Card>
    );
  }
  if (!capabilities) return null;

  const example = [
    "curl -H '",
    capabilities.header,
    ": inv_live_…' \\\n  ",
    window.location.origin,
    "/api/v1/items",
  ].join("");

  const copyExample = async () => {
    if (await copyTextOrExplain(example, t("common:copy.failed"))) {
      toast.success(t("usage.copied"));
    }
  };

  return (
    <Card className="p-4 space-y-4">
      <div className="space-y-2">
        <h2 className="text-sm font-semibold text-on">
          {t("capabilities.title")}
        </h2>
        <p className="text-xs text-on-muted">{t("capabilities.intro")}</p>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-on">
          {t("capabilities.withheldTitle")}
        </h3>
        <ApiKeyPermissionList
          permissions={capabilities.withheld_permissions}
          catalog={capabilities.catalog}
          withheld
        />
        {capabilities.admin_areas_blocked && (
          <p className="text-xs text-on-muted">
            {t("capabilities.adminBlocked")}
          </p>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-on">{t("usage.title")}</h3>
        <p className="text-xs text-on-muted">
          {t("usage.hint", { header: capabilities.header })}
        </p>
        <pre className="text-xs bg-surface-raised rounded-lg p-3 overflow-x-auto font-mono text-on-secondary whitespace-pre">
          {example}
        </pre>
        <Button
          variant="secondary"
          size="sm"
          leftIcon={<Copy size={14} />}
          onClick={copyExample}
        >
          {t("usage.copy")}
        </Button>
      </div>
    </Card>
  );
}
