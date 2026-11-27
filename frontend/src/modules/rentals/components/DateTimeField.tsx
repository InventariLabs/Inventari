import { useTranslation } from "react-i18next";

import { DateInput, Input, FIELD_LABEL_CLASS } from "@/module-sdk";

/**
 * A day and a time as two fields.
 *
 * The shared date field carries the day; the time is a native `time` input,
 * because the app has no date-time control and a native `datetime-local` would
 * read in the browser's zone rather than the organization's. The page that
 * uses this turns the pair into an instant with `wallTimeToIso`.
 */
export function DateTimeField({
  id,
  label,
  date,
  time,
  onDateChange,
  onTimeChange,
  error,
}: {
  id: string;
  label: string;
  date: string;
  time: string;
  onDateChange: (value: string) => void;
  onTimeChange: (value: string) => void;
  error?: string;
}) {
  const { t } = useTranslation("rentals");
  return (
    <div className="flex flex-col gap-1">
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      <div className="grid grid-cols-2 items-end gap-2">
        <DateInput
          value={date}
          onChange={onDateChange}
          aria-label={t("form.dateOf", { label })}
        />
        <Input
          id={id}
          type="time"
          value={time}
          onChange={(event) => onTimeChange(event.target.value)}
          aria-label={t("form.timeOf", { label })}
          error={error}
        />
      </div>
    </div>
  );
}
