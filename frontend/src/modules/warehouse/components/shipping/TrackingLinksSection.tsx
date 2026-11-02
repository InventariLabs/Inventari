import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useCanManage } from "@/hooks/useCanWrite";
import { usePageSavePart } from "@/module-sdk";
import {
  useDocumentProfile,
  useUpdateDocumentProfile,
} from "@/modules/warehouse/hooks/useDocumentProfile";
import { SettingsSectionHeader } from "../SettingsSectionHeader";

interface Row {
  key: number;
  carrier: string;
  url: string;
}

const toRows = (templates: Record<string, string> | null | undefined): Row[] =>
  Object.entries(templates ?? {}).map(([carrier, url], key) => ({
    key,
    carrier,
    url,
  }));

const toTemplates = (rows: Row[]): Record<string, string> =>
  Object.fromEntries(
    rows
      .filter((row) => row.carrier.trim() || row.url.trim())
      .map((row) => [row.carrier.trim(), row.url.trim()]),
  );

const sameTemplates = (a: Record<string, string>, b: Record<string, string>) =>
  JSON.stringify(Object.entries(a)) === JSON.stringify(Object.entries(b));

/**
 * The organization's own tracking links: a carrier name and its tracking
 * page with `{tracking_number}` where the number goes, read before the
 * links the app knows by itself.
 *
 * It keeps its own rows and writes only this field when the page's Save
 * runs, so neither it nor the profile form can overwrite what the other holds.
 * The server checks each link and names the carrier whose link it refuses.
 */
export function TrackingLinksSection() {
  const { t } = useTranslation("warehouse");
  const canManage = useCanManage("warehouse");
  const { data: profile } = useDocumentProfile();
  const update = useUpdateDocumentProfile();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [nextKey, setNextKey] = useState(1000);

  useEffect(() => {
    if (profile && rows === null)
      setRows(toRows(profile.tracking_url_templates));
  }, [profile, rows]);

  const saved = toTemplates(toRows(profile?.tracking_url_templates));
  const drafted = toTemplates(rows ?? []);
  const dirty = rows !== null && !sameTemplates(saved, drafted);

  const save = async () => {
    const answer = await update.mutateAsync({
      tracking_url_templates: drafted,
    });
    setRows(toRows(answer.tracking_url_templates));
  };
  usePageSavePart("trackingLinks", dirty, save);

  if (!profile || rows === null) return null;

  const edit = (key: number, change: Partial<Row>) =>
    setRows(rows.map((row) => (row.key === key ? { ...row, ...change } : row)));

  return (
    <section>
      <SettingsSectionHeader
        title={t("shipping.linksTitle")}
        // The token is the literal the reader types, not a placeholder of ours.
        hint={t("shipping.linksHint", { token: "{tracking_number}" })}
      />
      <Card>
        <CardContent className="p-4 sm:p-6 space-y-3">
          {rows.length === 0 && (
            <p className="text-sm text-on-secondary">
              {t("shipping.linksNone")}
            </p>
          )}
          {rows.map((row) => (
            <div
              key={row.key}
              className="grid grid-cols-1 gap-2 sm:grid-cols-[12rem_1fr_auto] sm:items-end"
            >
              <Input
                label={t("shipping.carrier")}
                value={row.carrier}
                maxLength={100}
                disabled={!canManage}
                onChange={(e) => edit(row.key, { carrier: e.target.value })}
              />
              <Input
                label={t("shipping.linkTemplate")}
                value={row.url}
                maxLength={500}
                inputMode="url"
                placeholder="https://…?number={tracking_number}"
                disabled={!canManage}
                onChange={(e) => edit(row.key, { url: e.target.value })}
              />
              {canManage && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("shipping.linkRemove", {
                    carrier: row.carrier || "—",
                  })}
                  onClick={() =>
                    setRows(rows.filter((other) => other.key !== row.key))
                  }
                >
                  <Trash2 size={16} />
                </Button>
              )}
            </div>
          ))}
          {canManage && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Plus size={16} />}
              onClick={() => {
                setRows([...rows, { key: nextKey, carrier: "", url: "" }]);
                setNextKey(nextKey + 1);
              }}
            >
              {t("shipping.linkAdd")}
            </Button>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
