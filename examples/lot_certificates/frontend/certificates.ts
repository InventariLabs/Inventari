import { api } from "@/module-sdk";
import type { DocumentMetaData, DocumentView } from "@/module-sdk";

export const MODULE = "lot_certificates";

/** The longest number the register keeps (the server refuses a longer one). */
export const NUMBER_MAX_LENGTH = 100;

/**
 * The number this module wrote on a line, or null when it wrote none.
 *
 * A blank number is none; any other is read as written, the way the server's
 * receiving rule and its register read it.
 */
export function certificateNumber(metaData: DocumentMetaData): string | null {
  const number = metaData[MODULE]?.number;
  return typeof number === "string" && number.trim() ? number : null;
}

/** Every certificate a document's lines name, each once. */
export function certificateNumbers(doc: DocumentView): string[] {
  const numbers = doc.lines
    .map((line) => certificateNumber(line.metaData))
    .filter((number): number is string => number !== null);
  return [...new Set(numbers)];
}

/** Put the numbers on file; answers the ones this call filed. */
export async function fileCertificates(numbers: string[]): Promise<string[]> {
  const response = await api.post<{ filed: string[] }>(
    "/lot-certificates/certificates",
    { numbers },
  );
  return response.data.filed;
}
