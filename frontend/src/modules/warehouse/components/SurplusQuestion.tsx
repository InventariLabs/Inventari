import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

/**
 * A surplus the server asked about before writing it.
 *
 * Past the over-receipt tolerance a holder of the permission is asked, not
 * refused: the server names the surplus and the line it lands on, writes
 * nothing, and takes the same call again once it carries the answer.
 * *resend* is that call.
 */
interface SurplusQuestion {
  message: string;
  resend: () => unknown;
}

/** What the receiving session answers when a count needs the worker's yes. */
const SURPLUS_ASKED = "needs_surplus_confirmation";

/**
 * The question and its dialog, for a screen that sends counts.
 *
 * ``ask`` puts the server's sentence in front of the reader; yes clears it
 * and sends the call again. ``askIf`` does so when a session's answer is
 * that question, and says whether it was.
 */
export function useSurplusQuestion() {
  const [question, setQuestion] = useState<SurplusQuestion | null>(null);
  const ask = useCallback(
    (message: string, resend: () => unknown) =>
      setQuestion({
        message,
        resend: () => {
          setQuestion(null);
          return resend();
        },
      }),
    [],
  );
  const askIf = useCallback(
    (
      answer: { status: string; message: string } | null,
      resend: () => unknown,
    ): boolean => {
      if (answer?.status !== SURPLUS_ASKED) return false;
      ask(answer.message, resend);
      return true;
    },
    [ask],
  );
  const dialog = (
    <SurplusQuestionDialog
      question={question}
      onCancel={() => setQuestion(null)}
    />
  );
  return { ask, askIf, dialog };
}

/** The question, with the server's own sentence and one way to say yes. */
function SurplusQuestionDialog({
  question,
  onCancel,
}: {
  question: SurplusQuestion | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <ConfirmDialog
      open={question !== null}
      title={t("surplusQuestion.title")}
      message={question?.message ?? ""}
      confirmLabel={t("surplusQuestion.confirm")}
      variant="warning"
      onConfirm={() => question?.resend()}
      onCancel={onCancel}
    />
  );
}
