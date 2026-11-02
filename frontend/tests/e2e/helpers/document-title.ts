/**
 * What a document is called on screen. A confirmed document reads as its
 * number; a draft has none yet, and its raw identifier ("DRAFT-3CB4B1BD5F1C")
 * never reaches the screen: it reads as its kind and the identifier's tail,
 * "Transfer – draft 5F1C". Finds a document by the words a reader sees.
 */
export function shownTitle(doc: { number: string }): string | RegExp {
  return doc.number.startsWith("DRAFT-")
    ? new RegExp(`draft ${doc.number.slice(-4)}`)
    : doc.number;
}
