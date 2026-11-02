import { useCallback, useState } from "react";
import type { DocumentMetaData, SetMetaData } from "@/lib/moduleRegistry";
import {
  sentMetaData,
  withModuleValues,
  type ReceiptDraftLine,
} from "@/modules/warehouse/components/documentFormShared";
import { useDocumentMetaData } from "@/modules/warehouse/hooks/useDocumentMetaData";
import { reasonIsComplete } from "@/modules/shared/components/ReasonCodeField";
import type { ScrapReasonCode } from "@/modules/warehouse/reasonCodes";
import type {
  DocumentCreate,
  DocumentType,
  DocumentLineCreate,
  DocumentUpdate,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/** A scrap's reason as the form holds it: the stored code, or none yet. */
function useScrapReason(document?: WarehouseDocument) {
  return useState<ScrapReasonCode | "">(
    (document?.reason_code as ScrapReasonCode | null | undefined) ?? "",
  );
}

let lineKeyCounter = 0;
function nextLineKey(): string {
  return `line-${++lineKeyCounter}-${Date.now()}`;
}

interface UseDocumentWorkspaceStateOptions {
  document?: WarehouseDocument;
  initialType?: string;
  /** The shelf a new document starts on, when it was opened from one. */
  initialSourceLocationId?: string;
  /** Lines a new document starts with — the goods a decision is about. */
  initialLines?: DocumentInitialLine[];
  /** When false (Partners module disabled) the partner field is optional. */
  partnersEnabled?: boolean;
}

const EMPTY_LINE: Omit<ReceiptDraftLine, "_key"> = {
  item_id: undefined,
  name: "",
  quantity: 1,
  uom_id: null,
  batch_number: "",
  expiry_date: "",
  notes: "",
  unit_price: "",
  tax_rate: "",
};

/**
 * The blank row a new form opens with, still untouched: no product chosen
 * and nothing typed into any other field. A row with only a quantity or a
 * price entered is somebody's work and stays.
 */
function isPlaceholderLine(line: ReceiptDraftLine): boolean {
  return (
    !line.item_id &&
    !line.product_template_id &&
    !line.name.trim() &&
    Number(line.quantity) === EMPTY_LINE.quantity &&
    !line.uom_id &&
    !line.batch_number &&
    !line.expiry_date &&
    !line.notes &&
    !line.unit_price &&
    !line.tax_rate
  );
}

/** A line has arrived: the untouched blank row it was meant to replace goes. */
function withoutPlaceholders(lines: ReceiptDraftLine[]): ReceiptDraftLine[] {
  return lines.filter((line) => !isPlaceholderLine(line));
}

type SavedLine = WarehouseDocument["lines"][number];

/** What a new form may start its lines with: the goods a decision names. */
export type DocumentInitialLine = LineSource;

/** The lines a new form opens with: the document's own, the goods a caller
 * handed in, or one blank row. */
function startingLines(
  document: WarehouseDocument | undefined,
  initialLines: DocumentInitialLine[] | undefined,
): ReceiptDraftLine[] {
  if (document?.lines) return document.lines.map(mapDocumentLineToReceiptLine);
  if (initialLines && initialLines.length > 0) {
    return initialLines.map(mapDocumentLineToReceiptLine);
  }
  return [{ _key: nextLineKey(), ...EMPTY_LINE }];
}

/** What a line read back from the server carries: a saved document's, or one an import read. */
type LineSource = Pick<SavedLine, "quantity"> &
  Partial<
    Pick<
      SavedLine,
      | "item_id"
      | "product_template_id"
      | "name"
      | "brand"
      | "barcode"
      | "sku"
      | "uom_id"
      | "batch_number"
      | "serial_number"
      | "expiry_date"
      | "notes"
      | "unit_price"
      | "tax_rate"
      | "meta_data"
    >
  >;

function mapDocumentLineToReceiptLine(line: LineSource): ReceiptDraftLine {
  return {
    _key: nextLineKey(),
    item_id: line.item_id ?? undefined,
    product_template_id: line.product_template_id ?? undefined,
    name: line.name ?? "",
    brand: line.brand ?? undefined,
    barcode: line.barcode ?? undefined,
    sku: line.sku ?? undefined,
    image_url: undefined,
    // The wire carries a Decimal as text (the generated schema says
    // `quantity: string`); this module's hand-written type says `number`,
    // so nothing objected when the consolidation below added two of them
    // and got "2.0003" out of two and three. The conversion belongs here,
    // at the one door a document's lines come through.
    quantity: Number(line.quantity) || 0,
    uom_id: line.uom_id ?? null,
    batch_number: line.batch_number ?? "",
    serial_number: line.serial_number ?? undefined,
    expiry_date: line.expiry_date ?? "",
    notes: line.notes ?? "",
    unit_price: line.unit_price ?? "",
    tax_rate: line.tax_rate ?? "",
    // Other modules' fields ride along, or saving the draft would erase them.
    meta_data: line.meta_data ?? undefined,
  };
}

function mapReceiptLineToPayload(line: ReceiptDraftLine): DocumentLineCreate {
  return {
    item_id: line.item_id || undefined,
    product_template_id: line.product_template_id || undefined,
    name: line.name || undefined,
    brand: line.brand || undefined,
    barcode: line.barcode || undefined,
    sku: line.sku || undefined,
    expected_quantity: Number(line.quantity),
    uom_id: line.uom_id ?? undefined,
    batch_number: line.batch_number || undefined,
    serial_number: line.serial_number || undefined,
    expiry_date: line.expiry_date || undefined,
    notes: line.notes || undefined,
    unit_price: line.unit_price || undefined,
    tax_rate: line.tax_rate || undefined,
    meta_data: sentMetaData(line.meta_data),
  };
}

/** *lines* with one module's values written onto the line keyed *key*. */
function withLineMetaData(
  lines: ReceiptDraftLine[],
  key: string,
  ...[module, values]: Parameters<SetMetaData>
): ReceiptDraftLine[] {
  return lines.map((line) =>
    line._key === key
      ? { ...line, meta_data: withModuleValues(line.meta_data, module, values) }
      : line,
  );
}

function sameMetaData(a?: DocumentMetaData, b?: DocumentMetaData): boolean {
  return JSON.stringify(a ?? {}) === JSON.stringify(b ?? {});
}

/**
 * Whether *line* folds into *kept* when the lines are consolidated: the same
 * record, product or typed name, and the same traceability, value and other
 * modules' fields — two lots, two prices or two certificates stay two lines.
 */
function consolidatesWith(kept: ReceiptDraftLine, line: ReceiptDraftLine) {
  const sameItem = line.item_id && kept.item_id === line.item_id;
  const sameTemplate =
    !line.item_id &&
    !kept.item_id &&
    line.product_template_id &&
    kept.product_template_id === line.product_template_id;
  const sameName =
    !line.item_id &&
    !kept.item_id &&
    !line.product_template_id &&
    !kept.product_template_id &&
    line.name.trim() &&
    kept.name.trim() === line.name.trim();

  if (!sameItem && !sameTemplate && !sameName) return false;

  return (
    kept.batch_number === line.batch_number &&
    kept.expiry_date === line.expiry_date &&
    kept.unit_price === line.unit_price &&
    kept.tax_rate === line.tax_rate &&
    kept.uom_id === line.uom_id &&
    sameMetaData(kept.meta_data, line.meta_data)
  );
}

/**
 * Goods coming in go into stock as a product on the list: a line typed by
 * hand is made a product before the receipt is saved. Mirrors the receipt
 * types of `is_receipt` in document_types.py.
 */
const RECEIPT_TYPES: ReadonlySet<string> = new Set(["IN", "INTERNAL_IN"]);

/** A line made a product takes the typed line's place and keeps its price. */
function withLineReplaced(
  lines: ReceiptDraftLine[],
  key: string,
  made: ReceiptDraftLine,
): ReceiptDraftLine[] {
  return lines.map((line) =>
    line._key === key
      ? {
          ...made,
          _key: key,
          unit_price: line.unit_price,
          tax_rate: line.tax_rate,
        }
      : line,
  );
}

export function useDocumentWorkspaceState({
  document,
  initialType,
  initialSourceLocationId,
  initialLines,
  partnersEnabled = true,
}: UseDocumentWorkspaceStateOptions) {
  const isEdit = !!document;

  // The type is chosen before the workspace opens (the "New document" menu)
  // and never changes inside it — except on the issue screen, which asks what
  // the goods are for and picks the type from the answer. Its lines name
  // stock records under every type it offers, so they survive the change.
  const [docType, setDocType] = useState<DocumentType>(
    // The contract types a document's type as a plain string; the server only sends the members.
    (document?.type ?? initialType ?? "IN") as DocumentType,
  );
  const [partnerId, setPartnerId] = useState(document?.partner_id ?? "");
  const [sourceLocationId, setSourceLocationId] = useState(
    document?.source_location_id ?? initialSourceLocationId ?? "",
  );
  const [targetLocationId, setTargetLocationId] = useState(
    document?.target_location_id ?? "",
  );
  const [scheduledDate, setScheduledDate] = useState(
    document?.scheduled_date ?? "",
  );
  const [notes, setNotes] = useState(document?.notes ?? "");
  const [reasonCode, setReasonCode] = useScrapReason(document);
  const [externalReference, setExternalReference] = useState(
    document?.external_reference ?? "",
  );
  const [lines, setLines] = useState<ReceiptDraftLine[]>(() =>
    startingLines(document, initialLines),
  );
  const { metaData, setMetaData } = useDocumentMetaData(document);

  const requiresSource =
    docType === "OUT" || docType === "INT" || docType === "INTERNAL_OUT";
  const requiresTarget =
    docType === "IN" || docType === "INT" || docType === "INTERNAL_IN";
  const requiresPartner =
    (docType === "IN" || docType === "OUT") && partnersEnabled;
  // Anything that takes goods off a shelf names a specific record — the
  // stock executor moves stock by record and refuses a line without one.
  // These are the types whose line search offers the stock standing in the
  // source location rather than the product catalogue. Transfer and scrap
  // were missing: their search answered with catalogue entries, so the form
  // produced documents their own executors could not carry out — a transfer
  // that refused at the last step, and a scrap that quietly moved nothing
  // and closed as done. Mirrors `requires_stock_row` in document_types.py.
  const requiresItemId =
    docType === "OUT" ||
    docType === "INTERNAL_OUT" ||
    docType === "INT" ||
    docType === "SCRAP";

  const linesNameAProduct = RECEIPT_TYPES.has(docType);

  // A dispatch and a scrap pull across the records on a shelf, so their
  // picker may fold identical records into one row. A transfer moves the
  // single record the line names and would leave its twin behind.
  const splitsAcrossRecords =
    docType === "OUT" || docType === "INTERNAL_OUT" || docType === "SCRAP";

  const appendLine = useCallback((line: ReceiptDraftLine) => {
    setLines((prev) => [
      ...(isPlaceholderLine(line) ? prev : withoutPlaceholders(prev)),
      line,
    ]);
  }, []);

  const addOrIncrementLine = useCallback((line: ReceiptDraftLine) => {
    setLines((prev) => {
      const existingIndex = prev.findIndex((c) => {
        if (line.item_id && c.item_id === line.item_id) return true;
        if (
          !line.item_id &&
          !c.item_id &&
          line.product_template_id &&
          c.product_template_id === line.product_template_id &&
          c.batch_number === line.batch_number &&
          c.expiry_date === line.expiry_date &&
          c.unit_price === line.unit_price &&
          c.tax_rate === line.tax_rate &&
          c.uom_id === line.uom_id
        ) {
          return true;
        }
        return false;
      });

      if (existingIndex < 0) {
        return [...withoutPlaceholders(prev), line];
      }

      return prev.map((currentLine, index) =>
        index === existingIndex
          ? {
              ...currentLine,
              // Both sides through Number(): the line in state came from
              // the door above, but a caller may hand this one a quantity
              // straight off a response of its own.
              quantity:
                Number(currentLine.quantity) + (Number(line.quantity) || 1),
            }
          : currentLine,
      );
    });
  }, []);

  const addEmptyLine = useCallback(() => {
    appendLine({ _key: nextLineKey(), ...EMPTY_LINE });
  }, [appendLine]);

  const removeLine = useCallback((index: number) => {
    setLines((prev) => prev.filter((_, lineIndex) => lineIndex !== index));
  }, []);

  const setLineMetaData = useCallback(
    (key: string, ...change: Parameters<SetMetaData>) =>
      setLines((prev) => withLineMetaData(prev, key, ...change)),
    [],
  );

  const updateLine = useCallback(
    (index: number, updates: Partial<ReceiptDraftLine>) => {
      setLines((prev) =>
        prev.map((line, lineIndex) =>
          lineIndex === index ? { ...line, ...updates } : line,
        ),
      );
    },
    [],
  );

  const replaceLine = useCallback(
    (key: string, made: ReceiptDraftLine) =>
      setLines((prev) => withLineReplaced(prev, key, made)),
    [],
  );

  const toCreatePayload = useCallback((): DocumentCreate => {
    const cleanLines = lines.map(mapReceiptLineToPayload);

    return {
      type: docType,
      partner_id: partnerId || undefined,
      source_location_id: sourceLocationId || undefined,
      target_location_id: targetLocationId || undefined,
      scheduled_date: scheduledDate || undefined,
      lines: cleanLines,
      notes: notes || undefined,
      external_reference: externalReference || undefined,
      meta_data: sentMetaData(metaData),
      ...(docType === "SCRAP" && reasonCode ? { reason_code: reasonCode } : {}),
    };
  }, [
    docType,
    externalReference,
    lines,
    metaData,
    notes,
    reasonCode,
    partnerId,
    scheduledDate,
    sourceLocationId,
    targetLocationId,
  ]);

  const toUpdatePayload = useCallback((): DocumentUpdate => {
    const cleanLines = lines.map(mapReceiptLineToPayload);

    // An empty field the user emptied is a clearing instruction, and a null
    // is how the wire spells one (backend AGENTS.md §2b). Turning it into
    // undefined dropped the key, so the save answered "updated" over a value
    // that never changed.
    return {
      partner_id: partnerId || null,
      source_location_id: sourceLocationId || null,
      target_location_id: targetLocationId || null,
      scheduled_date: scheduledDate || null,
      notes: notes || null,
      external_reference: externalReference || null,
      meta_data: metaData,
      lines: cleanLines,
      ...(docType === "SCRAP" ? { reason_code: reasonCode || null } : {}),
    };
  }, [
    docType,
    externalReference,
    lines,
    metaData,
    notes,
    reasonCode,
    partnerId,
    scheduledDate,
    sourceLocationId,
    targetLocationId,
  ]);

  /**
   * `partnerOffered` is whether the picker can offer the partner held — the
   * role set and the active flag. A required field holding one it cannot
   * offer shows its placeholder, and validation has to call it empty the way
   * the reader sees it, not the way the state does. Left out (or while still
   * unknown) the check reads the id alone.
   */
  const validateForm = useCallback(
    (partnerOffered?: boolean): Record<string, string> => {
      const errors: Record<string, string> = {};

      const partnerMissing = !partnerId || partnerOffered === false;
      if (requiresPartner && partnerMissing) {
        errors.partner_id = "errors.partnerRequired";
      }
      if (requiresSource && !sourceLocationId) {
        errors.source_location_id = "errors.sourceLocationRequired";
      }
      if (requiresTarget && !targetLocationId) {
        errors.target_location_id = "errors.targetLocationRequired";
      }
      if (docType === "SCRAP" && !reasonIsComplete(reasonCode, notes)) {
        errors.reason_code = "reasons.codeRequired";
      }

      lines.forEach((line) => {
        if (requiresItemId && !line.item_id) {
          errors[`line.${line._key}.item_id`] =
            "errors.itemIdRequiredForDispatch";
          return;
        }
        if (!line.item_id && !line.name.trim()) {
          errors[`line.${line._key}.name`] = "errors.lineNameRequired";
        } else if (
          linesNameAProduct &&
          !line.item_id &&
          !line.product_template_id
        ) {
          errors[`line.${line._key}.name`] = "errors.lineNeedsProduct";
        }
        // the server rejects a line of zero — say so on the field the
        // reader has to fix, instead of after a round trip and a toast.
        if (!(Number(line.quantity) > 0)) {
          errors[`line.${line._key}.quantity`] = "errors.lineQuantityPositive";
        }
      });

      return errors;
    },
    [
      docType,
      lines,
      linesNameAProduct,
      notes,
      partnerId,
      reasonCode,
      requiresItemId,
      requiresPartner,
      requiresSource,
      requiresTarget,
      sourceLocationId,
      targetLocationId,
    ],
  );

  const consolidateLines = useCallback(() => {
    setLines((prev) => {
      const consolidated: ReceiptDraftLine[] = [];

      for (const line of prev) {
        if (!line.name.trim() && !line.item_id && !line.product_template_id) {
          consolidated.push(line);
          continue;
        }

        const existingIndex = consolidated.findIndex((kept) =>
          consolidatesWith(kept, line),
        );

        if (existingIndex >= 0) {
          consolidated[existingIndex] = {
            ...consolidated[existingIndex],
            quantity:
              Number(consolidated[existingIndex].quantity) +
              Number(line.quantity),
            notes:
              [consolidated[existingIndex].notes, line.notes]
                .filter(Boolean)
                .join("; ") || "",
          };
        } else {
          consolidated.push(line);
        }
      }

      return consolidated;
    });
  }, []);

  /** Take the lines the server has now, discarding the ones on screen.
   *
   * The line import writes straight to the document, beside this form. The
   * form went on showing the lines it opened with — and saving sends the
   * whole list, so "Save" after an import deleted every imported line and
   * put the one stale row back. Reloading is the only reading of "Save"
   * that does not lose work somebody just did.
   */
  const replaceLinesFrom = useCallback((source: WarehouseDocument) => {
    setLines(
      source.lines?.map(mapDocumentLineToReceiptLine) ?? [
        { _key: nextLineKey(), ...EMPTY_LINE },
      ],
    );
  }, []);

  /** Add the lines an import read for a document not saved yet.
   *
   * They join the lines already typed; the blank line the form opens with
   * gives way, or every import would start with an empty row to delete.
   */
  const appendImportedLines = useCallback((imported: LineSource[]) => {
    setLines((prev) => [
      ...prev.filter(
        (line) =>
          !!line.item_id || !!line.name.trim() || !!line.barcode?.trim(),
      ),
      ...imported.map(mapDocumentLineToReceiptLine),
    ]);
  }, []);

  return {
    isEdit,
    docType,
    partnerId,
    sourceLocationId,
    targetLocationId,
    scheduledDate,
    notes,
    scrapReason: { code: reasonCode, setCode: setReasonCode },
    externalReference,
    lines,
    metaData,
    setMetaData,
    setLineMetaData,
    requiresSource,
    requiresTarget,
    requiresPartner,
    requiresItemId,
    splitsAcrossRecords,
    linesNameAProduct,
    replaceLine,
    setDocType,
    hasLines: lines.length > 0,
    setPartnerId,
    setSourceLocationId,
    setTargetLocationId,
    setScheduledDate,
    setNotes,
    setExternalReference,
    appendLine,
    addOrIncrementLine,
    replaceLinesFrom,
    appendImportedLines,
    consolidateLines,
    addEmptyLine,
    removeLine,
    updateLine,
    toCreatePayload,
    toUpdatePayload,
    validateForm,
  };
}

export type DocumentWorkspace = ReturnType<typeof useDocumentWorkspaceState>;
