import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Home, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryResult } from "@/components/ui/QueryResult";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import {
  useShoppingExclusions,
  useCreateShoppingExclusion,
  useDeleteShoppingExclusion,
} from "@/modules/recipes/hooks/useMealPlans";
import { extractApiError } from "@/lib/errors";

export default function AlwaysAtHomePage() {
  const { t } = useTranslation("recipes");
  const canWrite = useCanWrite("recipes");
  const [addName, setAddName] = useState("");

  const exclusionsQuery = useShoppingExclusions();
  const createExclusion = useCreateShoppingExclusion();
  const deleteExclusion = useDeleteShoppingExclusion();

  function handleAdd() {
    const trimmed = addName.trim();
    if (!trimmed) return;
    createExclusion.mutate(
      { name: trimmed },
      {
        onSuccess: () => {
          toast.success(t("meal_planner.exclusions_added"));
          setAddName("");
        },
        onError: (err: unknown) => {
          const status = (err as Error & { response?: { status?: number } })
            ?.response?.status;
          if (status === 409) {
            toast.info(t("meal_planner.exclusions_already_exists"));
          } else {
            toast.error(
              extractApiError(err, t("meal_planner.exclusions_error")),
            );
          }
        },
      },
    );
  }

  function handleRemove(id: string) {
    deleteExclusion.mutate(id, {
      onSuccess: () => {
        toast.success(t("meal_planner.exclusions_removed"));
      },
      onError: (err) => {
        toast.error(extractApiError(err, t("meal_planner.exclusions_error")));
      },
    });
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      <ReadOnlyNotice module="recipes" />
      <p className="text-sm text-on-muted">
        {t("meal_planner.exclusions_desc")}
      </p>

      {canWrite && (
        <div className="flex items-center gap-2 max-w-md">
          <Input
            aria-label={t("meal_planner.exclusions_add_placeholder")}
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAdd();
            }}
            placeholder={t("meal_planner.exclusions_add_placeholder")}
          />
          <Button
            onClick={handleAdd}
            size="sm"
            disabled={!addName.trim() || createExclusion.isPending}
          >
            <Plus size={16} className="mr-1" />
            {t("meal_planner.exclusions_add_button")}
          </Button>
        </div>
      )}

      <QueryResult query={exclusionsQuery}>
        {(exclusions) =>
          exclusions.length === 0 ? (
            <EmptyState
              variant="compact"
              icon={Home}
              title={t("meal_planner.exclusions_empty")}
              description={t("meal_planner.exclusions_empty_description")}
            />
          ) : (
            <>
              <div className="border border-border rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-raised/50 text-left">
                      <th className="px-4 py-2.5 font-medium text-on-secondary">
                        {t("common:form.name")}
                      </th>
                      <th className="px-4 py-2.5 font-medium text-on-secondary w-20" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {exclusions.map((item) => (
                      <tr
                        key={item.id}
                        className="hover:bg-surface-raised/30 transition-colors"
                      >
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <Home
                              size={14}
                              className="text-primary-500 shrink-0"
                              fill="currentColor"
                            />
                            {item.template_image_url && (
                              <img
                                src={item.template_image_url}
                                alt=""
                                loading="lazy"
                                className="w-6 h-6 rounded object-cover"
                              />
                            )}
                            <span className="font-medium">{item.name}</span>
                            {item.template_barcode && (
                              <span className="text-xs text-on-muted">
                                {item.template_barcode}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          {canWrite && (
                            <Button
                              type="button"
                              size="iconSm"
                              variant="ghost"
                              onClick={() => handleRemove(item.id)}
                              className="rounded-lg text-on-muted hover:text-on-danger hover:bg-red-50 active:bg-red-50"
                              aria-label={t("common:remove")}
                              title={t("common:remove")}
                            >
                              <X size={16} />
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-on-muted text-center">
                {t("meal_planner.exclusions_count", {
                  count: exclusions.length,
                })}
              </p>
            </>
          )
        }
      </QueryResult>
    </div>
  );
}
