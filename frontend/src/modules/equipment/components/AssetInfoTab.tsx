import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Tag,
  Monitor,
  Hash,
  Calendar,
  DollarSign,
  Wrench,
  ImageOff,
  Download,
  Loader2,
  MapPin,
  User,
  CalendarClock,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InfoRow } from "@/modules/equipment/components/AssetInfoRow";
import { formatMoney } from "@/utils/formatters";
import { downloadBlob } from "@/utils/helpers";
import { extractApiError } from "@/lib/errors";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useExportLabelPng } from "@/modules/shared/hooks/useLabels";
import { ValuationCard } from "@/modules/equipment/components/ValuationCard";
import {
  fmt,
  getCategoryLabel,
  getEquipmentMeta,
} from "@/modules/equipment/components/assetUtils";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { useAssetImage } from "@/modules/equipment/hooks/useAssetImage";
import { useLocationLabel } from "@/modules/equipment/hooks/useLocationLabel";
import { itemsApi } from "@/lib/api/items";
import { toast } from "sonner";
import { formatDate } from "@/utils/helpers";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import type { EquipmentAssignment } from "@/modules/equipment/api/equipment";
import type { Item, CategoryDTO, FieldDefinition } from "@/types";

interface InfoTabProps {
  item: Item;
  /** The open checkout, if any: who or where has the asset right now. */
  activeAssignment?: EquipmentAssignment | null;
  onImageChanged?: () => void;
}

/**
 * Who has the asset, since when and until when — the module's own question.
 *
 * It was answered only on the Assignments tab, so the page a scanned QR code
 * opens said "Checked out" and left the reader to go looking for by whom.
 * This card leads the default tab, which is the first screen on a phone too.
 */
function HolderCard({ assignment }: { assignment: EquipmentAssignment }) {
  const { t } = useTranslation("equipment");
  const formatOrgDay = useFormatOrgDay();
  const isPlace = assignment.holder_kind === "location";
  const name =
    assignment.holder_name ??
    assignment.checkout_location_name ??
    assignment.assigned_to_name;
  return (
    <Card>
      <CardContent>
        <InfoRow
          icon={isPlace ? <MapPin size={14} /> : <User size={14} />}
          label={
            isPlace ? t("assignments.standing_in") : t("assignments.held_by")
          }
          value={
            <>
              <div>{name}</div>
              {!isPlace && assignment.assigned_to_email && (
                <div className="text-xs font-normal text-on-muted">
                  {assignment.assigned_to_email}
                </div>
              )}
            </>
          }
        />
        <InfoRow
          icon={<Calendar size={14} />}
          label={t("assignments.checked_out_at")}
          value={formatDate(assignment.checked_out_at)}
        />
        <InfoRow
          icon={<CalendarClock size={14} />}
          label={t("assignments.expected_return")}
          value={
            assignment.expected_return_at
              ? formatOrgDay(assignment.expected_return_at)
              : null
          }
        />
      </CardContent>
    </Card>
  );
}

/**
 * Where the asset is. Checked out to a place, it stands there until it comes
 * back: that is its location, with its own location — the home the return
 * goes to — beneath it. The row used to name the home alone while the list's
 * holder column named the place.
 */
function LocationRow({
  item,
  activeAssignment,
}: {
  item: Item;
  activeAssignment?: EquipmentAssignment | null;
}) {
  const { t } = useTranslation("equipment");
  // The detail card must answer "where is it" — resolved through the
  // org-wide storage list, so a seeded location reads in the reader's
  // language, not as the English literal from install day.
  const placeId =
    activeAssignment?.holder_kind === "location"
      ? activeAssignment.checkout_location_id
      : null;
  const locationLabel = useLocationLabel([item.location_id, placeId]);
  const homeName = locationLabel(item.location_id, null);
  const whereName = placeId
    ? locationLabel(placeId, activeAssignment?.checkout_location_name ?? null)
    : homeName;
  return (
    <InfoRow
      icon={<MapPin size={14} />}
      label={t("form.fields.location", "Location")}
      value={
        whereName ? (
          <>
            <Link
              to={`/equipment/assets?location=${placeId ?? item.location_id}`}
              className="text-on-primary underline-offset-2 hover:underline"
            >
              {whereName}
            </Link>
            {placeId && homeName && (
              <div className="text-xs font-normal text-on-muted">
                {t("detail.home_location", { name: homeName })}
              </div>
            )}
          </>
        ) : null
      }
    />
  );
}

