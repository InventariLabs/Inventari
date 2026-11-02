import {
  Bold,
  Italic,
  Heading2,
  List,
  ListOrdered,
  Eye,
  EyeOff,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface InstructionsMarkdownToolbarProps {
  mdPreview: boolean;
  onTogglePreview: () => void;
  onBold: () => void;
  onItalic: () => void;
  onHeading: () => void;
  onBulletList: () => void;
  onOrderedList: () => void;
  t: (key: string) => string;
  /** Sits directly on top of a textarea: square bottom, no bottom border. */
  attached?: boolean;
}

export function InstructionsMarkdownToolbar({
  mdPreview,
  onTogglePreview,
  onBold,
  onItalic,
  onHeading,
  onBulletList,
  onOrderedList,
  t,
  attached = false,
}: InstructionsMarkdownToolbarProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-0.5 border border-border bg-surface px-2 py-1",
        attached ? "rounded-t-xl border-b-0" : "rounded-lg",
      )}
    >
      {!mdPreview && (
        <>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onBold}
            aria-label={t("recipes:import_export.md_bold")}
            title={t("recipes:import_export.md_bold")}
            className="rounded hover:bg-surface-inset"
          >
            <Bold size={16} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onItalic}
            aria-label={t("recipes:import_export.md_italic")}
            title={t("recipes:import_export.md_italic")}
            className="rounded hover:bg-surface-inset"
          >
            <Italic size={16} />
          </Button>
          <div className="w-px h-4 bg-surface-inset mx-1" />
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onHeading}
            aria-label={t("recipes:import_export.md_heading")}
            title={t("recipes:import_export.md_heading")}
            className="rounded hover:bg-surface-inset"
          >
            <Heading2 size={16} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onBulletList}
            aria-label={t("recipes:import_export.md_bullet_list")}
            title={t("recipes:import_export.md_bullet_list")}
            className="rounded hover:bg-surface-inset"
          >
            <List size={16} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onOrderedList}
            aria-label={t("recipes:import_export.md_ordered_list")}
            title={t("recipes:import_export.md_ordered_list")}
            className="rounded hover:bg-surface-inset"
          >
            <ListOrdered size={16} />
          </Button>
        </>
      )}
      <Button
        size="content"
        type="button"
        variant="ghost"
        onClick={onTogglePreview}
        aria-label={
          mdPreview
            ? t("recipes:import_export.md_edit")
            : t("recipes:import_export.md_preview")
        }
        className={cn(
          "ml-auto gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium",
          mdPreview
            ? "bg-primary-50 text-on font-medium"
            : "hover:bg-surface-inset",
        )}
      >
        {mdPreview ? <EyeOff size={16} /> : <Eye size={16} />}
        {mdPreview
          ? t("recipes:import_export.md_edit")
          : t("recipes:import_export.md_preview")}
      </Button>
    </div>
  );
}
