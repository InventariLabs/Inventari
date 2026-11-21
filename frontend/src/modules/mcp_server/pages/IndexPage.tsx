import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Card, useHasPermission, useModulePageHeader } from "@/module-sdk";

/** The path an MCP client posts to; the module serves it from its router. */
const ENDPOINT_PATH = "/api/v1/mcp-server/mcp";

export default function IndexPage() {
  const { t } = useTranslation("mcp_server");
  const { setHeader } = useModulePageHeader();
  // A key is made on a settings screen gated by this permission. Offering
  // the link to an account that cannot open it sends the reader to a refusal
  // the page could have named instead.
  const canOpenApiKeys = useHasPermission("org:settings:write");
  // A client is configured with a whole address, not a path: the reader
  // copies this line into a command that cannot infer the origin.
  const endpoint = `${window.location.origin}${ENDPOINT_PATH}`;

  useEffect(() => {
    setHeader({ title: t("title"), subtitle: t("subtitle") });
  }, [t, setHeader]);

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-muted-foreground">
        {t("description")}
      </p>

      <Card className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-on-secondary">
          {t("endpoint.label")}
        </p>
        {/* Scrolls sideways rather than wrapping: an address is copied as one
            string, and a wrap at a slash or at a hyphen inside a segment
            hands the reader something that does not work. The same block the
            API-key dialog uses for a value that is copied. */}
        <code className="mt-1 block overflow-x-auto whitespace-nowrap rounded-lg bg-surface-raised px-3 py-2 text-sm text-on">
          {endpoint}
        </code>
        <p className="mt-2 text-xs text-on-muted">{t("endpoint.hint")}</p>
        <p className="mt-1 text-xs text-on-muted">{t("endpoint.protocol")}</p>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-semibold text-on">{t("connect.title")}</h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-on">
          <li>
            {canOpenApiKeys
              ? t("connect.createKey")
              : t("connect.createKeyNeedsAdmin")}
          </li>
          <li>{t("connect.pointClient")}</li>
          <li>{t("connect.allowHost")}</li>
        </ol>
      </Card>

      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {canOpenApiKeys && (
          <Link
            to="/settings/api-keys"
            className="text-sm font-medium text-primary-700 hover:underline"
          >
            {t("links.apiKeys")}
          </Link>
        )}
        <Link
          to="/settings/modules/mcp_server"
          className="text-sm font-medium text-primary-700 hover:underline"
        >
          {t("settings.open")}
        </Link>
      </div>
    </div>
  );
}
