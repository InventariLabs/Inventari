import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { LocationCombobox, ScanCameraPanel } from "@/module-sdk";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { LabelPickerInput } from "@/modules/shared/components/LabelPickerInput";
import { EquipmentCategoryField } from "@/modules/equipment/components/EquipmentCategoryField";
import { Link } from "react-router-dom";
import { Settings2, Plus, Camera, CameraOff, Loader2 } from "lucide-react";
import type { CategoryDTO } from "@/types";
import type { EquipmentFormData } from "../pages/AddEquipmentPage";

const noop = () => {};

const fieldLabel =
  "block text-xs font-medium uppercase tracking-wide text-on-secondary ml-1";

interface BasicInfoSectionProps {
  form: EquipmentFormData;
  fieldErrors?: Partial<Record<"name" | "location_id" | "category_id", string>>;
  equipmentCategories: CategoryDTO[];
  categoryRequired?: boolean;
  showLabelCode?: boolean;
  onSet: (field: keyof EquipmentFormData, value: string) => void;
  onShowAddLocation: () => void;
  scanOpen?: boolean;
  scanLoading?: boolean;
  isCameraActive?: boolean;
  scannerError?: string | null;
  isTorchOn?: boolean;
  onToggleScan?: () => void;
  onToggleTorch?: () => void;
  onRetryScan?: () => void;
}

export function BasicInfoSection({
  form,
  fieldErrors = {},
  equipmentCategories,
  categoryRequired = false,
  showLabelCode = true,
  onSet,
  onShowAddLocation,
  scanOpen = false,
  scanLoading = false,
  isCameraActive = false,
  scannerError = null,
  isTorchOn = false,
  onToggleScan,
  onToggleTorch,
  onRetryScan,
}: BasicInfoSectionProps) {
  const { t } = useTranslation("equipment");
  const hasDynamicData = Object.values(form.dynamic).some(
    (v) => v !== "" && v !== null && v !== undefined,
  );

  const nameRef = useRef<HTMLInputElement>(null);
  const categoryRef = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (fieldErrors.name) nameRef.current?.focus();
    else if (fieldErrors.category_id) categoryRef.current?.focus();
    else if (fieldErrors.location_id)
      document.getElementById("equipment-location")?.focus();
  }, [fieldErrors]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t("form.sections.basic", "Basic Info")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <label className={fieldLabel} htmlFor="equipment-name">
            {t("form.fields.name", "Name")}
            <span className="text-red-600 dark:text-red-400 ml-1">*</span>
          </label>
          <Input
            id="equipment-name"
            ref={nameRef}
            value={form.name}
            onChange={(e) => onSet("name", e.target.value)}
            placeholder={t("form.placeholders.name", "e.g. Dell Latitude 5540")}
            required
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.name)}
          />
          {fieldErrors.name && (
            <p
              role="alert"
              className="text-xs text-red-600 dark:text-red-400 ml-1"
            >
              {fieldErrors.name}
            </p>
          )}
        </div>

        <EquipmentCategoryField
          ref={categoryRef}
          value={form.category_id}
          categories={equipmentCategories}
          hasDynamicData={hasDynamicData}
          required={categoryRequired}
          error={fieldErrors.category_id}
          onChange={(categoryId) => onSet("category_id", categoryId)}
        />

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className={fieldLabel} htmlFor="equipment-location">
              {t("form.fields.location", "Location")}
              <span className="text-red-600 dark:text-red-400 ml-1">*</span>
            </label>
            <Link
              to="/equipment/locations"
              className="flex items-center gap-1 text-xs text-primary-500 hover:text-primary-600 transition-colors"
            >
              <Settings2 size={12} />
              {t("form.manageLocations", "Manage")}
            </Link>
          </div>
          <div className="flex gap-2">
            <LocationCombobox
              wrapperClassName="flex-1"
              id="equipment-location"
              // The form's own shelves, not the organization's: tagged for
              // equipment, or already holding its records. The
              // organization's other locations are offered by name nowhere
              // in this module — that is the picker that let a laptop be
              // filed into a freezer.
              scope={{ moduleScope: "equipment" }}
              value={form.location_id}
              onChange={(id) => onSet("location_id", id)}
              placeholder={t("form.placeholders.location", "Select location…")}
              title={t("form.fields.location", "Location")}
              required
              error={fieldErrors.location_id}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={onShowAddLocation}
              className="border-dashed shrink-0"
              title={t("locations.addTitle", "Add Location")}
              aria-label={t("locations.addTitle", "Add Location")}
            >
              <Plus size={18} />
            </Button>
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className={fieldLabel} htmlFor="equipment-barcode">
              {t("form.fields.barcode", "Barcode / EAN")}
            </label>
            {onToggleScan && (
              <Button
                type="button"
                variant={scanOpen ? "default" : "ghost"}
                size="sm"
                onClick={onToggleScan}
                className={scanOpen ? "" : "text-on-secondary hover:text-on"}
              >
                {scanLoading ? (
                  <Loader2 size={14} className="animate-spin mr-1" />
                ) : scanOpen ? (
                  <CameraOff size={14} className="mr-1" />
                ) : (
                  <Camera size={14} className="mr-1" />
                )}
                {scanOpen
                  ? t("form.scanClose", "Close scanner")
                  : t("form.scanOpen", "Scan")}
              </Button>
            )}
          </div>
          <ScanCameraPanel
            open={scanOpen}
            pinned
            scannerError={scannerError}
            isCameraActive={isCameraActive}
            isTorchOn={isTorchOn}
            onRetry={onRetryScan ?? noop}
            onToggleTorch={onToggleTorch ?? noop}
            onClose={onToggleScan ?? noop}
            className="mb-3"
          />
          <Input
            id="equipment-barcode"
            value={form.barcode}
            onChange={(e) => onSet("barcode", e.target.value)}
            placeholder={t("form.placeholders.barcode", "Scan or type…")}
            className="font-mono"
          />
        </div>

        {showLabelCode ? (
          <div className="space-y-1.5">
            <label className={fieldLabel} htmlFor="equipment-label-code">
              {t("form.fields.labelCode", "Label / QR Code")}
            </label>
            <LabelPickerInput
              id="equipment-label-code"
              value={form.label_code}
              onChange={(code) => onSet("label_code", code)}
            />
            <p className="text-xs text-on-muted ml-1">
              {t(
                "form.hints.labelCode",
                "Paste a code from a printed QR sticker to link it to this asset.",
              )}
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
