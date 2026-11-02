import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";

/**
 * Run an async action with automatic success/error toasts.
 *
 * Replaces the repeated pattern:
 *   try {
 *     await doSomething();
 *     toast.success(t("successMessage"));
 *   } catch (err) {
 *     toast.error(extractApiError(err, t("unknownError")));
 *   }
 *
 * Returns the resolved value, or `undefined` when the action failed.
 *
 * @param fn - The async action to run.
 * @param opts.success - Optional success toast message (omitted when not needed).
 * @param opts.errorFallback - Fallback message for the error toast.
 */
export async function runWithToast<T>(
  fn: () => Promise<T>,
  opts: { success?: string; errorFallback: string },
): Promise<T | undefined> {
  try {
    const result = await fn();
    if (opts.success) {
      toast.success(opts.success);
    }
    return result;
  } catch (err) {
    toast.error(extractApiError(err, opts.errorFallback));
    return undefined;
  }
}
