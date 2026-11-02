import { useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Printer } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { extractApiError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { useSettingsStore } from "@/store/settingsStore";
import { usePrintAgents, useQueuePrintJob } from "../hooks/usePrintQueue";
import type { PrintAgent, PrintOptions, PrintTarget } from "../lib/printQueue";

interface SendToPrinterButtonProps {
  /** What to print; `null` while nothing is chosen. */
  target: PrintTarget | null;
  /** The download's caption, QR-only, copies and size, when it has them.
   *  A screen with no preview leaves the size out and the job takes the
   *  default label size from the settings. */
  options?: PrintOptions;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  className?: string;
  /** Classes for the text beside the icon — `hidden sm:inline` in a header
   *  whose other buttons show only their icon on a phone. */
  textClassName?: string;
  /** After the job is queued — a bulk bar clears its selection here. */
  onSent?: () => void;
}

/**
 * "Send to printer" — queues the labels for the print agent next to a printer.
 *
 * Absent while the organization has no printer: an agent registers itself
 * when it starts, and until one has, the button would only lead to an error.
 * With one printer it sends straight away; with several it asks which.
 */
export function SendToPrinterButton({
  target,
  options,
  variant = "outline",
  size,
  className,
  textClassName,
  onSent,
}: SendToPrinterButtonProps) {
  const { t } = useTranslation("labels");
  const agents = usePrintAgents().data;
  const defaultWidth = useSettingsStore((s) => s.defaultLabelWidth);
  const defaultHeight = useSettingsStore((s) => s.defaultLabelHeight);
  const queue = useQueuePrintJob();
  const [choosing, setChoosing] = useState(false);

  // No printer known — none registered, or the list could not be read — is
  // no button: the label pool's printer panel is where a failed read is said.
  if (!agents || agents.length === 0) return null;

  const send = async (agent: PrintAgent) => {
    if (!target) return;
    setChoosing(false);
    try {
      await queue.mutateAsync({
        target,
        agentId: agent.id,
        options: { width: defaultWidth, height: defaultHeight, ...options },
      });
      toast.success(
        agent.online
          ? t("printQueue.sent", { printer: agent.name })
          : t("printQueue.sentOffline", { printer: agent.name }),
      );
      onSent?.();
    } catch (error) {
      toast.error(extractApiError(error, t("printQueue.sendFailed")));
    }
  };

  const button = (
    <Button
      variant={variant}
      size={size}
      className={className}
      leftIcon={<Printer size={16} />}
      disabled={!target}
      isLoading={queue.isPending}
      onClick={agents.length === 1 ? () => send(agents[0]) : undefined}
    >
      <span className={textClassName}>{t("printQueue.send")}</span>
    </Button>
  );

  if (agents.length === 1) return button;

  return (
    <PopoverPrimitive.Root open={choosing} onOpenChange={setChoosing}>
      <PopoverPrimitive.Trigger asChild>{button}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="end"
          sideOffset={4}
          style={{ zIndex: "var(--z-popover)" }}
          aria-label={t("printQueue.choose")}
          className="w-64 bg-surface-card rounded-xl border border-border shadow-xl p-1 flex flex-col gap-1"
        >
          <p className="px-3 pt-2 pb-1 text-xs text-on-muted">
            {t("printQueue.choose")}
          </p>
          {agents.map((agent) => (
            <Button
              key={agent.id}
              variant="ghost"
              className="w-full justify-between gap-2 text-on-secondary hover:text-on"
              onClick={() => send(agent)}
            >
              <span className="truncate">{agent.name}</span>
              <span
                className={cn(
                  "text-xs",
                  agent.online ? "text-success-700" : "text-on-muted",
                )}
              >
                {agent.online
                  ? t("printQueue.online")
                  : t("printQueue.offline")}
              </span>
            </Button>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
