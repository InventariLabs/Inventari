import { Eye, FileText, Download, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface TemplatesEmptyStateProps {
  emptyMessage: string;
  onSeed: () => void;
  onCreate: () => void;
  isSeedPending: boolean;
  seedLabel?: string;
  createLabel?: string;
  /** Optional: modules that ship a layout can show it before it is copied. */
  onPreview?: () => void;
  previewLabel?: string;
  /** True keeps the message and the preview, and drops the two calls to
   *  action. An account that may not write templates should not be invited
   *  to create one and refused after the editor is full. */
  readOnly?: boolean;
}

export function TemplatesEmptyState({
  emptyMessage,
  onSeed,
  onCreate,
  isSeedPending,
  seedLabel = "Load built-in templates",
  createLabel = "Create your first template",
  onPreview,
  previewLabel,
  readOnly = false,
}: TemplatesEmptyStateProps) {
  return (
    <Card className="p-8 text-center">
      <FileText size={40} className="mx-auto mb-3 text-on-muted" />
      <p className="text-sm text-on-muted mb-4">{emptyMessage}</p>
      <div className="flex flex-col sm:flex-row justify-center items-stretch sm:items-center gap-2">
        {onPreview && (
          <Button
            size="sm"
            variant="ghost"
            leftIcon={<Eye size={16} />}
            onClick={onPreview}
            className="w-full sm:w-auto whitespace-nowrap"
          >
            {previewLabel}
          </Button>
        )}
        {!readOnly && (
          <>
            <Button
              size="sm"
              variant="outline"
              leftIcon={<Download size={16} />}
              onClick={onSeed}
              disabled={isSeedPending}
              className="w-full sm:w-auto whitespace-nowrap"
            >
              {seedLabel}
            </Button>
            <Button
              size="sm"
              // Outline, not the filled default: the page header carries the
              // view's one primary create, and an empty state repeating it
              // left two filled buttons on the same screen.
              variant="outline"
              leftIcon={<Plus size={16} />}
              onClick={onCreate}
              className="w-full sm:w-auto whitespace-nowrap"
            >
              {createLabel}
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}
