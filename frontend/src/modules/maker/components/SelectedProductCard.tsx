import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { ProductOption } from "@/modules/maker/api/products";
import { readableSku } from "@/lib/readableSku";

interface SelectedProductCardProps {
  product: ProductOption;
  onChange: () => void;
}

/**
 * The output product the create sheet stands on once the search has been
 * answered — its name and SKU, with the one way back to the search.
 */
export function SelectedProductCard({
  product,
  onChange,
}: SelectedProductCardProps) {
  const { t } = useTranslation("maker");

  return (
    <div className="space-y-2">
      <p className="block text-xs font-medium uppercase text-on-secondary tracking-wide">
        {t("create.productLabel", { defaultValue: "Output product" })}
      </p>
      <Card className="p-3 flex items-center justify-between bg-accent-50 border-accent-100">
        <div className="min-w-0">
          <div className="font-medium truncate">{product.name}</div>
          {readableSku(product.sku) && (
            <div className="text-xs text-on-muted font-mono">
              {readableSku(product.sku)}
            </div>
          )}
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onChange}
          data-testid="maker-create-change-product"
        >
          {t("create.change", { defaultValue: "Change" })}
        </Button>
      </Card>
    </div>
  );
}
