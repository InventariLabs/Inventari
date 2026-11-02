import { useModules } from "@/contexts/ModulesContext";
import { useAwaitingApprovalDocuments } from "@/modules/warehouse/hooks/useAwaitingApprovalDocuments";
import { cn } from "@/lib/utils";

/**
 * Pending-approval count badge for the documents submenu (spec C.3).
 *
 * Renders nothing when the approvals module is off, while loading, on
 * error, or when the count is zero — so the nav item stays clean unless
 * there is actionable work for the current user. Shares the
 * ``["documents","awaiting-my-approval"]`` query cache with the approvals
 * queue page, so opening the nav never triggers an extra request.
 */
export function ApprovalsQueueBadge({ className }: { className?: string }) {
  const { isModuleEnabled } = useModules();
  const enabled = isModuleEnabled("approvals");
  const { data, isLoading, isError } = useAwaitingApprovalDocuments({
    enabled,
  });

  if (!enabled || isLoading || isError) return null;

  const count = data?.total ?? data?.items?.length ?? 0;
  if (count <= 0) return null;

  return (
    <span
      data-testid="approvals-queue-badge"
      className={cn(
        "inline-flex items-center justify-center min-w-[18px] h-[18px] px-1",
        "rounded-full bg-primary-700 dark:bg-primary-800 text-white text-[10px] font-medium",
        "leading-none",
        className,
      )}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}
