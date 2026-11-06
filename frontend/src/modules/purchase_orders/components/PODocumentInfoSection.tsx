import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import type { PartnerOption } from "@/hooks/usePartnerPicker";

/** The supplier field's id — the create-supplier layer returns focus to it. */
export const PO_PARTNER_FIELD_ID = "po-form-partner";

interface PODocumentInfoSectionProps {
  partnerId: string;
  partners: PartnerOption[];
  /** Hands the typed query to the server-side supplier lookup. */
  onPartnerSearch?: (query: string) => void;
  partnersLoading?: boolean;
  scheduledDate: string;
  notes: string;
  onPartnerChange: (id: string) => void;
  onScheduledDateChange: (date: string) => void;
  onNotesChange: (notes: string) => void;
  eyebrow: string;
  hint: string;
  partnerLabel: string;
  /** Shown under the field while no supplier is chosen. */
  partnerRequiredHint: string;
  selectPartnerPlaceholder: string;
  searchPartnerPlaceholder: string;
  noPartnersFoundMessage: string;
  scheduledDateLabel: string;
  /** Earliest selectable date (ISO `yyyy-MM-dd`) — a planned date cannot be in the past. */
  scheduledDateMin?: string;
  notesLabel: string;
  /** Opens the inline partner-create shortcut with the typed query. */
  onPartnerCreate?: (query: string) => void;
  createPartnerLabel?: string;
}

export function PODocumentInfoSection({
  partnerId,
  partners,
  onPartnerSearch,
  partnersLoading,
  scheduledDate,
  notes,
  onPartnerChange,
  onScheduledDateChange,
  onNotesChange,
  eyebrow,
  hint,
  partnerLabel,
  partnerRequiredHint,
  selectPartnerPlaceholder,
  searchPartnerPlaceholder,
  noPartnersFoundMessage,
  scheduledDateLabel,
  scheduledDateMin,
  notesLabel,
  onPartnerCreate,
  createPartnerLabel,
}: PODocumentInfoSectionProps) {
  return (
    <section className="rounded-2xl border border-border bg-surface-raised/40 p-4 sm:p-5">
      <div className="mb-4 space-y-1">
        <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
          {eyebrow}
        </p>
        <p className="text-sm text-on-secondary">{hint}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-4">
        <div className="space-y-1">
          <SearchableCombobox
            id={PO_PARTNER_FIELD_ID}
            label={partnerLabel}
            options={partners}
            onSearchChange={onPartnerSearch}
            loading={partnersLoading}
            value={partnerId}
            onChange={onPartnerChange}
            placeholder={selectPartnerPlaceholder}
            searchPlaceholder={searchPartnerPlaceholder}
            emptyMessage={noPartnersFoundMessage}
            title={partnerLabel}
            createLabel={createPartnerLabel}
            onCreateNew={onPartnerCreate}
          />
          {/* The rule lived on the receipt, three screens away, in English
. Say it where the supplier can still be picked. */}
          {!partnerId && (
            <p className="text-xs text-on-muted">{partnerRequiredHint}</p>
          )}
        </div>
        <DateInput
          label={scheduledDateLabel}
          value={scheduledDate}
          onChange={(e) => onScheduledDateChange(e)}
          min={scheduledDateMin}
        />
      </div>

      <Textarea
        wrapperClassName="mt-4"
        label={notesLabel}
        className="w-full h-24 rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-on placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed resize-none"
        value={notes}
        onChange={(e) => onNotesChange(e.target.value)}
      />
    </section>
  );
}
