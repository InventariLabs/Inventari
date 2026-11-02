import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowDownToLine,
  ChevronDown,
  FileText,
  Gauge,
  Tags,
} from "lucide-react";
import { Checkbox } from "@/components/ui/Checkbox";
import type { useDocumentProfileDraft } from "@/modules/warehouse/hooks/useDocumentProfileDraft";
import { ApprovalWorkflowSettings } from "./ApprovalWorkflowSettings";
import { DocumentFormatSettings } from "./DocumentFormatSettings";
import { FloorWorkSection } from "./FloorWorkSection";
import { PartnerRequirementsSection } from "./PartnerRequirementsSection";
import { PickOrderSection } from "./PickOrderSection";
import { PrintLayoutSelector } from "./PrintLayoutSelector";
import { ProfilePresetsSection } from "./ProfilePresetsSection";
import { QuarantineLocationSection } from "./QuarantineLocationSection";
import { ReceivingSettingsSection } from "./ReceivingSettingsSection";
import { TaxRatesSection } from "./TaxRatesSection";
import { RelatedScreens } from "./RelatedScreens";
import { ValueTrackingSettings } from "./ValueTrackingSettings";
import { WarehouseReceivingSection } from "./WarehouseReceivingSection";
import { TrackingLinksSection } from "./shipping/TrackingLinksSection";

export type ProfileDraftState = ReturnType<typeof useDocumentProfileDraft>;

const titleClasses = "text-sm font-semibold text-on";
const descriptionClasses = "text-xs text-on-secondary mt-0.5 mb-4";

/** Receiving tolerance and where held goods are put. */
export function ReceivingPanel({ d }: { d: ProfileDraftState }) {
  return (
    <>
      <ReceivingSettingsSection />
      <QuarantineLocationSection
        quarantineLocationId={d.quarantineLocationId}
        onQuarantineLocationIdChange={d.setQuarantineLocationId}
        titleClassName={titleClasses}
        descriptionClassName={descriptionClasses}
      />
    </>
  );
}

/** How each warehouse receives, and the screens that carry the rules on. */
export function PutawayPanel({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <WarehouseReceivingSection canWrite={canWrite} />
      <RelatedScreens
        screens={[
          {
            to: "/warehouse/putaway-rules",
            icon: ArrowDownToLine,
            label: t("configuration.links.putawayRules"),
          },
          {
            to: "/warehouse/occupancy",
            icon: Gauge,
            label: t("configuration.links.occupancy"),
          },
          {
            to: "/warehouse/location-settings",
            icon: Tags,
            label: t("configuration.links.walkOrder"),
          },
        ]}
      />
    </>
  );
}

export function PrintoutsPanel() {
  const { t } = useTranslation("warehouse");
  return (
    <>
      {/* The choice that makes a copied template actually print. */}
      <PrintLayoutSelector />
      <RelatedScreens
        screens={[
          {
            to: "/warehouse/templates",
            icon: FileText,
            label: t("configuration.links.templates"),
          },
        ]}
      />
    </>
  );
}

/** What a closed `<details>` hides: settings that are written once. */
function AdvancedDisclosure({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <details className="group rounded-xl border border-border">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 [&::-webkit-details-marker]:hidden">
        <span className="flex flex-col gap-0.5">
          <span className={titleClasses}>{title}</span>
          <span className="text-xs text-on-secondary">{hint}</span>
        </span>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className="shrink-0 text-on-muted transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="space-y-6 border-t border-border p-4">{children}</div>
    </details>
  );
}

