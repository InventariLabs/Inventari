import { Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";

interface FrozenListNoticeProps {
  /** Why the list is closed: it was finished or put away. */
  status: string;
  /** Whether this account may reactivate it; the notice reads the same either way. */
  canReactivate: boolean;
  onReactivate: () => void;
  busy: boolean;
}

/**
 * One line saying a list is closed, in place of the buttons that would end in
 * the server's refusal. A completed or archived list takes no new lines and no
 * ticks until it is reactivated, so the page names that and offers the way out.
 */
export function FrozenListNotice({
  status,
  canReactivate,
  onReactivate,
  busy,
}: FrozenListNoticeProps) {
  const { t } = useTranslation("shopping_lists");
  return (
    <div
      className="flex items-start gap-3 rounded-xl bg-surface-inset px-4 py-3 text-on-secondary"
      role="note"
    >
      <Lock size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="flex-1">
        <p className="text-sm font-medium text-on">
          {t(
            status === "archived"
              ? "detail.archivedTitle"
              : "detail.completedTitle",
          )}
        </p>
        <p className="text-sm">{t("detail.frozenHint")}</p>
      </div>
      {canReactivate && (
        <Button
          variant="outline"
          size="sm"
          onClick={onReactivate}
          disabled={busy}
        >
          {t("detail.reactivate")}
        </Button>
      )}
    </div>
  );
}
