import { useId, useState } from "react";
import { Barcode } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { ScanCodeButton } from "./ScanCodeButton";
import { useGenerateProductCode } from "@/modules/inventory/hooks/useItemMutations";
import type { FieldDefinition } from "@/types";
import { DefaultInputField } from "./DefaultInputField";

const INTERNAL_CODE = /^20\d{11}$/;

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
  const hintId = useId();
  const code = String(value ?? "").trim();
  const empty = code === "";
  // The range the generator draws from: an EAN-13 starting with 20, which
  // GS1 keeps for a company's own goods. A code typed by hand can be in it
  // too — another company's in-store code — so its sentence names no owner.
  const internal = INTERNAL_CODE.test(code);
  const hint = empty ? "button" : internal ? "code" : null;
  // Once the hint has stood under the field its place stays, empty, while
  // the form is open: the first keystroke of a typed code would otherwise
  // pull everything below the field up by the hint's height.
  const [hintPlaceKept, keepHintPlace] = useState(hint !== null);
  if (hint !== null && !hintPlaceKept) keepHintPlace(true);

  return (
    <div>
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <DefaultInputField
            id={id}
            field={field}
            value={value}
            error={error}
            describedBy={hint ? hintId : undefined}
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
                onSuccess: (generated) => onChange(generated),
              })
            }
          >
            {t("fields.generateCode")}
          </Button>
        )}
      </div>
      {/* The code printed on the product is read, not retyped. */}
      <div className="mt-2">
        <ScanCodeButton label={t("fields.scanCode")} onCode={onChange} />
      </div>
      {hintPlaceKept && (
        // Both sentences share one cell, so it is as tall as the longer one
        // and swapping them moves nothing either; the one not in force is
        // invisible, which also takes it out of the accessibility tree.
        <div className="grid text-xs text-on-muted mt-1.5">
          {(
            [
              ["button", t("fields.generateCodeHint")],
              ["code", t("fields.internalCodeHint")],
            ] as const
          ).map(([which, sentence]) => (
            <p
              key={which}
              id={hint === which ? hintId : undefined}
              className={cn(
                "col-start-1 row-start-1",
                hint !== which && "invisible",
              )}
            >
              {sentence}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
