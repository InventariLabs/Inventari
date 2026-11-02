import { useTranslation } from "react-i18next";
import type { ImportMapping, MappingField } from "./types";

interface ImportPreviewTableProps {
  /** The first rows of the source, as the server read them. */
  rows: Record<string, unknown>[];
  /** The fields the mapping step offers, in the order it offers them. */
  fields: MappingField[];
  /** Which sheet column feeds which field. */
  mapping: ImportMapping;
}

/** What the mapping actually reads, on the rows the reader can see.
 *
 * Every importer here used to ask for a mapping and show no data at all: a
 * sheet with a shifted header row, or one pandas split on the wrong
 * delimiter, looked correctly mapped and the mismatch only turned up after
 * the rows had been written. The columns are the mapped fields rather than
 * the file's own, because the question this answers is not "what is in the
 * file" but "is *this* the column I just called Quantity".
 *
 * Rows are numbered as the refusals are: data rows from 1, the header not
 * counted, so "row 3" names the same row on both screens.
 */
export function ImportPreviewTable({
  rows,
  fields,
  mapping,
}: ImportPreviewTableProps) {
  const { t } = useTranslation(["common"]);
  const mapped = fields.filter((field) => mapping[field.key]);
  if (rows.length === 0 || mapped.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-on-muted uppercase tracking-widest">
        {t("common:import.previewTitle")}
      </h3>
      <div className="border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-surface-raised">
            <tr>
              <th scope="col" className="px-2 py-1.5 text-left font-medium">
                #
              </th>
              {mapped.map((field) => (
                <th
                  key={field.key}
                  scope="col"
                  className="px-2 py-1.5 text-left font-medium whitespace-nowrap"
                >
                  {field.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="border-t border-border">
                <td className="px-2 py-1.5 text-on-muted">{index + 1}</td>
                {mapped.map((field) => (
                  <td key={field.key} className="px-2 py-1.5 text-on">
                    {String(row[mapping[field.key]] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-on-muted">{t("common:import.previewHint")}</p>
    </div>
  );
}
