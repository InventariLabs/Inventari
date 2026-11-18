/**
 * The modules whose presence offers the organization the movement ledger.
 *
 * Every organization records its stock movements (ADR-004). The ledger tab and
 * the navigation entry show only where a module that reads them is on. Offering
 * the history to everyone is a product decision of its own, not a side effect
 * of keeping the ledger.
 *
 * The authority is the backend manifest flag `consumes_stock_quant`; this
 * list mirrors it and `test_which_modules_record_movements.py` fails if the
 * two drift apart.
 */
export const MOVEMENT_RECORDING_MODULES = [
  "warehouse",
  "maker",
  "purchase_orders",
  "stock_takes",
] as const;

/** Does this organization see the movement ledger? */
export function recordsMovements(enabledModules: string[]): boolean {
  return MOVEMENT_RECORDING_MODULES.some((name) =>
    enabledModules.includes(name),
  );
}