/** Value and tax, the partner's tax ID, and — set apart — the number format. */
export function NumberingPanel({ d }: { d: ProfileDraftState }) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <section className="space-y-6">
        <div>
          <h2 className={titleClasses}>{t("profile.valueTracking")}</h2>
          <p className={descriptionClasses}>{t("profile.valueTrackingHint")}</p>
        </div>
        <ValueTrackingSettings
          valueTracking={d.valueTracking}
          taxHandling={d.taxHandling}
          defaultTaxRate={d.defaultTaxRate}
          defaultCurrency={d.defaultCurrency}
          onValueTrackingChange={d.setValueTracking}
          onTaxHandlingChange={d.setTaxHandling}
          onDefaultTaxRateChange={d.setDefaultTaxRate}
          onDefaultCurrencyChange={d.setDefaultCurrency}
        />
        <Checkbox
          checked={d.valueTracking && d.requireUnitPrice}
          disabled={!d.valueTracking}
          onChange={(e) => d.setRequireUnitPrice(e.target.checked)}
          className="h-4 w-4 cursor-pointer"
          label={
            <span className="text-sm font-medium text-on">
              {t("profile.requireUnitPrice")}
            </span>
          }
        />
        {!d.valueTracking && (
          <p className="text-xs text-on-muted -mt-3">
            {t("profile.requireUnitPriceNeedsValueTracking")}
          </p>
        )}
      </section>
      <TaxRatesSection />
      <PartnerRequirementsSection
        requireTaxId={d.requireTaxId}
        onRequireTaxIdChange={d.setRequireTaxId}
        titleClassName={titleClasses}
        descriptionClassName={descriptionClasses}
      />
      <AdvancedDisclosure
        title={t("configuration.advanced.title")}
        hint={t("configuration.advanced.hint")}
      >
        <DocumentFormatSettings
          numberingFormat={d.numberingFormat}
          numberPadding={d.numberPadding}
          typeLabelIN={d.typeLabelIN}
          typeLabelOUT={d.typeLabelOUT}
          typeLabelINT={d.typeLabelINT}
          typeLabelInternalIn={d.typeLabelInternalIn}
          typeLabelInternalOut={d.typeLabelInternalOut}
          typeLabelCORR={d.typeLabelCORR}
          typeLabelSCRAP={d.typeLabelSCRAP}
          typeLabelADJ={d.typeLabelADJ}
          onNumberingFormatChange={d.setNumberingFormat}
          onNumberPaddingChange={d.setNumberPadding}
          onTypeLabelINChange={d.setTypeLabelIN}
          onTypeLabelOUTChange={d.setTypeLabelOUT}
          onTypeLabelINTChange={d.setTypeLabelINT}
          onTypeLabelInternalInChange={d.setTypeLabelInternalIn}
          onTypeLabelInternalOutChange={d.setTypeLabelInternalOut}
          onTypeLabelCORRChange={d.setTypeLabelCORR}
          onTypeLabelSCRAPChange={d.setTypeLabelSCRAP}
          onTypeLabelADJChange={d.setTypeLabelADJ}
        />
      </AdvancedDisclosure>
    </>
  );
}

export function ApprovalsPanel({ d }: { d: ProfileDraftState }) {
  const { t } = useTranslation("warehouse");
  return (
    <section className="space-y-6">
      <div>
        <h2 className={titleClasses}>{t("profile.approvalWorkflow")}</h2>
        <p className={descriptionClasses}>
          {t("profile.approvalWorkflowHint")}
        </p>
      </div>
      <ApprovalWorkflowSettings
        approvalThreshold={d.approvalThreshold}
        approvalRequiredTypes={d.approvalRequiredTypes}
        profileCurrency={d.defaultCurrency || null}
        onThresholdChange={d.setApprovalThreshold}
        onTypeToggle={(type, selected) =>
          d.setApprovalRequiredTypes(
            selected
              ? [...d.approvalRequiredTypes, type]
              : d.approvalRequiredTypes.filter((other) => other !== type),
          )
        }
      />
    </section>
  );
}

export function FloorPanel({ d }: { d: ProfileDraftState }) {
  return (
    <>
      <FloorWorkSection
        confirmShelfByScan={d.confirmShelfByScan}
        onConfirmShelfByScanChange={d.setConfirmShelfByScan}
        titleClassName={titleClasses}
        descriptionClassName={descriptionClasses}
      />
      <PickOrderSection />
    </>
  );
}

export function TrackingPanel() {
  return <TrackingLinksSection />;
}

type PresetsProps = React.ComponentProps<typeof ProfilePresetsSection>;

export function PresetsPanel(
  props: Omit<PresetsProps, "titleClassName" | "descriptionClassName">,
) {
  return (
    <ProfilePresetsSection
      {...props}
      titleClassName={titleClasses}
      descriptionClassName={descriptionClasses}
    />
  );
}
