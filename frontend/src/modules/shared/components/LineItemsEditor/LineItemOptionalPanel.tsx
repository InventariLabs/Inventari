import { CalendarPlus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import type { LineItem, LineItemsEditorLabels } from "./types";

interface LineItemOptionalPanelProps {
  index: number;
  line: LineItem;
  expiryFieldOpen: boolean;
  labels: LineItemsEditorLabels;
  testId?: string;
  onUpdate: (updates: Partial<LineItem>) => void;
  onExpiryToggle: () => void;
}

export function LineItemOptionalPanel({
  index,
  line,
  expiryFieldOpen,
  labels,
  testId,
  onUpdate,
  onExpiryToggle,
}: LineItemOptionalPanelProps) {
  const batchFieldId = `line-item-${index}-batch`;
  const expiryFieldId = `line-item-${index}-expiry`;
  const notesFieldId = `line-item-${index}-notes`;

  return (
    <div
      data-testid={testId}
      className="mt-3 rounded-xl border border-border bg-surface-raised/35 p-3 sm:p-4"
    >
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[180px_180px_minmax(0,1fr)] xl:items-start">
        <Input
          id={`line-item-${index}-sku`}
          type="text"
          label="SKU"
          value={line.sku ?? ""}
          onChange={(event) => onUpdate({ sku: event.target.value })}
          placeholder="-"
          className="h-10 px-2 font-mono"
        />
        <Input
          id={batchFieldId}
          type="text"
          label={labels.batchNumber}
          value={line.batch_number ?? ""}
          onChange={(event) => onUpdate({ batch_number: event.target.value })}
          placeholder="-"
          className="h-10 px-2"
        />
        <Input
          id={`line-item-${index}-serial`}
          type="text"
          label={labels.serialNumber}
          value={line.serial_number ?? ""}
          onChange={(event) => onUpdate({ serial_number: event.target.value })}
          placeholder="-"
          className="h-10 px-2"
        />

        {/* The expiry column is a field like the ones beside it: label on the
            same line as SKU / Notes, control on the same line as theirs. The
            bordered card it used to be started and ended between those lines,
            so nothing in the row lined up. */}
        <div className="space-y-1.5">
          {expiryFieldOpen ? (
            <>
              <DateInput
                id={expiryFieldId}
                label={labels.expiryDate}
                value={line.expiry_date ?? ""}
                onChange={(value) => onUpdate({ expiry_date: value })}
                presets={["plus1Week", "plus1Month", "plus6Months"]}
              />
              <Button
                type="button"
                variant="ghost"
                size="contentSm"
                onClick={onExpiryToggle}
                className="px-1 py-0 text-xs font-medium"
              >
                {labels.hideExpiryField}
              </Button>
            </>
          ) : (
            <>
              <span className="block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide">
                {labels.expiryDate}
              </span>
              <Button
                type="button"
                variant="outline"
                onClick={onExpiryToggle}
                leftIcon={<CalendarPlus size={14} />}
                className="w-full justify-start border-dashed px-3 text-xs font-medium"
              >
                {labels.showExpiryField}
              </Button>
              {labels.expiryFieldHiddenHint && (
                <p className="ml-1 text-xs text-on-secondary">
                  {labels.expiryFieldHiddenHint}
                </p>
              )}
            </>
          )}
        </div>

        <div className="space-y-1 xl:col-span-2">
          <Textarea
            id={notesFieldId}
            label={labels.notes}
            value={line.notes ?? ""}
            onChange={(event) => onUpdate({ notes: event.target.value })}
            rows={3}
            className="min-h-[96px] w-full resize-y rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-on placeholder:text-on-muted focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
          />
        </div>
      </div>
    </div>
  );
}
