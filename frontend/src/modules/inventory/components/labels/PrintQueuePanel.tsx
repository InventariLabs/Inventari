import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ExternalLink, Printer, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocale, formatRecentMoment } from "@/utils/formatters";
import {
  usePrintAgents,
  usePrintJobs,
  useRetryPrintJob,
} from "@/modules/shared/hooks/usePrintQueue";
import type {
  PrintAgent,
  PrintJob,
  PrintJobStatus,
} from "@/modules/shared/lib/printQueue";

/** The print agent's setup guide, as the latest release ships it. */
const PRINT_AGENT_SETUP_URL =
  "https://github.com/InventariLabs/Inventari/blob/main/print-agent/README.md";

const STATUS_VARIANT: Record<
  PrintJobStatus,
  "secondary" | "info" | "success" | "danger"
> = {
  queued: "secondary",
  printing: "info",
  printed: "success",
  failed: "danger",
};

const STATUS_LABEL = {
  queued: "printQueue.status.queued",
  printing: "printQueue.status.printing",
  printed: "printQueue.status.printed",
  failed: "printQueue.status.failed",
} as const satisfies Record<PrintJobStatus, string>;

/**
 * The printers this organization has, and what was last sent to them.
 *
 * A print agent announces itself when it starts and then asks for work every
 * few seconds, so "online" is simply "asked recently". Before any agent has
 * started there is nothing to choose from — the panel then says how to start
 * one, because "Send to printer" stays hidden until then.
 */
export function PrintQueuePanel() {
  const { t } = useTranslation("labels");
  const enabledModules = useEnabledModulesOptional();
  const agents = usePrintAgents({ live: true });
  const jobs = usePrintJobs();
  const retry = useRetryPrintJob();

  const agentList = agents.data ?? [];
  const jobList = jobs.data ?? [];
  const names = new Map(agentList.map((agent) => [agent.id, agent.name]));

  const sendAgain = async (job: PrintJob) => {
    try {
      await retry.mutateAsync(job.id);
      toast.success(t("printQueue.resent"));
    } catch (error) {
      toast.error(extractApiError(error, t("printQueue.sendFailed")));
    }
  };

  if (agents.isLoading) return null;

  return (
    <Card className="p-4 space-y-4" data-testid="print-queue-panel">
      <h2 className="text-sm font-semibold text-on">{t("printQueue.title")}</h2>

      {agents.isError ? (
        <QueryFailure error={agents.error} onRetry={() => agents.refetch()} />
      ) : agentList.length === 0 ? (
        <div className="space-y-2">
          <p className="text-sm text-on-muted">{t("printQueue.noAgents")}</p>
          {/* The key page belongs to an optional module: a profile without it
              would land on "page not found". */}
          {enabledModules.includes("api_keys") && (
            <p className="text-sm">
              <Link
                to="/settings/api-keys"
                className="font-medium text-primary-700 hover:underline dark:text-primary-500"
              >
                {t("printQueue.createAgentKey")}
              </Link>
            </p>
          )}
          <a
            href={PRINT_AGENT_SETUP_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm font-medium text-primary-700 hover:underline dark:text-primary-500"
          >
            {t("printQueue.setupAgent")}
            <ExternalLink size={14} aria-hidden="true" />
          </a>
        </div>
      ) : (
        <ul className="space-y-2">
          {agentList.map((agent) => (
            <AgentRow key={agent.id} agent={agent} />
          ))}
        </ul>
      )}

      {jobs.isError && (
        <QueryFailure error={jobs.error} onRetry={() => jobs.refetch()} />
      )}

      {jobList.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-on-muted">
            {t("printQueue.recentJobs")}
          </h3>
          <ul className="divide-y divide-border">
            {jobList.map((job) => (
              <li
                key={job.id}
                data-testid="print-job-row"
                className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
              >
                <Badge variant={STATUS_VARIANT[job.status]}>
                  {t(STATUS_LABEL[job.status])}
                </Badge>
                <span className="text-sm text-on min-w-0 truncate">
                  {job.short_codes.join(", ")}
                  {job.count > job.short_codes.length &&
                    ` ${t("printQueue.more", { count: job.count - job.short_codes.length })}`}
                </span>
                <span className="text-xs text-on-muted">
                  {names.get(job.agent_id) ?? ""} ·{" "}
                  {t("printQueue.size", {
                    width: formatQuantityLocale(job.width_mm, 2),
                    height: formatQuantityLocale(job.height_mm, 2),
                  })}{" "}
                  · {formatRecentMoment(job.finished_at ?? job.created_at)}
                </span>
                {job.scale != null && (
                  <span className="basis-full text-xs text-on-warning">
                    {t("printQueue.shrunk", {
                      percent: Math.round(job.scale * 100),
                    })}
                  </span>
                )}
                {job.status === "failed" && (
                  <>
                    {job.error && (
                      <span className="basis-full text-xs text-on-danger">
                        {job.error}
                      </span>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      leftIcon={<RotateCcw size={14} />}
                      onClick={() => sendAgain(job)}
                      disabled={retry.isPending}
                    >
                      {t("printQueue.retry")}
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

/**
 * A printer by name, and whether its agent is asking for work.
 *
 * It used to show a media profile and a label size, with a dialog to change
 * them. A printer has neither now: every label is one file at the size the
 * person chose, and the agent next to the printer fits it there.
 */
function AgentRow({ agent }: { agent: PrintAgent }) {
  const { t } = useTranslation("labels");
  return (
    <li
      data-testid="print-agent-row"
      className="flex flex-wrap items-center gap-x-3 gap-y-1"
    >
      <Printer size={16} className="text-on-muted" aria-hidden="true" />
      <span className="text-sm font-medium text-on">{agent.name}</span>
      <Badge variant={agent.online ? "success" : "secondary"}>
        {agent.online ? t("printQueue.online") : t("printQueue.offline")}
      </Badge>
      {!agent.online && (
        <span className="text-xs text-on-muted">
          {t("printQueue.lastSeen", {
            when: formatRecentMoment(agent.last_seen_at),
          })}
        </span>
      )}
    </li>
  );
}
