import { useState } from "react";
import { X, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useCreateCategory } from "@/modules/shared/hooks/useCategories";
import { EmojiPicker } from "@/components/ui/EmojiPicker";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet } from "@/components/ui/Sheet";
import { toast } from "sonner";
import type { CategoryDTO } from "@/types";

interface CategoryCreateModalProps {
  onClose: () => void;
  onSuccess: (newCat: CategoryDTO) => void;
}

export default function CategoryCreateModal({
  onClose,
  onSuccess,
}: CategoryCreateModalProps) {
  const { t } = useTranslation(["categories", "items", "common"]);
  // Quick-create is fast. The user only picks an
  // emoji here; color can be tweaked later from the management page.
  const [newCategoryData, setNewCategoryData] = useState<{
    name: string;
    emoji: string | null;
  }>({ name: "", emoji: null });

  const createCategoryMutation = useCreateCategory();

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal-nested"
      backdropOpacity={60}
      aria-label={t("categories:newCategory")}
    >
      <div className="p-8 flex-1 overflow-y-auto">
        <div className="flex items-center justify-between mb-8">
          <h2 className="text-2xl font-semibold text-on tracking-tight">
            {t("categories:newCategory")}
          </h2>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
          >
            <X size={24} />
          </Button>
        </div>
        <div className="space-y-8">
          <div>
            <Input
              label={t("categories:modal.nameLabel")}
              type="text"
              value={newCategoryData.name}
              onChange={(e) =>
                setNewCategoryData({ ...newCategoryData, name: e.target.value })
              }
              placeholder={t("categories:modal.namePlaceholder")}
              autoFocus
            />
          </div>

          <div>
            <p className="block text-xs font-medium uppercase tracking-wide text-on-secondary ml-1">
              {t("categories:modal.symbolLabel")}
            </p>
            <EmojiPicker
              value={newCategoryData.emoji}
              onChange={(emoji) =>
                setNewCategoryData({ ...newCategoryData, emoji })
              }
            />
          </div>

          <Button
            type="button"
            variant="primary"
            size="lg"
            isLoading={createCategoryMutation.isPending}
            disabled={
              createCategoryMutation.isPending || !newCategoryData.name.trim()
            }
            onClick={() =>
              createCategoryMutation.mutate(
                {
                  name: newCategoryData.name,
                  emoji: newCategoryData.emoji,
                },
                {
                  onSuccess: (newCat) => {
                    toast.success(
                      t("categories:messages.created", {
                        defaultValue: "Category created",
                      }),
                    );
                    onSuccess(newCat);
                  },
                },
              )
            }
            leftIcon={<Plus size={20} />}
            className="w-full h-16 text-lg rounded-2xl gap-3"
          >
            {t("categories:createCategory")}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
