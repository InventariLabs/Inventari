import type {
  DocumentCreate,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/** A press: the body that identifies it and the key the server remembers. */
export type Press = { key: string; body: string };

/**
 * Send a press under the key the server remembers for it. The key lives as
 * long as the answer is owed — a retry after a lost answer is answered with
 * the document the first send made — and is retired once the answer is here,
 * so the same goods handed over again are a new delivery, not a retry.
 */
export async function sendOnePress(
  press: { current: Press | null },
  data: DocumentCreate,
  send: (key: string) => Promise<WarehouseDocument>,
): Promise<WarehouseDocument> {
  const body = JSON.stringify(data);
  if (press.current?.body !== body) {
    press.current = { key: crypto.randomUUID(), body };
  }
  const answer = await send(press.current.key);
  press.current = null;
  return answer;
}
