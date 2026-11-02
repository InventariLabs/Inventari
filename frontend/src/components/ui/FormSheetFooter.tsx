import { Button } from "@/components/ui/Button";
import { SheetActions, SheetFooter } from "@/components/ui/Sheet";

/**
 * The action row of a form rendered inside a sheet or modal: an optional
 * line-count hint, a cancel button and a submit button with a pending state.
 *
 * One row is the whole footer (§4.3). Actions that belong to the record rather
 * than to this edit — delete, archive — go to the `ActionMenu` in the header;
 * they are not a second row here.
 *
 * Labels arrive via props so the component stays generic — consumers
 * translate them at the call site. Layout is owned by SheetFooter /
 * SheetActions per UI_GUIDELINES §4.3; this component only adds the
 * line-count hint (: previously two byte-level copies lived in the
 * purchase_orders and documents modules).
 *
 * While pending, the submit Button renders its spinner in place of the
 * label — that is the Button's isLoading contract, so no pending-label
 * prop is needed.
 */
export interface FormSheetFooterProps {
  isPending: boolean;
  /** Line count shown as the left-aligned hint; 0 hides the hint. */
  lineCount: number;
  /** Label of the line-count hint; ignored when lineCount is 0. */
  lineCountText?: string;
  cancelText: string;
  /** Label of the submit button. */
  submitText: string;
  /** Blocks submission while the form is incomplete. */
  submitDisabled?: boolean;
  onCancel: () => void;
  onSubmit: (event: React.FormEvent) => void;
}

export function FormSheetFooter({
  isPending,
  lineCount,
  lineCountText,
  cancelText,
  submitText,
  submitDisabled = false,
  onCancel,
  onSubmit,
}: FormSheetFooterProps) {
  return (
    <SheetFooter>
      <SheetActions>
        {lineCount > 0 && (
          <span className="text-xs text-on-secondary mr-auto hidden sm:inline">
            {lineCountText}
          </span>
        )}
        <Button type="button" variant="outline" onClick={onCancel}>
          {cancelText}
        </Button>
        <Button
          type="button"
          isLoading={isPending}
          disabled={submitDisabled}
          onClick={(e) => onSubmit(e as React.FormEvent)}
        >
          {submitText}
        </Button>
      </SheetActions>
    </SheetFooter>
  );
}
