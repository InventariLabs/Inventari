import { useTranslation } from "react-i18next";
import { Check, Pencil, Star, TriangleAlert, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProviderLogo } from "@/modules/settings/components/ai/ProviderLogo";
import { getProviderDescriptor } from "@/modules/settings/components/ai/providers";
import type { AiConnection } from "@/types/ai";

interface AiConnectionCardProps {
  connection: AiConnection;
  isBoundHere: boolean;
  onEdit: (connection: AiConnection) => void;
  onDelete: (connection: AiConnection) => void;
}

export function AiConnectionCard({
  connection,
  isBoundHere,
  onEdit,
  onDelete,
}: AiConnectionCardProps) {
  const { t } = useTranslation("modules");
  const providerMeta = getProviderDescriptor(connection.provider);

  return (
    <Card className="p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex items-start gap-2">
          <ProviderLogo
            provider={connection.provider}
            size={20}
            className="mt-0.5 shrink-0"
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-on truncate">
                {connection.name}
              </h3>
              {isBoundHere && (
                <Star
                  size={14}
                  className="text-amber-500 fill-amber-500 dark:text-amber-400 dark:fill-amber-400 shrink-0"
                  aria-label={t("config.boundHere")}
                />
              )}
            </div>
            <p className="text-xs text-on-muted truncate">
              {providerMeta?.name ?? connection.provider}
              {connection.model_name ? ` · ${connection.model_name}` : ""}
            </p>
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onEdit(connection)}
            aria-label={t("config.editConnection")}
          >
            <Pencil size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onDelete(connection)}
            aria-label={t("config.deleteConnection")}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            <Trash2 size={16} />
          </Button>
        </div>
      </div>

      {/* A capability is a claim until the connection test asks the model to
          make good on it. The three states are drawn apart because they mean
          three different things to somebody choosing where to send a
          photograph: nobody has checked, it worked, it did not. */}
      <div className="flex flex-wrap gap-1.5">
        {(connection.capabilities ?? []).map((cap) => {
          const check = connection.capability_checks?.[cap];
          const title =
            check === undefined
              ? t("config.capabilityUnverified")
              : check.ok
                ? t("config.capabilityConfirmed")
                : t("config.capabilityFailed");
          return (
            <Badge
              key={cap}
              variant={check?.ok === false ? "danger" : "outline"}
              className="text-[10px]"
              title={title}
            >
              {check?.ok === true && (
                <Check size={10} className="mr-1" aria-hidden="true" />
              )}
              {check?.ok === false && (
                <TriangleAlert size={10} className="mr-1" aria-hidden="true" />
              )}
              {t(`config.capability.${cap}`)}
              <span className="sr-only"> — {title}</span>
            </Badge>
          );
        })}
      </div>
      {(connection.capabilities ?? []).some(
        (cap) => connection.capability_checks?.[cap]?.ok === false,
      ) && (
        <p className="text-xs text-on-warning">
          {t("config.capabilityFailedHint")}
        </p>
      )}

      {connection.api_key && (
        <p className="text-xs font-mono text-on-muted truncate">
          {connection.api_key}
        </p>
      )}
    </Card>
  );
}
