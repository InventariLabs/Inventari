import { toast } from "sonner";
import i18n from "@/i18n/config";
import { ReadableError } from "@/lib/errors";

const DEFAULT_MAX_SIZE = 10 * 1024 * 1024; // 10 MB

/**
 * The cap every interface image shares: the product photo, the
 * organization logo, the recipe cover. It is hand-synced with the backend
 * routes' own caps — there is no API that would hand the browser its
 * limits — and the pin tests on both sides name this exact number. Change
 * both in one review or neither.
 */
export const IMAGE_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;

/**
 * What a file picker for an attachment offers — the item's file field and
 * the equipment record's papers. Hand-synced with the one type list the
 * backend accepts (`ATTACHMENT_CONTENT_TYPES` in
 * `backend/app/core/upload_validation.py`): no `.doc`, which the server
 * refuses. `image/*` rather than four extensions keeps the phone's camera
 * on offer; the server still decides which images pass.
 */
export const ATTACHMENT_FILE_ACCEPT = "image/*,.pdf,.txt,.zip,.docx,.xls,.xlsx";

/**
 * Whether the file is small enough, and a toast saying so when it is not.
 *
 * The message goes through i18n rather than a template literal: this runs
 * outside a component, so there is no `useTranslation` to reach for, and the
 * hardcoded sentence was English on every screen in every language.
 */
export function validateFileSize(
  file: File,
  maxSize = DEFAULT_MAX_SIZE,
): boolean {
  if (file.size > maxSize) {
    toast.error(tooLarge(maxSize));
    return false;
  }
  return true;
}

/**
 * The same check for a request that cannot go ahead: the refusal is thrown,
 * not toasted. Every caller of an upload already catches its failure and
 * toasts `extractApiError(error, fallback)`; a gate that toasted too put a
 * second, generic toast on top of the one with the limit. A `ReadableError`
 * makes the caller's single toast the one that says the limit.
 */
export function assertFileSize(file: File, maxSize = DEFAULT_MAX_SIZE): void {
  if (file.size > maxSize) throw new ReadableError(tooLarge(maxSize));
}

function tooLarge(maxSize: number): string {
  const maxMB = (maxSize / (1024 * 1024)).toFixed(0);
  return i18n.t("common:errors.fileTooLarge", { maxMB });
}
