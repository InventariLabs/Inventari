import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import type { AuditResponseItemRecord } from "@/modules/equipment/api/equipment_campaigns";

interface DisputeFormProps {
  /** with several assets the dispute names one of them. */
  items?: AuditResponseItemRecord[];
  onSubmit: (type: string, reason: string, assignmentId?: string) => void;
  onCancel: () => void;
  isPending: boolean;
}

export function DisputeForm({
  items = [],
  onSubmit,
  onCancel,
  isPending,
}: DisputeFormProps) {
  const { t } = useTranslation("equipment");
  const [disputeType, setDisputeType] = useState("");
  const [reason, setReason] = useState("");
  const [assignmentId, setAssignmentId] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (items.length > 1 && !assignmentId) return;
    onSubmit(
      disputeType,
      reason,
      items.length > 1 ? assignmentId : items[0]?.assignment_id,
    );
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 border-t border-border pt-4"
    >
      <h3 className="font-semibold text-on">
        {t("attestation.public.reportHeading")}
      </h3>

      {items.length > 1 && (
        <div>
          <Select
            label={t("attestation.public.selectItem")}
            value={assignmentId}
            onChange={(id) => setAssignmentId(id)}
            options={items.map((item) => ({
              id: item.assignment_id,
              name: item.serial_number
                ? `${item.item_name} (${item.serial_number})`
                : item.item_name,
            }))}
          />
        </div>
      )}

      <div>
        <Select
          label={t("attestation.public.issueType")}
          required
          value={disputeType}
          onChange={(id) => setDisputeType(id)}
          options={[
            {
              id: "MISSING",
              name: t("attestation.public.issueTypeMissing"),
            },
            {
              id: "DAMAGED",
              name: t("attestation.public.issueTypeDamaged"),
            },
            {
              id: "WRONG_ITEM",
              name: t("attestation.public.issueTypeWrongItem"),
            },
            { id: "OTHER", name: t("attestation.public.issueTypeOther") },
          ]}
        />
      </div>

      <Textarea
        label={t("attestation.public.detailsLabel")}
        // Inline-validated: the submit button is what enforces this, so the
        // star and the announcement come from aria-required.
        aria-required
        className="w-full rounded-md border border-border bg-surface-card text-on px-3 py-2 text-sm dark:[color-scheme:dark]"
        rows={3}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={t("attestation.public.detailsPlaceholder")}
      />

      <div className="flex gap-2">
        {/* ui-pattern: filled-destructive — the form exists to report that
            something is wrong, so this submit is the point of the screen and
            the colour is the message rather than a warning about it */}
        <Button
          type="submit"
          variant="danger"
          disabled={
            !disputeType ||
            !reason.trim() ||
            isPending ||
            (items.length > 1 && !assignmentId)
          }
        >
          {isPending
            ? t("attestation.public.submitting")
            : t("attestation.public.submitReport")}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("attestation.public.cancel")}
        </Button>
      </div>
    </form>
  );
}
