import { apiErrorStatus, extractApiErrorCode } from "@/lib/errors";

/** Why the demo did not hand out a sandbox, in the visitor's terms. */
export type DemoSandboxFailure =
  "capReached" | "poolEmpty" | "tooManyFromHere" | "network" | "failed";

/**
 * Which refusal a failed request for a demo sandbox was.
 *
 * The limits are part of the demo working as intended, not a fault: a
 * visitor who meets one is told what happened and when to come back, on the
 * page they are on, never shown an error page.
 */
export function demoSandboxFailure(error: unknown): DemoSandboxFailure {
  const code = extractApiErrorCode(error);
  if (code === "DEMO_SANDBOX_CAP_REACHED") return "capReached";
  if (code === "DEMO_SANDBOX_POOL_EMPTY") return "poolEmpty";
  const status = apiErrorStatus(error);
  if (status === null) return "network";
  if (status === 429) return "tooManyFromHere";
  return "failed";
}
