import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ScanLine } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { labelsApi } from "@/lib/api/labels";
import { scanLookupError } from "@/module-sdk";

interface StorageScanFieldProps {
  /**
   * The location the label names. Return `false` when the caller cannot take
   * it (a move destination, say) so the field keeps what was scanned.
   */
  onSelect: (id: string, code: string) => boolean | void;
}

/**
 * The field a location label is scanned into.
 *
 * Scanning is what the floor does instead of walking a tree; typing a short
 * code into the same field does the same thing, so a label whose print is
 * still in the printer is not a dead end.
 */
export function StorageScanField({ onSelect }: StorageScanFieldProps) {
  const { t } = useTranslation(["locations"]);
  const [scan, setScan] = useState("");
  const [isScanning, setIsScanning] = useState(false);

  const accept = (id: string, code: string) => {
    if (onSelect(id, code) === false) return;
    setScan("");
  };

  const handleScan = async () => {
    const code = scan.trim();
    if (!code || isScanning) return;
    setIsScanning(true);
    try {
      // The field accepts a typed short code as well as a scanned label: the
      // label lookup resolves both.
      const view = await labelsApi.scan(code);
      if (view.location?.id) {
        accept(view.location.id, code);
        return;
      }
      toast.error(t("locations:tree.scanNotLocation", { code }));
    } catch (error) {
      toast.error(
        scanLookupError(error, t("locations:tree.scanNotFound", { code }), t),
      );
    } finally {
      setIsScanning(false);
    }
  };

  return (
    <div className="flex gap-2">
      <Input
        leftIcon={<ScanLine size={16} />}
        aria-label={t("locations:tree.scanPlaceholder")}
        placeholder={t("locations:tree.scanPlaceholder")}
        value={scan}
        onChange={(event) => setScan(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") void handleScan();
        }}
      />
      <Button
        type="button"
        variant="secondary"
        size="icon"
        aria-label={t("locations:tree.scanAction")}
        onClick={() => void handleScan()}
        disabled={!scan.trim() || isScanning}
      >
        <ScanLine size={18} />
      </Button>
    </div>
  );
}
