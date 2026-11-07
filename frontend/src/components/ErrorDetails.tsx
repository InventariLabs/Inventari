import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { isRouteErrorResponse } from "react-router-dom";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useAutoResetFlag } from "@/hooks/useAutoResetFlag";
import { copyText } from "@/lib/clipboard";

/**
 * Pages whose address ends in a credential: the password reset, old-style
 * invitation and equipment attestation links that an e-mail hands out.
 */
const SECRET_PATH_TAIL =
  /^(\/(?:reset-password|join|public\/attestation)\/)[^/]+/;
/** Query parameters that carry one: registration and invitation links. */
const SECRET_PARAMS = ["token", "invite", "code"];
const REDACTED = "redacted";

/**
 * The page address with the credentials an e-mailed link put there masked.
 * A crash on such a page would otherwise hand a live token to wherever the
 * report is pasted — for a self-hosted install, often a public issue tracker.
 */
function reportableAddress(href: string): string {
  const url = new URL(href);
  url.pathname = url.pathname.replace(SECRET_PATH_TAIL, `$1${REDACTED}`);
  for (const name of SECRET_PARAMS) {
    if (url.searchParams.has(name)) url.searchParams.set(name, REDACTED);
  }
  return url.href;
}

/** What the reader pastes into a bug report: the failure, the page and the time. */
function describeError(error: unknown): string {
  if (isRouteErrorResponse(error)) {
    return `${error.status} ${error.statusText}`;
  }
  if (error instanceof Error && error.stack) {
    // Chromium puts "Name: message" at the top of `stack`, Firefox does not.
    return error.stack.includes(String(error))
      ? error.stack
      : `${String(error)}\n${error.stack}`;
  }
  return String(error);
}

/**
 * The error the screen could not cure, in a form a bug report can carry.
 *
 * Nothing on a self-hosted install receives the error, so the text shown here
 * is the only trace of it that leaves the browser — by the reader's hand.
 * Shared by the route error page and the error boundary, which would
 * otherwise each word the same hand-off differently.
 */
export default function ErrorDetails({ error }: { error: unknown }) {
  const { t } = useTranslation("common");
  const [copied, markCopied] = useAutoResetFlag(2000);
  // A copy that did not land has to say how to carry the text by hand.
  const [failed, setFailed] = useState(false);

  const report = useMemo(
    () =>
      [
        new Date().toISOString(),
        reportableAddress(window.location.href),
        describeError(error),
      ]
        .join("\n")
        .trim(),
    [error],
  );

  const handleCopy = async () => {
    if ((await copyText(report)) === "copied") {
      setFailed(false);
      markCopied();
    } else {
      setFailed(true);
    }
  };

  return (
    <div className="mt-6 w-full max-w-2xl text-left">
      <pre
        tabIndex={0}
        aria-label={t("errors.detailsLabel")}
        className="p-3 bg-surface-raised rounded-lg border border-border font-mono text-xs text-on-secondary leading-relaxed whitespace-pre-wrap break-words max-h-48 overflow-auto"
      >
        {report}
      </pre>
      <div className="mt-2 flex flex-col items-start gap-1">
        <Button
          variant="outline"
          size="sm"
          leftIcon={copied ? <Check size={16} /> : <Copy size={16} />}
          onClick={handleCopy}
        >
          {copied ? t("actions.copied") : t("errors.copyDetails")}
        </Button>
        {failed && (
          <p role="status" className="text-xs text-on-secondary">
            {t("copy.selectManually")}
          </p>
        )}
      </div>
    </div>
  );
}
