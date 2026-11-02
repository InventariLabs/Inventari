type Translate = (key: string, options?: Record<string, unknown>) => string;

/**
 * The identifier a draft carries until confirmation gives it its number:
 * `DRAFT-` and eleven hex characters, the last one a letter (see
 * `temporary_number` in the backend). A number the register issues ends on a
 * digit, so the shape never catches one.
 */
const DRAFT_IDENTIFIER = /^DRAFT-[0-9A-F]{11}[A-F]$/;

/**
 * What a document is called on screen. A confirmed document is its number; a
 * draft has none yet, and its raw identifier ("DRAFT-3CB4B1BD5F1C") reads as
 * an error. The draft is named by its kind instead, with the tail of the
 * identifier so two drafts of one kind in a list stay apart.
 */
export function documentTitle(
  t: Translate,
  doc: { number: string; type: string },
): string {
  if (!DRAFT_IDENTIFIER.test(doc.number)) return doc.number;
  return t("warehouse:draftTitle", {
    type: t(`warehouse:types.${doc.type}`, { defaultValue: doc.type }),
    suffix: doc.number.slice(-4),
  });
}
