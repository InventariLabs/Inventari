import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { queryKeys } from "@/hooks/queries/keys";
import { aboutApi } from "@/lib/api/about";
import { USER_GUIDE_URL } from "@/lib/userGuide";
import { webLinkOrNull } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { QueryFailure } from "@/components/ui/QueryResult";

/** The copyright line of NOTICE; a name and years, not a sentence to translate. */
const COPYRIGHT = "Copyright © 2026 Jerzy Piątek";

const ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/";

function OutLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-sm font-medium text-primary-700 hover:underline dark:text-primary-500"
    >
      {children}
      <ExternalLink size={14} aria-hidden="true" />
    </a>
  );
}

/**
 * About — /settings/about, open to every member.
 *
 * The legal notices AGPL-3.0 §5(d) asks an interactive interface to show,
 * and the offer of source §13 asks of a version served over a network. The
 * version and the source link come from the server, so an installation
 * running a fork points the link at its own repository by configuration.
 */
export default function SettingsAboutSection() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();
  const about = useQuery({
    queryKey: queryKeys.about.detail,
    queryFn: aboutApi.get,
    staleTime: Infinity,
  });

  useEffect(() => {
    setHeader({
      title: t("settings.tabs.about"),
      subtitle: t("settings.about.subtitle"),
    });
  }, [t, setHeader]);

  const info = about.data;
  const sourceUrl = webLinkOrNull(info?.source_code_url);

  return (
    <div className="max-w-2xl space-y-6 pb-32">
      <Card>
        <CardHeader>
          <CardTitle>
            {info ? t("settings.about.name_version", info) : "Inventari"}
          </CardTitle>
          <p className="text-sm text-on-secondary">{COPYRIGHT}</p>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-on-secondary">
          <p>{t("settings.about.free_software")}</p>
          <p>{t("settings.about.no_warranty")}</p>
          {info && (
            <OutLink href={info.license_url}>
              {t("settings.about.license_link")}
            </OutLink>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("navigation.userGuide")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-on-secondary">
          <p>{t("settings.about.guide_hint")}</p>
          <OutLink href={USER_GUIDE_URL}>
            {t("settings.about.guide_link")}
          </OutLink>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.about.source_title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-on-secondary">
          <p>{t("settings.about.source_hint")}</p>
          {about.error ? (
            <QueryFailure
              error={about.error}
              onRetry={() => void about.refetch()}
            />
          ) : about.isLoading ? (
            <div
              aria-busy="true"
              className="h-5 w-48 animate-pulse rounded bg-surface-inset"
            />
          ) : sourceUrl ? (
            <OutLink href={sourceUrl}>
              {t("settings.about.source_link")}
            </OutLink>
          ) : (
            // A configured value that is not a web address is shown, never
            // made clickable: `href` would run a `javascript:` payload.
            <p className="break-all font-mono text-xs">
              {info?.source_code_url}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.about.third_party_title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-on-secondary">
          <p>{t("settings.about.open_food_facts")}</p>
          <OutLink href={ODBL_URL}>{t("settings.about.odbl_link")}</OutLink>
        </CardContent>
      </Card>
    </div>
  );
}
