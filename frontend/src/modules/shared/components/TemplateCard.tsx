import {
  Download,
  FileText,
  History,
  Pencil,
  Trash2,
  Star,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import type { DocumentTemplate } from "@/modules/shared/lib/templates";
import { formatDate } from "@/utils/helpers";

interface TemplateCardProps {
  template: DocumentTemplate;
  typeLabels: Record<string, string>;
  onEdit: (tpl: DocumentTemplate) => void;
  onDelete: (tpl: DocumentTemplate) => void;
  defaultLabel?: string;
  /** Offered only for a copy whose built-in has moved on. */
  onRefreshCopy?: (tpl: DocumentTemplate) => void;
  isRefreshPending?: boolean;
  /** Offered when the template can leave as a file. */
  onExport?: (tpl: DocumentTemplate) => void;
  /** True drops every action — the card stays, as a record to read. */
  readOnly?: boolean;
}

export function TemplateCard({
  template: tpl,
  typeLabels,
  onEdit,
  onDelete,
  defaultLabel = "Default",
  onRefreshCopy,
  isRefreshPending = false,
  onExport,
  readOnly = false,
}: TemplateCardProps) {
  const { t } = useTranslation("common");
  return (
    <Card className="p-4" data-testid="template-card">
      <div className="flex items-center gap-3">
        <FileText size={18} className="text-primary-500 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 ml-auto">
            <span className="font-medium text-sm text-on truncate">
              {tpl.name}
            </span>
            {tpl.is_default && (
              <Badge variant="info" className="flex items-center gap-1">
                <Star size={10} />
                {defaultLabel}
              </Badge>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-on-muted">
            <span>{typeLabels[tpl.document_type] ?? tpl.document_type}</span>
            {/* A bare date next to "Checkout" says nothing about which
                date it is. The equipment card carried the word; the shared
                one dropped it when the two became one. */}
            {tpl.updated_at && (
              <span>
                {t("templates.updated")} {formatDate(tpl.updated_at)}
              </span>
            )}
          </div>
          {/* A copy belongs to the organization and nothing rewrites it —
              which is why it has to be told that the layout it came from has
              moved on since. */}
          {tpl.source_outdated && (
            <p
              data-testid="template-outdated-note"
              className="mt-1 text-xs text-amber-700 dark:text-amber-400"
            >
              {t("templates.outdatedCopy")}
            </p>
          )}
        </div>
        <div className="flex gap-1">
          {!readOnly && onExport && (
            <Button
              variant="ghost"
              size="iconSm"
              className="text-on-muted hover:text-on"
              title={t("templates.export")}
              aria-label={`${t("templates.export")} ${tpl.name}`}
              onClick={() => onExport(tpl)}
            >
              <Download size={14} />
            </Button>
          )}
          {!readOnly && tpl.source_outdated && onRefreshCopy && (
            <Button
              variant="ghost"
              size="iconSm"
              className="text-on-muted hover:text-on"
              title={t("templates.refreshCopy")}
              aria-label={`${t("templates.refreshCopy")} ${tpl.name}`}
              disabled={isRefreshPending}
              onClick={() => onRefreshCopy(tpl)}
            >
              <History size={14} />
            </Button>
          )}
          {!readOnly && (
            <>
              <Button
                variant="ghost"
                size="iconSm"
                className="text-on-muted hover:text-on"
                title={t("a11y.edit")}
                aria-label={t("a11y.editNamed", { name: tpl.name })}
                onClick={() => onEdit(tpl)}
              >
                <Pencil size={14} />
              </Button>
              <Button
                variant="ghostDanger"
                size="iconSm"
                title={t("a11y.delete")}
                aria-label={t("a11y.deleteNamed", { name: tpl.name })}
                onClick={() => onDelete(tpl)}
              >
                <Trash2 size={14} />
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
