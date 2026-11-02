/**
 * The code the server mints when an organization has no SKU pattern
 * (`STM-` plus eight random hex digits). Nobody chose it and nobody can
 * read it, so a screen has no reason to print it.
 */
const GENERATED_SKU = /^STM-[0-9A-F]{8}$/;

export function readableSku(sku: string | null | undefined): string | null {
  return sku && !GENERATED_SKU.test(sku) ? sku : null;
}
