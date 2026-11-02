import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";

/** The code whose note is not optional, in every list that has one. */
const FREE_TEXT_REASON_CODE = "OTHER";

interface Props<T extends string> {
  /** The question this list answers, already translated. */
  label: string;
  codes: readonly T[];
  /** The translated label for one code. */
  labelFor: (code: T) => string;
  code: T | "";
  onCodeChange: (code: T | "") => void;
  note: string;
  onNoteChange: (note: string) => void;
  /** Show the "this is missing" messages — set once the reader has tried. */
  showErrors: boolean;
  /** Names the two fields for tests: `<testId>-code`, `<testId>-note`. */
  testId: string;
  /** Marks the code as required. Off where nothing refuses a save without it. */
  required?: boolean;
}

/**
 * Why something happened: a code from a closed list, plus a note.
 *
 * The reason used to be one free-text box. It answered "what happened here"
 * and nothing else — no report could tell how often a correction is a
 * mistyped quantity rather than a wrong product, or how much of a shortage
 * is breakage rather than theft. The code answers that; the note stays for
 * what the list cannot say, and becomes the reason itself when the code is
 * "Other".
 *
 * Shared rather than owned by one module: corrections, returns and counted
 * differences all strike the same bargain, and a module may not reach into
 * another module's components. The labels arrive translated so this file
 * belongs to no namespace; only the words shared by every list — the
 * placeholder, the note, the two "this is missing" messages — are read here.
 */
export function ReasonCodeField<T extends string>({
  label,
  codes,
  labelFor,
  code,
  onCodeChange,
  note,
  onNoteChange,
  showErrors,
  testId,
  required = true,
}: Props<T>) {
  const { t } = useTranslation("common");
  const noteRequired = code === FREE_TEXT_REASON_CODE;
  const noteMissing = noteRequired && note.trim() === "";

  return (
    <div className="space-y-3">
      <NativeSelect
        label={label}
        aria-required={required}
        value={code}
        onChange={(e) => onCodeChange(e.target.value as T | "")}
        error={
          showErrors && code === "" ? t("reasons.codeRequired") : undefined
        }
        data-testid={`${testId}-code`}
      >
        <option value="" disabled>
          {t("reasons.placeholder")}
        </option>
        {codes.map((c) => (
          <option key={c} value={c}>
            {labelFor(c)}
          </option>
        ))}
      </NativeSelect>

      <Input
        label={t("reasons.note")}
        aria-required={noteRequired}
        placeholder={t("reasons.notePlaceholder")}
        value={note}
        onChange={(e) => onNoteChange(e.target.value)}
        error={
          showErrors && noteMissing ? t("reasons.noteRequired") : undefined
        }
        data-testid={`${testId}-note`}
      />
    </div>
  );
}

/** Whether the pair is complete enough to send. */
export function reasonIsComplete(code: string, note: string): boolean {
  if (code === "") return false;
  return code !== FREE_TEXT_REASON_CODE || note.trim() !== "";
}
