import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  useSilencedHomeShelves,
  useUnsilenceHomeShelf,
} from "@/modules/warehouse/hooks/usePutawayRules";
import { SettingsSectionHeader } from "./SettingsSectionHeader";

/**
 * The products the put-away was told not to ask about, each with the way back.
 * Absent while there are none, so a warehouse that never said "do not ask
 * again" never meets the section.
 */
export function SilencedHomeShelves({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation("warehouse");
  const { data: silenced } = useSilencedHomeShelves();
  const unsilence = useUnsilenceHomeShelf();
  if (!silenced || silenced.length === 0) return null;

  return (
    <Card className="p-4">
      <SettingsSectionHeader
        title={t("putaway.silenced.title")}
        hint={t("putaway.silenced.hint")}
      />
      <ul className="divide-y divide-border">
        {silenced.map((row) => (
          <li
            key={row.product_template_id}
            className="flex items-center justify-between gap-3 py-2"
          >
            <span className="min-w-0 break-words text-on">
              {row.product_name ?? row.product_template_id}
            </span>
            {canWrite && (
              <Button
                variant="outline"
                size="sm"
                disabled={unsilence.isPending}
                aria-label={t("putaway.silenced.askAgainFor", {
                  product: row.product_name ?? "",
                })}
                onClick={() => unsilence.mutate(row.product_template_id)}
              >
                {t("putaway.silenced.askAgain")}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