export function InfoTab({
  item,
  activeAssignment,
  onImageChanged,
}: InfoTabProps) {
  const { t, i18n } = useTranslation("equipment");
  const currency = useOrganizationCurrency();
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const {
    data: allCategories = [],
    error: categoriesError,
    refetch: refetchCategories,
  } = useAllCategories();
  const meta = getEquipmentMeta(item);
  const image = useAssetImage()(item);

  const handleDeleteImage = async () => {
    try {
      await itemsApi.deleteImage(item.id);
      onImageChanged?.();
      toast.success(t("form.image_deleted", "Image deleted"));
    } catch {
      toast.error(t("form.errors.saveFailed", "Failed to delete image"));
    }
  };

  const exportLabelPng = useExportLabelPng();
  const handleDownloadQr = async () => {
    if (!item.label_code) return;
    try {
      const blob = await exportLabelPng.mutateAsync({
        count: 1,
        shortCodes: [item.label_code],
        width: 50,
        height: 24,
      });
      downloadBlob(blob, `${item.label_code}.png`);
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("qr.downloadFailed", "Failed to download QR label"),
        ),
      );
    }
  };

  const category = allCategories.find(
    (c: CategoryDTO) => c.id === item.category_id,
  );
  const rawMeta = (item.metadata?.equipment ?? {}) as Record<string, unknown>;

  const HARDCODED_KEYS = new Set([
    "manufacturer",
    "model",
    "serial_number",
    "asset_tag",
    "purchase_date",
    "warranty_until",
    "notes",
    "equipment_status",
    "status",
  ]);

  // The category's field definitions cross the wire as open dicts; the
  // entries are the shared FieldDefinition shape — narrowed once, here.
  const extraFields = (
    (category?.field_definitions ?? []) as FieldDefinition[]
  ).filter(
    (f: FieldDefinition) => f.visible !== false && !HARDCODED_KEYS.has(f.key),
  );

  return (
    <div className="space-y-4">
      {activeAssignment && <HolderCard assignment={activeAssignment} />}
      {image ? (
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-start gap-4">
              <img
                src={image.url}
                alt={item.name}
                loading="lazy"
                className="h-32 w-auto rounded-lg object-cover"
              />
              {!item.is_deleted && (
                <div className="flex flex-col gap-2">
                  {image.fromModel ? (
                    // Deleting it here would delete the model's picture for
                    // every unit, so the offer is to give this one its own.
                    <p className="text-xs text-on-muted max-w-52">
                      {t("form.image_from_model")}
                    </p>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleDeleteImage}
                      leftIcon={<ImageOff size={14} />}
                    >
                      {t("form.delete_image", "Delete image")}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {t("form.sections.basic", "Basic Info")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <InfoRow
            icon={<Tag size={14} />}
            label={t("form.fields.category", "Category")}
            value={
              item.category ? getCategoryLabel(t, item.category) : undefined
            }
          />
          <LocationRow item={item} activeAssignment={activeAssignment} />
          <InfoRow
            icon={<Monitor size={14} />}
            label={t("form.fields.manufacturer", "Manufacturer")}
            value={meta.manufacturer}
          />
          <InfoRow
            icon={<Monitor size={14} />}
            label={t("form.fields.model", "Model")}
            value={meta.model}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {t("form.sections.identification", "Identification")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <InfoRow
            icon={<Hash size={14} />}
            label={t("form.fields.serialNumber", "Serial Number")}
            value={meta.serial_number}
          />
          <InfoRow
            icon={<Tag size={14} />}
            label={t("form.fields.assetTag", "Asset Tag")}
            value={meta.asset_tag}
          />
          <InfoRow
            icon={<Hash size={14} />}
            label={t("form.fields.barcode", "Barcode")}
            value={item.barcode}
          />
          {item.label_code && (
            <div className="flex items-center gap-3 py-2 border-b border-border last:border-0">
              <div className="flex-shrink-0 w-4 mt-0.5 text-on-muted flex justify-center">
                <Tag size={14} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-on-muted mb-0.5">
                  {t("qr.label", "QR Label")}
                </div>
                <div className="text-sm text-on font-mono break-all">
                  {item.label_code}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleDownloadQr}
                disabled={exportLabelPng.isPending}
                leftIcon={
                  exportLabelPng.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Download size={14} />
                  )
                }
                className="shrink-0"
              >
                {t("qr.download", "Download")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {t("form.sections.purchase", "Purchase & Warranty")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <InfoRow
            icon={<Calendar size={14} />}
            label={t("form.fields.purchaseDate", "Purchase Date")}
            value={fmt(meta.purchase_date)}
          />
          <InfoRow
            icon={<DollarSign size={14} />}
            label={t("form.fields.purchasePrice", "Purchase Price")}
            value={
              item.purchase_price != null
                ? formatMoney(item.purchase_price, currency, lang)
                : null
            }
          />
          <InfoRow
            icon={<Calendar size={14} />}
            label={t("form.fields.warrantyUntil", "Warranty Until")}
            value={fmt(meta.warranty_until)}
          />
        </CardContent>
      </Card>

      <ValuationCard itemId={item.id} />

      {meta.notes && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-on-secondary whitespace-pre-wrap">
              {meta.notes}
            </p>
          </CardContent>
        </Card>
      )}

      {/* The category carries the definitions of the fields below; without it
          the card vanishes and the asset reads as having no details. */}
      {categoriesError && (
        <Card>
          <CardContent className="pt-4">
            <InlineQueryError
              error={categoriesError}
              onRetry={() => void refetchCategories()}
            />
          </CardContent>
        </Card>
      )}

      {extraFields.length > 0 && extraFields.some((f) => rawMeta[f.key]) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              {t("form.sections.details", "Details")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {extraFields.map((f: FieldDefinition) => {
              const raw = rawMeta[f.key];
              if (raw == null || raw === "") return null;
              const display =
                f.type === "date" ? fmt(String(raw)) : String(raw);
              return (
                <InfoRow
                  key={f.key}
                  icon={<Wrench size={14} />}
                  label={f.label ?? f.key}
                  value={display}
                />
              );
            })}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
