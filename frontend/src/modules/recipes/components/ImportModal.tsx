import { Link, FileJson } from "lucide-react";
import { Link as RouterLink } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { Input } from "@/components/ui/Input";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsPanels,
  TabsTrigger,
} from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";

type ImportMode = "url" | "json";

interface ImportModalProps {
  isOpen: boolean;
  importMode: ImportMode;
  importUrl: string;
  importJson: string;
  isPreviewPending: boolean;
  onModeChange: (mode: ImportMode) => void;
  onUrlChange: (url: string) => void;
  onJsonChange: (json: string) => void;
  onShowExample: () => void;
  onImport: () => void;
  onClose: () => void;
  titleText: string;
  urlTabText: string;
  jsonTabText: string;
  /** Real field labels — a placeholder is an example, never a name. */
  urlLabel: string;
  jsonLabel: string;
  urlPlaceholder: string;
  jsonPlaceholder: string;
  showExampleText: string;
  cancelText: string;
  submitText: string;
  parsingText: string;
  /** Why the last attempt failed — stays on screen, unlike a toast. */
  errorText?: string | null;
  /** True when the AI purpose behind URL import has no bound connection.
   * The URL tab then explains itself instead of letting the click travel
   * to a refusal the backend already knows is coming. */
  urlNeedsAi?: boolean;
  /** What the URL tab says when {@link urlNeedsAi} — who is missing and why. */
  urlNeedsAiNotice?: string | null;
  /** Label of the link to the screen that binds a connection. */
  urlNeedsAiCtaText?: string;
}

export function ImportModal({
  isOpen,
  importMode,
  importUrl,
  importJson,
  isPreviewPending,
  onModeChange,
  onUrlChange,
  onJsonChange,
  onShowExample,
  onImport,
  onClose,
  titleText,
  urlTabText,
  jsonTabText,
  urlLabel,
  jsonLabel,
  urlPlaceholder,
  jsonPlaceholder,
  showExampleText,
  cancelText,
  submitText,
  parsingText,
  errorText,
  urlNeedsAi = false,
  urlNeedsAiNotice,
  urlNeedsAiCtaText,
}: ImportModalProps) {
  if (!isOpen) return null;

  const urlTabBlocked = urlNeedsAi && Boolean(urlNeedsAiNotice);
  const canSubmit = isPreviewPending
    ? false
    : importMode === "url"
      ? urlTabBlocked || !importUrl.trim()
      : !importJson.trim();

  return (
    <Sheet open={isOpen} onClose={onClose} maxWidth="xl" aria-label={titleText}>
      <SheetHeader title={titleText} onClose={onClose} />

      <SheetBody className="p-5 space-y-4">
        <Tabs
          defaultValue="url"
          value={importMode}
          onValueChange={(mode) => onModeChange(mode as ImportMode)}
        >
          <TabsList>
            <TabsTrigger value="url" size="sm" icon={<Link size={16} />}>
              {urlTabText}
            </TabsTrigger>
            <TabsTrigger value="json" size="sm" icon={<FileJson size={16} />}>
              {jsonTabText}
            </TabsTrigger>
          </TabsList>

          {/* Both panels share one cell, so the sheet keeps the height of the
              taller one: the JSON tab used to be 48px taller than the URL
              tab and the sheet jumped, centred, on every switch. */}
          <TabsPanels className="mt-4">
            <TabsContent value="url" stacked className="mt-0">
              <Input
                type="url"
                value={importUrl}
                onChange={(e) => onUrlChange(e.target.value)}
                label={urlLabel}
                placeholder={urlPlaceholder}
                autoFocus
              />
              {urlTabBlocked && (
                <p className="mt-3 text-sm text-amber-600 flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>{urlNeedsAiNotice}</span>
                  {urlNeedsAiCtaText && (
                    <RouterLink
                      to="/settings/ai"
                      className="font-semibold underline underline-offset-2 hover:no-underline"
                    >
                      {urlNeedsAiCtaText}
                    </RouterLink>
                  )}
                </p>
              )}
            </TabsContent>

            <TabsContent value="json" stacked className="mt-0 space-y-1.5">
              <Textarea
                value={importJson}
                onChange={(e) => onJsonChange(e.target.value)}
                label={jsonLabel}
                placeholder={jsonPlaceholder}
                rows={6}
                className="font-mono resize-none"
              />
              <Button
                size="content"
                type="button"
                variant="link"
                onClick={onShowExample}
                className="px-0 text-xs text-on-primary min-h-11 md:min-h-0 min-w-11 md:min-w-0"
              >
                {showExampleText}
              </Button>
            </TabsContent>
          </TabsPanels>
        </Tabs>

        {errorText && (
          <p
            role="alert"
            className="rounded-xl bg-red-50 px-3 py-2 text-sm text-on-danger"
          >
            {errorText}
          </p>
        )}
      </SheetBody>

      <FormSheetFooter
        isPending={isPreviewPending}
        lineCount={0}
        cancelText={cancelText}
        submitText={isPreviewPending ? parsingText : submitText}
        submitDisabled={canSubmit}
        onCancel={onClose}
        onSubmit={onImport}
      />
    </Sheet>
  );
}
