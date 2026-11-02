import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface ActionFooterProps {
  /** Lines entered so far. */
  count: number;
  /** Why the last press did not post, in the server's words or the check's. */
  error: string | null;
  pending: boolean;
  /** The one verb of the screen: "Issue", "Move". */
  label: string;
  onPost: () => void;
}

/**
 * The bottom of a one-screen action: how many lines, why posting stopped,
 * and the one button that posts. Pinned to the bottom, so on a phone the
 * button stays in reach under a long list.
 */
export function ActionFooter({
  count,
  error,
  pending,
  label,
  onPost,
}: ActionFooterProps) {
  const { t } = useTranslation("warehouse");
  return (
    <Card className="sticky bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px)+0.5rem)] z-[var(--z-sticky)] flex flex-wrap items-center justify-between gap-3 p-4 shadow-lg md:bottom-2">
      <div className="min-w-0 space-y-1">
        <p className="text-sm text-on-secondary">
          {/* Lines, the word the posted answer uses for the same count
              ("Issued 2 lines") and the receive footer beside it. */}
          {t("receive.footerLines", { count })}
        </p>
        {error && (
          <p role="alert" className="text-sm text-on-danger">
            {error}
          </p>
        )}
      </div>
      <Button className="w-full sm:w-auto" disabled={pending} onClick={onPost}>
        {label}
      </Button>
    </Card>
  );
}
