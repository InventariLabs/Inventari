import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Input, ReadableError } from "@/module-sdk";
import type { SlotDataMap } from "@/module-sdk";
import { MODULE, NUMBER_MAX_LENGTH, certificateNumber } from "../certificates";

/**
 * The certificate number under every received line with a lot.
 *
 * The value goes on the line, under this module's name, and travels with the
 * document. The pre-post check is the guarantee — a script posts without this
 * field — so this is the courtesy: the reader hears about a missing number
 * before the server is asked.
 */
export default function CertificateField({
  data,
}: {
  data: SlotDataMap["document_line_form_extra"];
}) {
  const { t } = useTranslation(MODULE);
  const { line, setMetaData, registerBeforeSubmit } = data;
  const applies = data.documentType === "IN" && Boolean(line.batchNumber);
  const number = certificateNumber(line.metaData);

  useEffect(() => {
    if (!applies || number) return undefined;
    return registerBeforeSubmit(() => {
      throw new ReadableError(
        t("field.missing", { lot: line.batchNumber ?? "" }),
      );
    });
  }, [applies, number, line.batchNumber, registerBeforeSubmit, t]);

  if (!applies) return null;
  return (
    <Input
      label={t("field.label", { lot: line.batchNumber ?? "" })}
      aria-required
      maxLength={NUMBER_MAX_LENGTH}
      value={String(line.metaData[MODULE]?.number ?? "")}
      onChange={(event) =>
        setMetaData(
          MODULE,
          event.target.value ? { number: event.target.value } : null,
        )
      }
    />
  );
}
