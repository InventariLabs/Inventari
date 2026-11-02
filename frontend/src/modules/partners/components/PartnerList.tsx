import { useTranslation } from "react-i18next";
import { Building2, Power, PowerOff, Pencil } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { formatDate } from "@/utils/formatters";
import { usePartnerTurnover } from "@/modules/partners/hooks/usePartnerTurnover";
import type { Partner, PartnerType } from "@/types";

const TYPE_BADGES: Record<PartnerType, string> = {
  SUPPLIER: "bg-primary-50 text-primary-700",
  CUSTOMER: "bg-accent-50 text-accent-700",
  BOTH: "bg-primary-50 text-primary-700",
  SERVICE_PROVIDER: "bg-amber-50 text-amber-700",
  MANUFACTURER: "bg-surface-raised text-on-secondary",
  EMPLOYEE: "bg-accent-50 text-accent-700",
};

interface Props {
  partners: Partner[];
  canWrite: boolean;
  onOpen: (partner: Partner) => void;
  onEdit: (partner: Partner) => void;
  onToggleActive: (partner: Partner) => void;
}

/**
 * The partner list: a `<table>` where a row has columns (§14.1), the card
 * stack on a phone, where a row is a touch target rather than a line to scan.
 */
export function PartnerList(props: Props) {
  const isPhone = useMediaQuery("(max-width: 767px)");
  return isPhone ? <PartnerCards {...props} /> : <PartnerTable {...props} />;
}

function useLastActivity() {
  return (partner: Partner) => formatDate(partner.last_activity_at);
}

function TypeBadge({ partner }: { partner: Partner }) {
  const { t } = useTranslation("partners");
  return (
    <span
      className={cn(
        "text-xs px-2 py-0.5 rounded-full font-medium",
        TYPE_BADGES[partner.type as PartnerType],
      )}
    >
      {t(`types.${partner.type}`)}
    </span>
  );
}

function InactiveBadge() {
  const { t } = useTranslation("partners");
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-surface-raised text-on-secondary">
      {t("status.inactive")}
    </span>
  );
}

/**
 * Edit | Deactivate. Deactivation is destructive and sat flush against Edit in
 * the same weight; the divider and the danger colour make the boundary visible
 * before the tap, not after (§2.13a). Icon-only, so each carries `aria-label`
 * and `title` with the same words (§11.4).
 */
function PartnerActions({
  partner,
  onEdit,
  onToggleActive,
}: Pick<Props, "onEdit" | "onToggleActive"> & { partner: Partner }) {
  const { t } = useTranslation("partners");
  const toggleLabel = partner.is_active
    ? t("actions.deactivate")
    : t("actions.activate");
  return (
    <div className="flex items-center gap-1 shrink-0">
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("actions.edit")}
        title={t("actions.edit")}
        onClick={(e) => {
          e.stopPropagation();
          onEdit(partner);
        }}
      >
        <Pencil size={16} />
      </Button>
      <span aria-hidden="true" className="w-px h-5 shrink-0 bg-border mx-1" />
      <Button
        variant={partner.is_active ? "ghostDanger" : "ghost"}
        size="icon"
        aria-label={toggleLabel}
        title={toggleLabel}
        onClick={(e) => {
          e.stopPropagation();
          onToggleActive(partner);
        }}
      >
        {partner.is_active ? (
          <PowerOff size={16} />
        ) : (
          <Power size={16} className="text-accent-600" />
        )}
      </Button>
    </div>
  );
}

function PartnerTable({ partners, canWrite, onOpen, ...actions }: Props) {
  const { t } = useTranslation("partners");
  const turnover = usePartnerTurnover();
  const lastActivity = useLastActivity();
  const heading = "px-3 py-2.5 font-medium text-on-secondary";
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-surface-card">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide">
            <th scope="col" className={heading}>
              {t("columns.name")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.type")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.taxId")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.contact")}
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              {t("columns.documents")}
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              {t("stats.total")}
            </th>
            <th scope="col" className={heading}>
              {t("stats.lastActivity")}
            </th>
            {canWrite && (
              <th scope="col" className={heading}>
                <span className="sr-only">{t("columns.actions")}</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {partners.map((partner) => (
            <tr
              key={partner.id}
              className={cn(
                "border-b border-border last:border-b-0 cursor-pointer transition-colors hover:bg-surface-raised",
                !partner.is_active && "opacity-60",
              )}
              onClick={() => onOpen(partner)}
            >
              <td className="px-3 py-2.5">
                <div className="flex items-center gap-2 min-w-0">
                  <Building2 size={16} className="shrink-0 text-primary-600" />
                  <span className="font-semibold text-on truncate">
                    {partner.name}
                  </span>
                  {!partner.is_active && <InactiveBadge />}
                </div>
              </td>
              <td className="px-3 py-2.5">
                <TypeBadge partner={partner} />
              </td>
              <td className="px-3 py-2.5 text-on-secondary">
                {partner.tax_id ?? "—"}
              </td>
              <td className="px-3 py-2.5 text-xs text-on-secondary">
                <div className="flex flex-col">
                  {[partner.contact_person, partner.email, partner.phone]
                    .filter(Boolean)
                    .map((value) => (
                      <span key={value}>{value}</span>
                    ))}
                </div>
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {partner.document_count ?? 0}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {turnover(partner)}
              </td>
              <td className="px-3 py-2.5 text-on-secondary">
                {lastActivity(partner)}
              </td>
              {canWrite && (
                <td className="px-3 py-2.5">
                  <PartnerActions partner={partner} {...actions} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PartnerCards({ partners, canWrite, onOpen, ...actions }: Props) {
  const { t } = useTranslation("partners");
  const turnover = usePartnerTurnover();
  const lastActivity = useLastActivity();
  return (
    <div className="space-y-2">
      {partners.map((partner) => (
        <Card
          key={partner.id}
          data-testid="partner-card"
          className={cn(
            "flex items-center gap-4 p-4 cursor-pointer transition-colors hover:border-primary-200",
            !partner.is_active && "opacity-60",
          )}
          onClick={() => onOpen(partner)}
        >
          <div className="shrink-0 w-10 h-10 rounded-full bg-primary-50 flex items-center justify-center">
            <Building2 size={18} className="text-primary-600" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {/* Each row is the first level of content under the page
                  title, so it takes h2 (UI_GUIDELINES §2.11). */}
              <h2 className="text-sm font-semibold text-on truncate">
                {partner.name}
              </h2>
              <TypeBadge partner={partner} />
              {!partner.is_active && <InactiveBadge />}
            </div>
            <div className="flex gap-3 text-xs text-on-secondary mt-0.5 flex-wrap">
              {partner.tax_id && <span>{partner.tax_id}</span>}
              {partner.email && <span>{partner.email}</span>}
              {partner.phone && <span>{partner.phone}</span>}
              {partner.contact_person && <span>{partner.contact_person}</span>}
            </div>
            <div className="flex gap-4 text-xs text-on-secondary mt-1 flex-wrap">
              <span className="tabular-nums">
                {t("stats.documents", { count: partner.document_count ?? 0 })}
              </span>
              <span>
                {t("stats.total")}:{" "}
                <span className="tabular-nums">{turnover(partner)}</span>
              </span>
              <span>
                {t("stats.lastActivity")}: <span>{lastActivity(partner)}</span>
              </span>
            </div>
          </div>
          {canWrite && <PartnerActions partner={partner} {...actions} />}
        </Card>
      ))}
    </div>
  );
}
