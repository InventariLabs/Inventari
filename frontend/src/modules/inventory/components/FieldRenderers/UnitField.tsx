import { UomSelect } from "@/modules/shared/components/UomSelect";
import type { Uom } from "@/types";

interface UnitFieldProps {
  uomId: string | undefined;
  error?: string;
  onChange: (uomId: string, uom: Uom) => void;
}

export function UnitField({ uomId, error, onChange }: UnitFieldProps) {
  return <UomSelect value={uomId || null} onChange={onChange} error={error} />;
}
