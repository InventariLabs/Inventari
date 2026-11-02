import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Building2,
  CalendarDays,
  FileText,
  ShoppingCart,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Power,
  PowerOff,
  StickyNote,
  Globe,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { useModules } from "@/contexts/ModulesContext";
import { countryLabel } from "@/lib/countries";
import { cn } from "@/lib/utils";
import { formatDate } from "@/utils/formatters";
import { usePartnerTurnover } from "@/modules/partners/hooks/usePartnerTurnover";
import { usePartner } from "@/modules/partners/hooks/usePartners";
import type { Partner, PartnerType } from "@/types";

interface PartnerDetailSheetProps {
  partner: Partner;
  onClose: () => void;
  onEdit: (partner: Partner) => void;
  onToggleActive: (partner: Partner) => void;
  /** Whether the sheet's footer offers editing and deactivating. */
  canWrite?: boolean;
}

const TYPE_BADGES: Record<PartnerType, string> = {
  SUPPLIER: "bg-primary-50 text-primary-700",
  CUSTOMER: "bg-accent-50 text-accent-700",
  BOTH: "bg-primary-50 text-primary-700",
  SERVICE_PROVIDER: "bg-amber-50 text-amber-700",
  MANUFACTURER: "bg-surface-raised text-on-secondary",
  EMPLOYEE: "bg-accent-50 text-accent-700",
};

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  if (children == null || children === "") return null;
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-border last:border-0">
      <span className="text-xs font-medium uppercase tracking-wide text-on-muted shrink-0">
        {label}
      </span>
      <span className="text-sm text-on text-right break-words">{children}</span>
    </div>
  );
}

export function PartnerDetailSheet({
  partner,
  onClose,
  onEdit,
  onToggleActive,
  canWrite = true,
}: PartnerDetailSheetProps) {
  const { t, i18n } = useTranslation("partners");
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const turnover = usePartnerTurnover();
  // The sheet opens from a list row, so the list item is the initial data;
  // GET /partners/{id} refetches the basic fields in the background so the
  // sheet never shows stale contact details.
  const { data: fresh } = usePartner(partner.id, partner);
  const p = fresh ?? partner;
  const {
    name,
    type,
    code,
    tax_id,
    is_consumer,
    email,
    phone,
    website,
    contact_person,
    address,
    notes,
    is_active,
    created_at,
    updated_at,
  } = p;

  const addressText = address
    ? [
        address.street,
        address.postal_code,
        address.city,
        address.country ? countryLabel(address.country, lang) : null,
      ]
        .filter(Boolean)
        .join(", ")
    : null;

  return (
    <Sheet open onClose={onClose} maxWidth="md" aria-label={t("detail.title")}>
      <div className="flex items-start gap-3 p-5 border-b border-border">
        <div className="shrink-0 w-11 h-11 rounded-full bg-primary-50 flex items-center justify-center">
          <Building2 size={20} className="text-primary-600" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-semibold text-on truncate">{name}</h2>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                TYPE_BADGES[type as PartnerType],
              )}
            >
              {t(`types.${type}`)}
            </span>
            {is_consumer && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-surface-raised text-on-secondary">
                {t("fields.isConsumer")}
              </span>
            )}
            {!is_active && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-surface-raised text-on-secondary">
                {t("status.inactive")}
              </span>
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
          className="rounded-full text-on-muted"
        >
          <X size={18} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <div className="divide-y divide-border">
          {code && <DetailRow label={t("fields.code")}>{code}</DetailRow>}
          {tax_id && <DetailRow label={t("fields.taxId")}>{tax_id}</DetailRow>}
          {email && (
            <DetailRow label={t("fields.email")}>
              <a
                href={`mailto:${email}`}
                className="inline-flex items-center gap-1 text-primary-600 hover:underline"
              >
                <Mail size={13} /> {email}
              </a>
            </DetailRow>
          )}
          {phone && (
            <DetailRow label={t("fields.phone")}>
              <a
                href={`tel:${phone}`}
                className="inline-flex items-center gap-1 text-primary-600 hover:underline"
              >
                <Phone size={13} /> {phone}
              </a>
            </DetailRow>
          )}
          {website && (
            <DetailRow label={t("fields.website")}>
              <a
                href={
                  website.startsWith("http") ? website : `https://${website}`
                }
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary-600 hover:underline"
              >
                <Globe size={13} /> {website}
              </a>
            </DetailRow>
          )}
          {contact_person && (
            <DetailRow label={t("fields.contactPerson")}>
              {contact_person}
            </DetailRow>
          )}
          {addressText && (
            <DetailRow label={t("fields.address")}>
              <span className="inline-flex items-start gap-1">
                <MapPin size={13} className="mt-0.5 shrink-0" /> {addressText}
              </span>
            </DetailRow>
          )}
          {notes && (
            <DetailRow label={t("fields.notes")}>
              <span className="inline-flex items-start gap-1">
                <StickyNote size={13} className="mt-0.5 shrink-0" /> {notes}
              </span>
            </DetailRow>
          )}
          <DetailRow label={t("detail.createdAt")}>
            <span className="inline-flex items-center gap-1">
              <CalendarDays size={13} /> {formatDate(created_at)}
            </span>
          </DetailRow>
          <DetailRow label={t("detail.updatedAt")}>
            <span className="inline-flex items-center gap-1">
              <CalendarDays size={13} /> {formatDate(updated_at)}
            </span>
          </DetailRow>
        </div>

        {/* The list row already surfaces these three numbers. The
            detail endpoint does not return them, so they come from the list
            item the sheet was opened from — the same source as the row. */}
        <div className="mt-5 flex flex-wrap gap-4 text-sm text-on-secondary">
          <span className="tabular-nums">
            {t("stats.documents", { count: partner.document_count ?? 0 })}
          </span>
          <span>
            {t("stats.total")}:{" "}
            <span className="text-on-secondary tabular-nums">
              {turnover(partner)}
            </span>
          </span>
          <span>
            {t("stats.lastActivity")}:{" "}
            <span className="text-on-secondary">
              {formatDate(partner.last_activity_at)}
            </span>
          </span>
        </div>

        <PartnerRelatedLinks partner={partner} />
      </div>

      {canWrite && (
        <PartnerSheetFooter
          partner={p}
          onEdit={onEdit}
          onToggleActive={onToggleActive}
        />
      )}
    </Sheet>
  );
}

