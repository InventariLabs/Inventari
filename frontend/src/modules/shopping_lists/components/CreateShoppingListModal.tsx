import { useState } from "react";
import { X, Loader2, ShoppingCart, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet, SheetActions } from "@/components/ui/Sheet";
import { formatDate } from "@/utils/helpers";
import { extractApiError } from "@/lib/errors";

interface Props {
  onClose: () => void;
  onSuccess: () => void;
}

export default function CreateShoppingListModal({ onClose, onSuccess }: Props) {
  const { t } = useTranslation("shopping_lists");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    setSubmitting(true);
    try {
      // The fallback used to be an English template string, so a Polish
      // interface produced Polish lists called "List 20.08.2026".
      const defaultName = t("modal.defaultName", {
        date: formatDate(new Date().toISOString()),
      });
      const finalName = name.trim() || defaultName;

      await shoppingListsApi.create({ name: finalName });

      toast.success(t("modal.createSuccess"));
      onSuccess();
    } catch (err) {
      // show a friendly, extracted message instead of the raw
      // axios/pydantic error string.
      toast.error(extractApiError(err, t("modal.createFailed")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      backdropOpacity={60}
      aria-label={t("modal.title")}
    >
      <div className="p-6 flex-1 overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary-50 text-primary-600 rounded-xl">
              <ShoppingCart size={20} />
            </div>
            <h3 className="text-lg font-semibold text-on">
              {t("modal.title")}
            </h3>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
          >
            <X size={24} />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="listName"
              className="block text-[10px] font-medium text-on-muted uppercase tracking-widest mb-2 ml-1"
            >
              {t("modal.nameLabel")}
            </label>
            <Input
              id="listName"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("modal.namePlaceholder")}
              autoFocus
            />
            <p className="text-[10px] text-on-muted mt-2 ml-1 italic">
              {t("modal.nameHint")}
            </p>
          </div>

          <SheetActions className="pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              {t("modal.cancel")}
            </Button>
            <Button type="submit" disabled={submitting} className="gap-3">
              {submitting ? (
                <Loader2 size={24} className="animate-spin" />
              ) : (
                <Plus size={24} />
              )}
              {submitting
                ? t("modal.creating")
                : t("modal.create", { defaultValue: "Create list" })}
            </Button>
          </SheetActions>
        </form>
      </div>
    </Sheet>
  );
}
