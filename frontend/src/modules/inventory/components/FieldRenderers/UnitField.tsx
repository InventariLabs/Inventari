import { UomSelect } from "@/modules/shared/components/UomSelect";
import type { Uom } from "@/types";
import { UnitLockedHint } from "./UnitLockedHint";

interface UnitFieldProps {
  uomId: string | undefined;
  error?: string;
  /** The record holds stock: the picker is disabled and says why. */
  locked?: boolean;
  onChange: (uomId: string, uom: Uom) => void;
}

export function UnitField({ uomId, error, locked, onChange }: UnitFieldProps) {
  return (
    <>
      <UomSelect
        value={uomId || null}
        onChange={onChange}
        error={error}
        disabled={locked}
      />
      {locked && <UnitLockedHint />}
    </>
  );
}
