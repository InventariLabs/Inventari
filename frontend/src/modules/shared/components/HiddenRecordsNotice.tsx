import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { EyeOff } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useHasPermission } from "@/module-sdk";

interface HiddenRecordsNoticeProps {
  /** Translated one-line copy, the count already filled in. */
  message: string;
  /** Translated label of the control that opens the module-data switch. */
  actionLabel: string;
}

/**
 * One muted line above a list that is showing rows while the module-data
 * policy keeps others off it.
 *
 * The hidden counter used to belong to the empty state alone, so the first
 * visible row silenced it — one hidden record behind three visible ones is
 * exactly the case a reader cannot spot on their own. The same component
 * serves the three lists of that navigation section — `/inventory/items`,
 * `/inventory/categories` and `/inventory/locations` — so it lives in
 * `shared` rather than in any one of their modules; each call site brings
 * its own catalogue's wording.
 *
 * The switch it points at saves only for an administrator. For anyone else
 * the line says who can turn it on instead of sending them to a settings page
 * where it reads "Only an administrator can change this".
 */
export function HiddenRecordsNotice({
  message,
  actionLabel,
}: HiddenRecordsNoticeProps) {
  const navigate = useNavigate();
  const { t } = useTranslation("common");
  const isAdmin = useHasPermission("admin:access");

  return (
    <p className="flex items-center gap-1.5 text-xs text-on-muted">
      <EyeOff size={14} aria-hidden="true" className="shrink-0" />
      <span>
        {message}{" "}
        {isAdmin ? (
          <Button
            variant="link"
            size="contentSm"
            onClick={() => navigate("/settings#module-data")}
            className="px-0 py-0.5 font-medium underline underline-offset-2 text-on-muted hover:text-on"
          >
            {actionLabel}
          </Button>
        ) : (
          t("access.hiddenRecordsAdminOnly")
        )}
      </span>
    </p>
  );
}
