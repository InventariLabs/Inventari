import type {
  DocumentLine,
  DocumentLineStatus,
} from "@/modules/warehouse/types";

/** What the status of a line is read from; quantities may be strings (the wire) or numbers (an edit in progress). */
type LineProgress = Pick<
  DocumentLine,
  "line_status" | "discrepancy_code" | "quantity"
> & {
  expected_quantity?: number | string | null;
  done_quantity?: number | string | null;
};

export function getDocumentLineStatus(
  line: LineProgress,
  documentStatus: string,
): DocumentLineStatus {
  if (line.line_status) {
    return line.line_status;
  }

  const expectedQuantity = Number(line.expected_quantity ?? line.quantity);
  const doneQuantity = Number(
    line.done_quantity ??
      (documentStatus === "DRAFT" || documentStatus === "CANCELLED"
        ? 0
        : expectedQuantity),
  );

  if (line.discrepancy_code) {
    return "EXCEPTION";
  }
  // Quantities ride the wire as decimal strings and become numbers above:
  // both sides as strings compare lexicographically ("3.000" >= "10.000"
  // is false), so the line reads as pending forever.
  if (doneQuantity >= expectedQuantity) {
    return "DONE";
  }
  if (doneQuantity > 0) {
    return "PARTIAL";
  }
  return "PENDING";
}

export function getDocumentLineStatusVariant(status: DocumentLineStatus) {
  switch (status) {
    case "DONE":
      return "success" as const;
    case "PARTIAL":
      return "info" as const;
    case "EXCEPTION":
      return "warning" as const;
    default:
      return "secondary" as const;
  }
}

/**
 * True when the lines' shortfall is a fact the reader has to see per line:
 * either a line has moved (so an untouched neighbour owes its own
 * "done 0"), or the document completed and a zero is the run's result, not
 * the absence of one. A draft or a cancelled document has no result yet,
 * and a column of zeros there is noise the status badge covers.
 */
export function documentHasExecution(document: {
  status: string;
  lines: Array<{
    quantity: number | string;
    expected_quantity?: number | string | null;
    done_quantity?: number | string | null;
  }>;
}): boolean {
  if (document.status === "COMPLETED") return true;
  return document.lines.some((line) => {
    const expectedQuantity = Number(line.expected_quantity ?? line.quantity);
    const doneQuantity = Number(
      line.done_quantity ??
        (document.status === "DRAFT" || document.status === "CANCELLED"
          ? 0
          : expectedQuantity),
    );
    return doneQuantity > 0;
  });
}
