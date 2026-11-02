import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { queryKeys } from "@/hooks/queries/keys";
import { apiErrorStatus, extractApiError } from "@/lib/errors";
import {
  templatesApi,
  type TemplateUrlSegment,
} from "@/modules/shared/lib/templates";

interface Props {
  module: TemplateUrlSegment;
  bodyHtml: string;
  className?: string;
}

/**
 * What a layout prints, rendered on the example document.
 *
 * Server-side, through the same Jinja pass the PDF goes through: a frame
 * holding the source answers "what does this template say", not "what will
 * the paper look like". A half-written layout is the editor's normal state,
 * so a failed render is an answer rather than an outage to retry — the
 * message says which line Jinja objected to.
 */
export function TemplatePreviewFrame({ module, bodyHtml, className }: Props) {
  const { t, i18n } = useTranslation(["common"]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.templatePreview.render(module, bodyHtml, i18n.language),
    queryFn: () => templatesApi.preview(module, bodyHtml),
    enabled: bodyHtml.trim() !== "",
    retry: false,
  });

  if (error) {
    // A 4xx is the renderer's verdict on the layout (below). Anything else —
    // a 5xx, a network failure — says nothing about the layout, so the frame
    // must not call it broken.
    const status = apiErrorStatus(error);
    if (status === null || status >= 500) {
      return (
        <div role="alert" className="p-4 text-sm text-red-600">
          <p>{t("common:templates.preview_unavailable")}</p>
          <Button
            type="button"
            variant="secondary"
            className="mt-2"
            onClick={() => void refetch()}
          >
            {t("common:actions.retry")}
          </Button>
        </div>
      );
    }
    // The backend's message names the line and file Jinja objected to —
    // without it a broken layout is a dead end. It is Jinja's text, not
    // ours: rendered as text, never as HTML.
    const reason = extractApiError(
      error,
      t("common:templates.preview_failed", "This layout does not render."),
    );
    return (
      <p role="alert" className="text-sm text-red-600 p-4">
        {reason}
      </p>
    );
  }

  return (
    <iframe
      srcDoc={isLoading ? "" : (data ?? "")}
      className={className ?? "w-full h-[460px] border-0"}
      title={t("common:a11y.templatePreview")}
      sandbox=""
    />
  );
}
