import { useCallback, useRef } from "react";
import {
  useMutation,
  useQueryClient,
  type MutateFunction,
  type MutateOptions,
  type QueryClient,
  type UseMutationOptions,
  type UseMutationResult,
  type UseMutateFunction,
} from "@tanstack/react-query";
import { toast } from "sonner";
import i18n from "@/i18n/config";
import { apiErrorStatus, extractApiError } from "@/lib/errors";

type InvalidationFn<TData = unknown, TVars = unknown> = (
  queryClient: QueryClient,
  data: TData,
  vars: TVars,
) => void;

type AppMutationOptions<TData, TVars> = Omit<
  UseMutationOptions<TData, Error, TVars>,
  "mutationFn" | "onSuccess"
> & {
  /**
   * Message shown when the request fails and the API sends no reason of its
   * own. Without it the generic sentence is used — pass one when this
   * mutation can say something more useful than "that did not work".
   */
  errorFallback?: string;
  /**
   * Fail without a word. Only for mutations whose failure is not news to the
   * reader (background refreshes, best-effort bookkeeping) — never as a way
   * to keep the screen tidy.
   */
  silentError?: boolean;
};

/**
 * Wraps useMutation with automatic queryClient + onSuccess invalidation and a
 * failure that the reader can see.
 *
 * Replaces the repeated pattern:
 *   const queryClient = useQueryClient();
 *   return useMutation({
 *     mutationFn: ...,
 *     onSuccess: () => { invalidation.xxx(queryClient); },
 *   });
 *
 * ## A conflict refreshes the view it refused
 *
 * A 409 says the state the reader acted on is no longer the state — the
 * request was refused because the screen was behind the server, not because
 * it was malformed. Leaving the screen as it is leaves two versions of the
 * same fact in front of the reader and a button the server will refuse
 * again. So a 409 marks every cached answer stale, which refetches what is
 * on screen and what the reader opens next, and the failure still gets its
 * message.
 *
 * The `invalidate` callback is not run on the refusal even though the
 * factory knows the variables: it is a success continuation, not only a
 * cache refresh — it uploads the files waiting for a created id, patches
 * caches with the response body, opens a download. A refusal has none of
 * those and nothing to hand them.
 *
 * ## Every failure has an addressee
 *
 * A mutation that fails silently leaves the screen exactly as it was, so the
 * reader walks away believing the change was saved. This factory therefore
 * reports failures by default, and the default steps aside only where the
 * failure already has somewhere to go:
 *
 * - `mutate(vars)` — nobody is listening, so the error becomes a toast, using
 *   the API's own message when it sends one and `errorFallback` when it does
 *   not.
 * - `mutate(vars, { onError })` — the call site handles it; no toast, so the
 *   two do not stack up on top of each other.
 * - an `onError` in the options passed here — same, for the whole hook.
 * - `mutateAsync(vars)` — the error is handed to whoever awaited it; the
 *   `try/catch` around it decides what to say.
 * - `silentError: true` — a deliberate, readable "say nothing".
 *
 * Silence is a choice you write down, not something you get by forgetting a
 * parameter.
 */
export function useAppMutation<TData = unknown, TVars = void>(
  mutationFn: (vars: TVars) => Promise<TData>,
  invalidate: InvalidationFn<TData, TVars>,
  options?: AppMutationOptions<TData, TVars>,
): UseMutationResult<TData, Error, TVars> {
  const queryClient = useQueryClient();
  const { errorFallback, silentError, ...mutationOptions } = options ?? {};

  const result = useMutation<TData, Error, TVars>({
    mutationFn,
    onSuccess: (data: TData, vars: TVars) => {
      invalidate(queryClient, data, vars);
    },
    ...mutationOptions,
    // Composed after the spread so a caller's own `onError` still runs — on
    // the hook or on the call — while the refresh happens either way: it is
    // not part of anyone's error handling.
    onError: (error, vars, onMutateResult, mutationContext) => {
      if (apiErrorStatus(error) === 409) {
        queryClient.invalidateQueries();
      }
      mutationOptions.onError?.(error, vars, onMutateResult, mutationContext);
    },
  });

  // The wrapper below must stay referentially stable — React Query's own
  // `mutate` is, and callers put it in effect dependencies. Reading the
  // current mutation and options through a ref keeps it that way.
  const latest = useRef({
    result,
    silentError,
    errorFallback,
    mutationOptions,
  });
  latest.current = { result, silentError, errorFallback, mutationOptions };

  // Declared against the library's own argument shape: react-query 5.103
  // widened `mutate` to a union of argument tuples, and a hand-written
  // (vars, options?) callback no longer satisfies it. The rest-tuple keeps
  // every call-site shape working and forwards both arguments untouched.
  const mutate = useCallback<UseMutateFunction<TData, Error, TVars>>(
    (...args) => {
      const [vars, callOptions] = args;
      const current = latest.current;
      const handled =
        current.silentError ||
        Boolean(callOptions?.onError) ||
        Boolean(current.mutationOptions.onError);
      if (handled) {
        current.result.mutate(...args);
        return;
      }
      const reportToReader: MutateOptions<TData, Error, TVars> = {
        ...callOptions,
        onError: (error) => {
          toast.error(
            extractApiError(
              error,
              current.errorFallback ?? i18n.t("common:errors.actionFailed"),
            ),
          );
        },
      };
      // The options are always present here, but the library models `mutate`
      // as a union of argument tuples whose first member makes `variables`
      // optional — a two-element tuple with required options does not
      // inhabit it. The runtime shape is exactly the two-argument call;
      // only the union is narrower than reality.
      current.result.mutate(
        ...([vars, reportToReader] as Parameters<
          MutateFunction<TData, Error, TVars>
        >),
      );
    },
    [],
  );

  return { ...result, mutate };
}
