import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input } from "@/module-sdk";
import type { SlotDataMap } from "@/module-sdk";
import { MODULE, NUMBER_MAX_LENGTH, certificateNumber } from "../certificates";

const FINAL = ["COMPLETED", "CANCELLED"];

/**
 * The certificate of a line on the document page. Until the receipt is booked
 * the reader may still fill or change it; afterwards it is what was booked.
 */
export default function CertificateOnLine({
  data,
}: {
  data: SlotDataMap["document_detail_line_extra"];
}) {
  const { t } = useTranslation(MODULE);
  const { line, documentStatus, saveMetaData } = data;
  const number = certificateNumber(line.metaData);
  const [draft, setDraft] = useState(number ?? "");
  // Read the way `certificateNumber` reads a stored one: blank is none, any
  // other number as written — so saving never turns a number on file into
  // another that is not.
  const drafted = draft.trim() ? draft : null;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!line.batchNumber) return null;
  if (FINAL.includes(documentStatus)) {
    return number ? (
      <p className="text-xs text-on-secondary">
        {t("line.certificate", { number })}
      </p>
    ) : null;
  }

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await saveMetaData(MODULE, drafted ? { number: drafted } : null);
    } catch {
      setError(t("line.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-wrap items-end gap-2">
      <Input
        label={t("field.label", { lot: line.batchNumber })}
        aria-required
        maxLength={NUMBER_MAX_LENGTH}
        value={draft}
        error={error ?? undefined}
        onChange={(event) => setDraft(event.target.value)}
        wrapperClassName="min-w-0 flex-1"
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={saving || drafted === number}
        onClick={() => void save()}
      >
        {t("line.save")}
      </Button>
    </div>
  );
}
