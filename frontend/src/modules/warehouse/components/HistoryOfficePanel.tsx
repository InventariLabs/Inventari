import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  NEW_DOCUMENT_TYPES,
  NewDocumentMenu,
} from "@/modules/warehouse/components/NewDocumentMenu";
import type { DocumentType } from "@/modules/warehouse/types";

const ROW_CLASS =
  "block rounded-lg px-2 py-2 hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500";

interface HistoryOfficePanelProps {
  /** Starting a document by hand is a write; a read-only account does not get it. */
  canWrite: boolean;
  onNewDocument: (type: DocumentType) => void;
}

function PanelEntry({ title, hint }: { title: string; hint: string }) {
  return (
    <span className="flex flex-col items-start gap-0.5">
      <span className="text-sm font-medium text-on">{title}</span>
      <span className="text-xs font-normal text-on-secondary">{hint}</span>
    </span>
  );
}

/**
 * The side panel of History for the person who keeps the books: the register
 * of documents, closing the month, and a document written by hand for the day
 * the accountant asks for one in particular. Everyone else never needs to
 * open any of them — the floor's actions write their documents themselves.
 */
export function HistoryOfficePanel({
  canWrite,
  onNewDocument,
}: HistoryOfficePanelProps) {
  const { t } = useTranslation("warehouse");

  return (
    <aside
      className="flex flex-col gap-3"
      aria-label={t("warehouse:history.panel.title")}
    >
      <Card className="p-4 space-y-1">
        <h2 className="text-base font-semibold text-on">
          {t("warehouse:history.panel.title")}
        </h2>
        <Link to="/warehouse/all" className={ROW_CLASS}>
          <PanelEntry
            title={t("warehouse:navigation.documents")}
            hint={t("warehouse:history.panel.documents.hint")}
          />
        </Link>
        <Link to="/warehouse/register" className={ROW_CLASS}>
          <PanelEntry
            title={t("warehouse:history.panel.register.title")}
            hint={t("warehouse:history.panel.register.hint")}
          />
        </Link>
        <Link to="/warehouse/periods" className={ROW_CLASS}>
          <PanelEntry
            title={t("warehouse:history.panel.closeMonth.title")}
            hint={t("warehouse:history.panel.closeMonth.hint")}
          />
        </Link>
        {canWrite && (
          <NewDocumentMenu
            onSelect={onNewDocument}
            trigger={
              <Button
                variant="ghost"
                size="row"
                aria-haspopup="menu"
                className="px-2 py-2"
              >
                <span className="flex flex-col items-start gap-0.5">
                  <span className="text-sm font-medium text-on">
                    {t("warehouse:history.panel.newDocument.title")}
                  </span>
                  <span className="text-xs font-normal text-on-secondary">
                    {t("warehouse:history.panel.newDocument.hint", {
                      types: NEW_DOCUMENT_TYPES.map((type) =>
                        t(`warehouse:types.${type}`),
                      ).join(", "),
                    })}
                  </span>
                </span>
              </Button>
            }
          />
        )}
      </Card>
      <Card className="p-4 space-y-1">
        <h2 className="text-base font-semibold text-on">
          {t("warehouse:history.mistake.title")}
        </h2>
        <p className="text-sm text-on-secondary">
          {t("warehouse:history.mistake.body", {
            action: t("warehouse:corrections.new"),
          })}
        </p>
      </Card>
    </aside>
  );
}
