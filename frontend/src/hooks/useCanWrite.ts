/**
 * "May this account change anything in this module?"
 *
 * Every module of this application names its permissions the same way —
 * `<module>:read` and `<module>:write`. That regularity is what makes a shared
 * answer possible: a page asks about its own module by name and does not have
 * to know which key spells the right. A page whose buttons reach a Core
 * register asks about that register instead (`categories`, `storages`), since
 * that is the key the API will check on the other end.
 *
 * Written because the same defect was found in three modules at once. The
 * backend refused a read-only account every write it tried — correctly, with a
 * translated message — while the screens went on offering the full write
 * surface. Fourteen check-in buttons, eight bulk actions, every modal opening
 * and filling to the end, and the refusal arriving only after the submit. The
 * moment was the bug, not the message.
 *
 * `useHasPermission` keeps the admin bypass and its "not loaded yet" rule, so
 * a page that mounts before /auth/me resolves does not flash a denial it
 * cannot support.
 */
import { useHasPermission } from "@/hooks/useHasPermission";

/** True when the account may create, change or remove things in *moduleName*. */
export function useCanWrite(moduleName: string): boolean {
  return useHasPermission(`${moduleName}:write`);
}

/**
 * True when the account may change how *moduleName* behaves.
 *
 * Only for modules that declare a `:manage` key of their own — `warehouse`
 * and `purchase_orders` do, and their backends check exactly that key.
 * Asking it of a module without one denies everybody but an administrator,
 * which is a different rule than the module wrote down.
 */
export function useCanManage(moduleName: string): boolean {
  return useHasPermission(`${moduleName}:manage`);
}
