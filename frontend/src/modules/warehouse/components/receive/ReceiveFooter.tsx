import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { formatQuantityLocale } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

interface Props {
  lineCount: number;
  quantity: { value: string; unit: string } | null;
  shortCount: number;
  fromOrder: boolean;
  problemText: string | null;
  /** What the press does for this source: receive a delivery, a return, or
   *  add goods nobody delivered. */
  postLabel: string;
  postError: string | null;
  /** Where the refusal can be put right, when it can: a link beside it. */
  postErrorFix?: { to: string; label: string } | null;
  canWrite: boolean;
  savingDraft: boolean;
  posting: boolean;
  onFinishLater: () => void;
  onPost: () => void;
}

/** The sticky footer: what the sheet holds, why it cannot post, and the two doors. */
export function ReceiveFooter({
  lineCount,
  quantity,
  shortCount,
  fromOrder,
  problemText,
  postLabel,
  postError,
  postErrorFix,
  canWrite,
  savingDraft,
  posting,
  onFinishLater,
  onPost,
}: Props) {
  const { t } = useTranslation("warehouse");

  const note = (() => {
    if (shortCount > 0) return t("receive.shortSummary", { count: shortCount });
    if (fromOrder) return t("receive.fullOrder");
    return t("receive.keyboardHint");
  })();

  return (
    <Card className="sticky bottom-0 flex flex-wrap items-center gap-3 px-4 py-3 shadow-lg">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-on">
          {t("receive.footerLines", { count: lineCount })}
          {quantity
            ? `, ${formatQuantityLocale(quantity.value)} ${unitLabel(t, quantity.unit)}`
            : ""}
        </p>
        <p className="text-xs text-on-secondary">{note}</p>
      </div>
      <span className="flex-1" />
      {problemText && (
        <p role="alert" className="text-sm text-on-danger">
          {problemText}
        </p>
      )}
      {postError && (
        <p role="alert" className="text-sm text-on-danger">
          {postError}
          {postErrorFix && (
            <>
              {" "}
              <Link to={postErrorFix.to} className="font-medium underline">
                {postErrorFix.label}
              </Link>
            </>
          )}
        </p>
      )}
      <Button
        type="button"
        variant="ghost"
        disabled={!canWrite || savingDraft || posting}
        isLoading={savingDraft}
        onClick={onFinishLater}
      >
        {savingDraft ? t("receive.savingDraft") : t("receive.finishLater")}
      </Button>
      <Button
        type="button"
        disabled={!canWrite || savingDraft || posting}
        isLoading={posting}
        onClick={onPost}
      >
        {posting ? t("receive.posting") : postLabel}
      </Button>
    </Card>
  );
}
