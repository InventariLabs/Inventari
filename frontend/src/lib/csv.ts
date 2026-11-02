import { downloadBlob } from "@/utils/helpers";

/**
 * One CSV writer for every screen that offers a download.
 *
 * The escaping rule was written out three times — documents, the audit log,
 * the stock-take report — and the anchor dance that saves the file three
 * more, next to the `downloadBlob` that has always done it. They had
 * already stopped agreeing: two wrote the byte-order mark that makes a
 * spreadsheet read UTF-8 names, the third did not, so exported audit
 * entries arrived with mangled accents.
 */

/**
 * A value as one CSV field: quoted only when it has to be.
 *
 * A quote inside a quoted field is doubled — that is the whole of RFC 4180
 * on the subject, and the reason a product named 12" Pan does not shift
 * every column after it.
 */
export function csvCell(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Rows into one CSV document, header row included by the caller. */
export function toCsv(rows: readonly (readonly unknown[])[]): string {
  return rows.map((row) => row.map(csvCell).join(",")).join("\n");
}

/**
 * Hand the reader a CSV file.
 *
 * The byte-order mark goes in front unconditionally: without it Excel reads
 * the file in the system code page, and every name with an accent in it
 * arrives broken.
 */
export function downloadCsv(content: string, filename: string): void {
  downloadBlob(
    new Blob(["﻿" + content], { type: "text/csv;charset=utf-8;" }),
    filename,
  );
}
