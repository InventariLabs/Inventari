import React from "react";
import { useTranslation } from "react-i18next";
import { Info } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { currencySymbol } from "@/utils/formatters";
import { DOCUMENT_TYPES } from "@/modules/warehouse/types";
import { TypedSlot } from "@/components/Slot";
import { DocumentApprovalModuleOffNotice } from "./DocumentApprovalModuleOffNotice";

const DOCUMENT_STATUS = [
  "DRAFT",
  "CONFIRMED",
  "PENDING_APPROVAL",
  "COMPLETED",
  "CANCELLED",
] as const;

/** DRAFT → CONFIRMED → PENDING_APPROVAL → CONFIRMED → COMPLETED. The cycle
 * enters CONFIRMED twice — before the document goes out for approval and
 * again after the approval is granted — so the second visit carries its own
 * legend name; one word for both phases told the reader nothing about which
 * side of the wait they were looking at. */
const APPROVAL_CYCLE: ReadonlyArray<{
  status: (typeof DOCUMENT_STATUS)[number];
  /** Set on the second CONFIRMED visit: one state, two phases, two names. */
  afterApproval?: boolean;
}> = [
  { status: "DRAFT" },
  { status: "CONFIRMED" },
  { status: "PENDING_APPROVAL" },
  { status: "CONFIRMED", afterApproval: true },
  { status: "COMPLETED" },
];

interface ApprovalWorkflowSettingsProps {
  approvalThreshold: string;
  approvalRequiredTypes: string[];
  /** Profile currency (ISO 4217); the organization default is used
   * when the profile has none configured. */
  profileCurrency?: string | null;
  onThresholdChange: (threshold: string) => void;
  onTypeToggle: (type: string, selected: boolean) => void;
}

export function ApprovalWorkflowSettings({
  approvalThreshold,
  approvalRequiredTypes,
  profileCurrency,
  onThresholdChange,
  onTypeToggle,
}: ApprovalWorkflowSettingsProps) {
  const { t } = useTranslation("warehouse");
  const currency = useDocumentCurrency(profileCurrency ?? null);
  const approvalRequested =
    approvalThreshold.trim() !== "" || approvalRequiredTypes.length > 0;

  return (
    <div className="space-y-6">
      <TypedSlot
        name="document_approval_setup_notice"
        data={{ approvalRequested }}
        fallback={
          <DocumentApprovalModuleOffNotice
            approvalRequested={approvalRequested}
          />
        }
      />

      <div className="flex gap-4 rounded-xl bg-surface border border-border/60 p-4">
        <Info size={20} className="text-on-muted shrink-0" />
        <div className="space-y-3">
          <p className="text-sm text-on-secondary leading-relaxed">
            {t("profile.approvalHowItWorks")}
          </p>
          {/* The real cycle, in the reader's language. This diagram used to
              show PENDING and APPROVED — two states a document never enters —
              while the state it does enter, PENDING_APPROVAL, was missing.
              Approval sends the document back to Confirmed, which is
              where completion is allowed from. */}
          <div
            className="flex flex-wrap items-center gap-2"
            data-testid="approval-flow-legend"
          >
            {APPROVAL_CYCLE.map((visit, i, arr) => (
              <React.Fragment key={`${visit.status}-${i}`}>
                <span
                  data-phase
                  className="px-2 py-0.5 rounded-lg bg-surface-card border border-border text-[10px] font-medium text-on-secondary shadow-sm"
                >
                  {visit.afterApproval
                    ? t("status.confirmedAfterApproval")
                    : t(`status.${visit.status}`)}
                </span>
                {i < arr.length - 1 && (
                  <span className="text-on-muted text-xs">&rarr;</span>
                )}
              </React.Fragment>
            ))}
          </div>
          <p className="text-xs text-on-muted">
            {t("profile.approvalRejectionNote")}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Input
            type="number"
            min={0}
            step={0.01}
            label={t("profile.approvalThreshold")}
            value={approvalThreshold}
            onChange={(e) => onThresholdChange(e.target.value)}
            placeholder="1000"
            leftIcon={
              currency ? (
                <span className="text-xs font-medium text-on-muted">
                  {currencySymbol(currency)}
                </span>
              ) : undefined
            }
          />
          <p className="text-xs text-on-secondary ml-1">
            {t("profile.approvalThresholdHint")}
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <p className="text-xs font-medium uppercase text-on-secondary tracking-wide ml-1">
          {t("profile.approvalRequiredForTypes")}
        </p>
        <div className="flex flex-wrap gap-2">
          {DOCUMENT_TYPES.map((type) => {
            const isSelected = approvalRequiredTypes.includes(type);
            return (
              <label
                key={type}
                className={`
                  inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border cursor-pointer
                  text-xs font-medium transition-all duration-200
                  ${
                    isSelected
                      ? "border-primary-600 bg-primary-50 text-primary-700"
                      : "border-border bg-surface-card text-on-secondary hover:border-border hover:bg-surface"
                  }
                `}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={(e) => onTypeToggle(type, e.target.checked)}
                  className="sr-only"
                />
                {t(`types.${type}`)}
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}
