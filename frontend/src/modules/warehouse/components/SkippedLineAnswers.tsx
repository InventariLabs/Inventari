import { Button } from "@/components/ui/Button";

/** What a skipped line can be answered with on a summary. */
export type SkipOutcome = "SHORTAGE" | "OTHER";

/** The words of the three buttons, in the namespace of the side showing them. */
export interface SkipAnswerLabels {
  undo: string;
  backorder: string;
  notSent: string;
}

interface Props {
  labels: SkipAnswerLabels;
  onUndo: () => void;
  onAnswer: (code: SkipOutcome) => void;
  /** Disables the answers while one is on its way. */
  isLoading?: boolean;
}

/**
 * Undo skip, Backorder and the closing answer, for one skipped line of a
 * finished session. Picking and receiving put the same three questions to
 * the person; only the words differ.
 */
export function SkippedLineAnswers({
  labels,
  onUndo,
  onAnswer,
  isLoading,
}: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={isLoading} onClick={onUndo}>
        {labels.undo}
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={isLoading}
        onClick={() => onAnswer("SHORTAGE")}
      >
        {labels.backorder}
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={isLoading}
        onClick={() => onAnswer("OTHER")}
      >
        {labels.notSent}
      </Button>
    </div>
  );
}
