import { useState } from "react";
import { AlertTriangle, CheckCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";

interface AnswerButtonsProps {
  onConfirm: () => void;
  onReport: () => void;
  isPending: boolean;
}

/**
 * The two ways to answer the public link. The link takes the answer once, so
 * "I have this asset" asks first: a slip of the thumb must not be the answer.
 */
export function AnswerButtons({
  onConfirm,
  onReport,
  isPending,
}: AnswerButtonsProps) {
  const { t } = useTranslation("equipment");
  const [asking, setAsking] = useState(false);

  if (asking) {
    return (
      <div className="space-y-3" role="group">
        <p className="font-semibold text-on">
          {t("attestation.public.confirmAsk")}
        </p>
        <div className="flex gap-3 flex-col sm:flex-row">
          <Button
            className="w-full sm:w-auto"
            onClick={onConfirm}
            disabled={isPending}
          >
            <CheckCircle size={16} className="mr-2" />
            {isPending
              ? t("attestation.public.confirming")
              : t("attestation.public.confirmYes")}
          </Button>
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            onClick={() => setAsking(false)}
            disabled={isPending}
          >
            {t("common:actions.back")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 flex-col sm:flex-row">
      <Button className="w-full sm:w-auto" onClick={() => setAsking(true)}>
        <CheckCircle size={16} className="mr-2" />
        {t("attestation.public.confirmButton")}
      </Button>
      <Button variant="outline" className="w-full sm:w-auto" onClick={onReport}>
        <AlertTriangle size={16} className="mr-2" />
        {t("attestation.public.reportIssue")}
      </Button>
    </div>
  );
}
