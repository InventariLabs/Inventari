import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ClipboardPaste, Wand2, X } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import type { BulkEquipmentEntry } from "@/modules/equipment/api/equipment";

interface BulkAddPanelProps {
  onSubmit: (
    entries: BulkEquipmentEntry[],
    options: { assignLabels: boolean; qrOnly: boolean },
  ) => void;
  onCancel: () => void;
  assetName?: string;
  isSubmitting?: boolean;
}

const MAX_ENTRIES = 200;

function buildPrefix(name: string): string {
  return name
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 12);
}

function generateSerials(prefix: string, count: number): BulkEquipmentEntry[] {
  const pad = String(count).length;
  return Array.from({ length: count }, (_, index) => ({
    serial_number: `${prefix}-${String(index + 1).padStart(pad, "0")}`,
    asset_tag: undefined,
  }));
}

function parseSerials(value: string): BulkEquipmentEntry[] {
  return value
    .split(/\r?\n/)
    .map((serialNumber) => serialNumber.trim())
    .filter(Boolean)
    .slice(0, MAX_ENTRIES)
    .map((serialNumber) => ({
      serial_number: serialNumber,
      asset_tag: undefined,
    }));
}

export default function BulkAddPanel({
  onSubmit,
  onCancel,
  assetName = "",
  isSubmitting = false,
}: BulkAddPanelProps) {
  const { t } = useTranslation("equipment");
  // "" is the cleared field, a state every manual entry passes through — the
  // same bargain DefaultServingsField strikes. Bounds are applied where the
  // serials are generated, not at the typing event.
  const [quantity, setQuantity] = useState<number | "">(1);
  const [prefix, setPrefix] = useState(() => buildPrefix(assetName));
  const [pasteValue, setPasteValue] = useState("");
  const [entries, setEntries] = useState<BulkEquipmentEntry[]>([]);
  const [useSerialAsAssetTag, setUseSerialAsAssetTag] = useState(false);
  const [assignLabels, setAssignLabels] = useState(false);
  const [qrOnly, setQrOnly] = useState(false);

  // What the Generate press asks for: the typed number trimmed to the panel's
  // bounds, a cleared field falling back to one — never NaN, never zero rows.
  const requestedQuantity =
    quantity === "" ? 1 : Math.min(MAX_ENTRIES, Math.max(1, quantity));

  const duplicateSerials = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of entries) {
      const serial = entry.serial_number.trim();
      counts.set(serial, (counts.get(serial) ?? 0) + 1);
    }
    return new Set(
      [...counts.entries()]
        .filter(([, count]) => count > 1)
        .map(([serial]) => serial),
    );
  }, [entries]);

  const handlePasteChange = (value: string) => {
    setPasteValue(value);
    const parsed = parseSerials(value).map((entry) => ({
      ...entry,
      asset_tag: useSerialAsAssetTag ? entry.serial_number : undefined,
    }));
    setEntries(parsed);
  };

  const handleGenerate = useCallback(() => {
    const generated = generateSerials(
      prefix.trim() || "ASSET",
      requestedQuantity,
    ).map((entry) => ({
      ...entry,
      asset_tag: useSerialAsAssetTag ? entry.serial_number : undefined,
    }));
    setEntries(generated);
  }, [prefix, requestedQuantity, useSerialAsAssetTag]);

  const updateSerial = (index: number, value: string) => {
    setEntries((current) =>
      current.map((entry, entryIndex) =>
        entryIndex === index
          ? {
              ...entry,
              serial_number: value,
              asset_tag: useSerialAsAssetTag ? value : entry.asset_tag,
            }
          : entry,
      ),
    );
  };

  const removeEntry = (index: number) => {
    setEntries((current) =>
      current.filter((_, entryIndex) => entryIndex !== index),
    );
  };

  const handleAssetTagChange = (checked: boolean) => {
    setUseSerialAsAssetTag(checked);
    setEntries((current) =>
      current.map((entry) => ({
        ...entry,
        asset_tag: checked ? entry.serial_number : undefined,
      })),
    );
  };

  const handleSubmit = () => {
    if (entries.length === 0 || duplicateSerials.size > 0) return;
    onSubmit(
      entries.map((entry) => ({
        serial_number: entry.serial_number.trim(),
        asset_tag: entry.asset_tag?.trim() || undefined,
      })),
      { assignLabels, qrOnly },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t("bulk.title", "Serial numbers")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Tabs defaultValue="paste">
          <TabsList className="w-full">
            <TabsTrigger value="paste" icon={<ClipboardPaste size={16} />}>
              {t("bulk.pasteTab", "Paste list")}
            </TabsTrigger>
            <TabsTrigger value="generate" icon={<Wand2 size={16} />}>
              {t("bulk.generateTab", "Generate")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="paste" className="space-y-2 pt-2">
            <Textarea
              label={t("bulk.pasteLabel", "Serial numbers")}
              id="bulk-serials-paste"
              value={pasteValue}
              onChange={(event) => handlePasteChange(event.target.value)}
              placeholder={t(
                "bulk.pastePlaceholder",
                "One serial number per line",
              )}
              rows={6}
              className="w-full rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-on placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all duration-200 resize-y"
            />
          </TabsContent>
          <TabsContent value="generate" className="space-y-4 pt-2">
            <div className="grid grid-cols-1 sm:grid-cols-[120px_1fr] gap-3">
              <Input
                id="bulk-quantity"
                label={t("bulk.quantity", "Quantity")}
                type="number"
                min={1}
                max={MAX_ENTRIES}
                value={quantity}
                onChange={(event) => {
                  const next = event.target.value.trim();
                  const parsed = Number(next);
                  setQuantity(
                    next === "" || Number.isNaN(parsed) ? "" : parsed,
                  );
                }}
              />
              <Input
                id="bulk-prefix"
                label={t("bulk.prefix", "Prefix")}
                value={prefix}
                onChange={(event) => setPrefix(event.target.value)}
                placeholder={t("bulk.prefixPlaceholder", "e.g. DELL-LAT5540")}
              />
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={handleGenerate}
              className="w-full"
              leftIcon={<Wand2 size={16} />}
            >
              {t("bulk.generate", {
                count: requestedQuantity,
              })}
            </Button>
          </TabsContent>
        </Tabs>

        <Checkbox
          id="bulk-use-serial-as-asset-tag"
          checked={useSerialAsAssetTag}
          onChange={(event) => handleAssetTagChange(event.target.checked)}
          label={t(
            "bulk.useSerialAsAssetTag",
            "Use serial number as asset tag",
          )}
        />

        <div className="space-y-2">
          <Checkbox
            id="bulk-assign-qr-labels"
            checked={assignLabels}
            onChange={(event) => setAssignLabels(event.target.checked)}
            label={t("bulk.assignQrLabels", "Generate & assign QR labels")}
          />
          {assignLabels ? (
            <div className="ml-6 flex flex-wrap items-center gap-3 text-sm text-on-secondary">
              <span>{t("bulk.labelContent", "Label content:")}</span>
              <label className="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="qr-content"
                  checked={!qrOnly}
                  onChange={() => setQrOnly(false)}
                  className="accent-primary-600"
                />
                {t("bulk.contentCodeName", "Name")}
              </label>
              <label className="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="qr-content"
                  checked={qrOnly}
                  onChange={() => setQrOnly(true)}
                  className="accent-primary-600"
                />
                {t("bulk.contentCodeOnly", "QR square only")}
              </label>
            </div>
          ) : null}
        </div>

        {entries.length > 0 ? (
          <div className="space-y-2">
            <p
              className={
                duplicateSerials.size > 0
                  ? "text-sm font-medium text-red-600"
                  : "text-sm font-medium text-accent-600"
              }
              role={duplicateSerials.size > 0 ? "alert" : "status"}
            >
              {duplicateSerials.size > 0
                ? t(
                    "bulk.duplicatesFound",
                    "Duplicate serial numbers detected.",
                  )
                : t("bulk.detected", {
                    count: entries.length,
                  })}
            </p>
            <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
              {entries.map((entry, index) => {
                const isDuplicate = duplicateSerials.has(
                  entry.serial_number.trim(),
                );
                return (
                  <div key={index} className="flex items-center gap-2">
                    <Input
                      value={entry.serial_number}
                      aria-label={t("bulk.serial_label", "Serial number")}
                      onChange={(event) =>
                        updateSerial(index, event.target.value)
                      }
                      error={
                        isDuplicate ? t("bulk.duplicate", "Duplicate") : ""
                      }
                    />
                    {/* ui-pattern: destructive-as-neutral — this drops a
                        row from the form being typed, and nothing here has
                        ever been saved to warn anybody about */}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeEntry(index)}
                      aria-label={t("bulk.remove", "Remove")}
                      className="shrink-0"
                    >
                      <X size={18} />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        <div className="flex gap-3 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            className="flex-1"
            disabled={isSubmitting}
          >
            {t("bulk.cancel", "Cancel")}
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            className="flex-1"
            disabled={
              entries.length === 0 || duplicateSerials.size > 0 || isSubmitting
            }
            isLoading={isSubmitting}
          >
            {t("bulk.create", {
              count: entries.length,
            })}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