/**
 * Where this partner appears elsewhere in the app.
 *
 * The card used to end at the phone number: the list behind it counts a
 * partner's documents and turnover, and opening them led nowhere. The flow
 * partner → order → receipt → document existed in the backend and stopped at
 * this sheet. Each link is offered only where its module is on.
 */
function PartnerRelatedLinks({ partner }: { partner: Partner }) {
  const { t } = useTranslation("partners");
  const { isModuleEnabled } = useModules();
  const links = [
    {
      module: "warehouse",
      to: `/warehouse/all?partner_id=${partner.id}`,
      icon: FileText,
      label: t("detail.relatedDocuments"),
      count: partner.document_count,
    },
    {
      module: "purchase_orders",
      to: `/purchase-orders?partner_id=${partner.id}`,
      icon: ShoppingCart,
      label: t("detail.relatedOrders"),
      // Counted like the documents link beside it: the reader can tell a
      // real zero from "not counted".
      count: partner.purchase_order_count,
    },
  ].filter((link) => isModuleEnabled(link.module));

  if (links.length === 0) return null;

  return (
    <div className="mt-5 space-y-2">
      <h3 className="text-xs font-medium uppercase tracking-wide text-on-muted">
        {t("detail.related")}
      </h3>
      {links.map(({ to, icon: Icon, label, count }) => (
        <Link
          key={to}
          to={to}
          className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5 text-sm text-on hover:bg-surface-raised"
        >
          <span className="inline-flex items-center gap-2">
            <Icon size={15} className="text-on-muted" />
            {label}
            {count != null && (
              <span className="text-xs text-on-muted tabular-nums">
                {count}
              </span>
            )}
          </span>
          <ArrowRight size={15} className="text-on-muted" />
        </Link>
      ))}
    </div>
  );
}

/**
 * The sheet's own actions, on their own.
 *
 * Split out because the sheet had reached the complexity ceiling reading a
 * partner's fields; deciding what a reader may do with one is a separate
 * question from displaying it.
 */
function PartnerSheetFooter({
  partner,
  onEdit,
  onToggleActive,
}: {
  partner: Partner;
  onEdit: (partner: Partner) => void;
  onToggleActive: (partner: Partner) => void;
}) {
  const { t } = useTranslation("partners");
  return (
    <div className="flex items-center justify-end gap-2 p-5 border-t border-border">
      <Button
        variant={partner.is_active ? "ghostDanger" : "outline"}
        onClick={() => onToggleActive(partner)}
      >
        {partner.is_active ? (
          <>
            <PowerOff size={15} />
            {t("actions.deactivate")}
          </>
        ) : (
          <>
            <Power size={15} className="text-accent-600" />
            {t("actions.activate")}
          </>
        )}
      </Button>
      <Button onClick={() => onEdit(partner)} leftIcon={<Pencil size={15} />}>
        {t("actions.edit")}
      </Button>
    </div>
  );
}
