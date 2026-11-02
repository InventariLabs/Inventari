import { Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { Input } from "@/components/ui/Input";
import type { LabelPool } from "@/types";
import type { PrintSettings } from "./LabelPreviewModal";

/**
 * Sizes worth offering, by what the label is going to carry.
 *
 * Every preset used to be wider than it was tall — right for a label that
 * carries a sentence, wrong for one that carries a square. A QR alone on a
 * 50 x 24 die-cut label leaves three fifths of it blank, and on a sheet
 * there is nothing to trim: the label is the size of the die, so the only
 * lever is which die.
 *
 * The short code sits under the square rather than beside it, so a label
 * carrying only the code is as square as one carrying only the QR. What
 * decides the shape is the description, not the code.
 *
 * A preset carries the word and the two numbers separately, and the button
 * joins them. The seven names used to be English sentences with the size
 * baked in ("Narrow (50x12)"), read aloud in every language by a reader who
 * could see the numbers but not the word; the word is a catalogue key now
 * and the numbers are the same ones the fields below accept.
 */
const WIDE_PRESETS = [
  { word: "previewModal.preset.standard", width: 50, height: 24 },
  { word: "previewModal.preset.small", width: 38, height: 15 },
  { word: "previewModal.preset.large", width: 62, height: 29 },
  { word: "previewModal.preset.narrow", width: 50, height: 12 },
] as const;

const SQUARE_PRESETS = [
  { word: "previewModal.preset.square", width: 24, height: 24 },
  { word: "previewModal.preset.square", width: 30, height: 30 },
  { word: "previewModal.preset.square", width: 40, height: 40 },
] as const;

type LabelPreset = { word: string; width: number; height: number };

const ALL_PRESETS: readonly LabelPreset[] = [
  ...WIDE_PRESETS,
  ...SQUARE_PRESETS,
];

/** "Wąska 50×12" — the word from the catalogue, the millimetres from here. */
const labelPresetName = (
  t: (key: string, options?: Record<string, unknown>) => string,
  preset: LabelPreset,
): string =>
  `${t(preset.word, { ns: "labels" })} ${preset.width}×${preset.height}`;

/**
 * What goes on the label besides the QR — one question, four answers.
 *
 * It used to be two independent switches, "QR code only (no text)" and
 * "Also print the code", and between them the word "code" meant two
 * different things: the square in the first, the string STM-K9XP in the
 * second. They also described one choice badly. Three of the four
 * arrangements were reachable and the fourth — the short code with no
 * caption — was not expressible at all, because "QR only" was read as
 * "no text" rather than "no caption".
 *
 * As a radio group the whole choice is visible whichever answer is
 * current, and nothing appears or disappears under the pointer: the
 * conditional row used to collapse the panel and move every control below
 * it while somebody was reaching for one.
 */
type LabelContent =
  "description" | "descriptionAndCode" | "codeOnly" | "qrOnly";

const CONTENT_STATES: Record<
  LabelContent,
  { qrOnly: boolean; showCode: boolean }
> = {
  description: { qrOnly: false, showCode: false },
  descriptionAndCode: { qrOnly: false, showCode: true },
  codeOnly: { qrOnly: true, showCode: true },
  qrOnly: { qrOnly: true, showCode: false },
};

function presetsFor(content: LabelContent): readonly LabelPreset[] {
  return content === "description" || content === "descriptionAndCode"
    ? WIDE_PRESETS
    : SQUARE_PRESETS;
}

/**
 * The size that should follow a change of content, if any.
 *
 * A preset is a guess about the labels somebody has, so it follows the
 * content: pick "QR square only" and the sizes on offer become square ones.
 * A size typed by hand is not a guess — somebody measured their labels — so
 * it is left exactly where it is. The difference between the two is whether
 * the current size is one of the presets.
 */
function sizeFollowing(
  settings: PrintSettings,
  content: LabelContent,
): { width: number; height: number } | null {
  const next = presetsFor(content);
  const matches = (p: LabelPreset) =>
    p.width === settings.width && p.height === settings.height;
  if (next.some(matches) || !ALL_PRESETS.some(matches)) return null;
  return { width: next[0].width, height: next[0].height };
}

function contentOf(settings: PrintSettings): LabelContent {
  if (settings.qrOnly) return settings.showCode ? "codeOnly" : "qrOnly";
  return settings.showCode ? "descriptionAndCode" : "description";
}

interface LabelSettingsSidebarProps {
  selectedLabels: LabelPool[];
  printSettings: PrintSettings;
  setPrintSettings: React.Dispatch<React.SetStateAction<PrintSettings>>;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function LabelSettingsSidebar({
  selectedLabels,
  printSettings,
  setPrintSettings,
  t,
}: LabelSettingsSidebarProps) {
  return (
    <div className="w-full md:w-72 bg-surface-card md:border-r md:border-border p-4 md:p-6 md:overflow-y-auto space-y-4 md:space-y-6">
      <div>
        <p className="block text-[10px] font-medium text-on-muted uppercase tracking-widest mb-3">
          {t("previewModal.presets", { ns: "labels" })}
        </p>
        <div className="grid grid-cols-2 md:grid-cols-1 gap-2">
          {presetsFor(contentOf(printSettings)).map((preset) => (
            <Button
              key={`${preset.width}×${preset.height}`}
              variant={
                printSettings.width === preset.width &&
                printSettings.height === preset.height
                  ? "default"
                  : "outline"
              }
              size="sm"
              onClick={() =>
                setPrintSettings({
                  ...printSettings,
                  width: preset.width,
                  height: preset.height,
                })
              }
              className="text-left justify-start"
            >
              {labelPresetName(t, preset)}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-1 gap-4 md:gap-6">
        <div className="space-y-3">
          <p className="block text-[10px] font-medium text-on-muted uppercase tracking-widest">
            {t("previewModal.globalSettings", { ns: "labels" })}
          </p>
          {/* Plain fields. These used to carry a filled inset background and
              no visible border of their own, which is what a disabled field
              looks like everywhere else in the app — and the label sat in a
              loose <span>, so nothing named the input for a reader. */}
          <Input
            label={t("previewModal.labelDescription", { ns: "labels" })}
            type="text"
            value={printSettings.customDescription}
            onChange={(e) =>
              setPrintSettings({
                ...printSettings,
                customDescription: e.target.value,
              })
            }
            placeholder={t("previewModal.labelDescriptionPlaceholder", {
              ns: "labels",
              defaultValue: "e.g. Grandma's Jam",
            })}
          />
        </div>

        <div className="space-y-3">
          <p className="block text-[10px] font-medium text-on-muted uppercase tracking-widest">
            {t("previewModal.customSize", { ns: "labels" })}
          </p>
          {/* items-end so a label that wraps to two lines lifts its own
              box instead of pushing its input below the neighbour's. In
              English neither wraps; in Polish the first one does. */}
          <div className="grid grid-cols-2 gap-3 items-end">
            <Input
              label={`${t("previewModal.width", { ns: "labels" })} (mm)`}
              type="number"
              value={printSettings.width}
              onChange={(e) =>
                setPrintSettings({
                  ...printSettings,
                  width: parseFloat(e.target.value) || 0,
                })
              }
              className="dark:[color-scheme:dark]"
            />
            <Input
              label={`${t("previewModal.height", { ns: "labels" })} (mm)`}
              type="number"
              value={printSettings.height}
              onChange={(e) =>
                setPrintSettings({
                  ...printSettings,
                  height: parseFloat(e.target.value) || 0,
                })
              }
              className="dark:[color-scheme:dark]"
            />
          </div>
        </div>
      </div>

      <ChoiceGroup
        label={t("previewModal.labelContent", { ns: "labels" })}
        // Flowed, not gridded: three columns in a 288 px panel break
        // "Description and short code" across three lines.
        layout="wrap"
        value={contentOf(printSettings)}
        onChange={(id) =>
          setPrintSettings({
            ...printSettings,
            ...CONTENT_STATES[id as LabelContent],
            ...(sizeFollowing(printSettings, id as LabelContent) ?? {}),
          })
        }
        options={[
          {
            id: "description",
            label: t("previewModal.content.description", { ns: "labels" }),
          },
          {
            id: "descriptionAndCode",
            label: t("previewModal.content.descriptionAndCode", {
              ns: "labels",
            }),
          },
          {
            id: "codeOnly",
            label: t("previewModal.content.codeOnly", { ns: "labels" }),
          },
          {
            id: "qrOnly",
            label: t("previewModal.content.qrOnly", { ns: "labels" }),
          },
        ]}
      />

      <div className="space-y-3">
        <p className="block text-[10px] font-medium text-on-muted uppercase tracking-widest">
          {t("previewModal.copies", {
            ns: "labels",
            defaultValue: "Copies per label",
          })}
        </p>
        {selectedLabels.length === 1 &&
          selectedLabels[0].assigned_item_quantity && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setPrintSettings({
                  ...printSettings,
                  copiesPerLabel: selectedLabels[0].assigned_item_quantity!,
                })
              }
              className="w-full text-left justify-start"
            >
              ↑{" "}
              {t("previewModal.copiesSuggest", {
                ns: "labels",
                defaultValue: "Set to product qty",
              })}
              : {selectedLabels[0].assigned_item_quantity}{" "}
              {selectedLabels[0].assigned_item_unit ?? ""}
            </Button>
          )}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="iconSm"
            onClick={() =>
              setPrintSettings({
                ...printSettings,
                copiesPerLabel: Math.max(1, printSettings.copiesPerLabel - 1),
              })
            }
            aria-label={t("actions.decrease", { ns: "common" })}
          >
            <Minus size={14} />
          </Button>
          <Input
            wrapperClassName="flex-1"
            type="number"
            min={1}
            max={200}
            value={printSettings.copiesPerLabel}
            onChange={(e) =>
              setPrintSettings({
                ...printSettings,
                copiesPerLabel: Math.max(
                  1,
                  Math.min(200, parseInt(e.target.value) || 1),
                ),
              })
            }
            aria-label={t("previewModal.copies", { ns: "labels" })}
            className="text-center dark:[color-scheme:dark]"
          />
          <Button
            variant="outline"
            size="iconSm"
            onClick={() =>
              setPrintSettings({
                ...printSettings,
                copiesPerLabel: Math.min(200, printSettings.copiesPerLabel + 1),
              })
            }
            aria-label={t("actions.increase", { ns: "common" })}
          >
            <Plus size={14} />
          </Button>
        </div>
        {printSettings.copiesPerLabel > 1 && (
          <p className="text-[10px] text-on-muted leading-relaxed">
            {t("previewModal.copiesTotal", {
              ns: "labels",
              defaultValue: "Total labels to print",
            })}
            :{" "}
            <span className="font-semibold text-on">
              {selectedLabels.length * printSettings.copiesPerLabel}
            </span>
          </p>
        )}
      </div>

      <div className="p-4 bg-surface-raised rounded-2xl border border-border md:block hidden">
        <p className="text-[10px] text-on-secondary leading-relaxed font-medium">
          <span className="font-medium uppercase tracking-wider">
            {t("previewModal.tipTitle", { ns: "labels" })}
          </span>
          <br />
          {t("previewModal.tip", { ns: "labels" })}
        </p>
      </div>
    </div>
  );
}
