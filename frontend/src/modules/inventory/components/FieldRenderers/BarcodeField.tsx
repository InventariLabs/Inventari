import { Barcode } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { LazyScanToFill } from "@/modules/shared/components/LazyScanToFill";
import { useGenerateProductCode } from "@/modules/inventory/hooks/useItemMutations";
import type { FieldDefinition } from "@/types";
import { DefaultInputField } from "./DefaultInputField";

interface BarcodeFieldProps {
  id?: string;
  field: FieldDefinition;
  value: unknown;
  error?: string;
  onChange: (value: unknown) => void;
}

/**
 * The product code: read off the pack by the camera, or — for a product that
 * came without — generated.
 *
 * A workshop's own goods carry no manufacturer's code, and the field was the
 * one place a scan door looks a product up by — so "Generate code" fills it
 * with an internal EAN-13 the product's label then prints. Only while the
 * field is empty: replacing a code would strand every label already on a
 * shelf.
 */
export function BarcodeField({
  id,
  field,
  value,
  error,
  onChange,
}: BarcodeFieldProps) {
  const { t } = useTranslation("items");
  const generate = useGenerateProductCode();
  const empty = String(value ?? "").trim() === "";

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <DefaultInputField
            id={id}
            field={field}
            value={value}
            error={error}
            onChange={onChange}
          />
        </div>
        {empty && (
          <Button
            type="button"
            variant="outline"
            leftIcon={<Barcode size={16} />}
            isLoading={generate.isPending}
            onClick={() =>
              generate.mutate(undefined, {
                onSuccess: (code) => onChange(code),
              })
            }
          >
            {t("fields.generateCode")}
          </Button>
        )}
      </div>
      {/* The code printed on the product is read, not retyped. */}
      <LazyScanToFill label={t("fields.scanCode")} onCode={onChange} />
    </div>
  );
}
