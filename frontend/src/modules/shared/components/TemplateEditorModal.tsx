import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Eye } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Checkbox } from "@/components/ui/Checkbox";
import { Sheet } from "@/components/ui/Sheet";
import {
  useCreateTemplate,
  useUpdateTemplate,
  useTemplatePlaceholders,
} from "@/modules/shared/hooks/useDocumentTemplates";
import type {
  DocumentTemplate,
  DocumentTemplateCreate,
  DocumentTemplateUpdate,
  PlaceholderInfo,
  TemplateUrlSegment,
} from "@/modules/shared/lib/templates";
import { TEMPLATE_MODULE_NAME_BY_SEGMENT } from "@/modules/shared/lib/templates";
import { TemplatePreviewFrame } from "@/modules/shared/components/TemplatePreviewFrame";

interface TemplateEditorModalProps {
  /** URL path segment of the templates API (NOT the module directory name). */
  module: TemplateUrlSegment;
  template?: DocumentTemplate;
  documentTypes: { value: string; label: string }[];
  onClose: () => void;
  i18nNamespace?: string;
  /**
   * Each placeholder token's description key in `i18nNamespace`. Required:
   * the API describes symbols in English only, so an editor that left this
   * out answered a Polish reader in English — two of the three did.
   */
  placeholderDescriptions: readonly { key: string; descriptionKey: string }[];
  /** Localized, module-relevant example for the Name field. */
  namePlaceholder?: string;
  /** Localized HTML-validation message shown under the body field. */
  htmlInvalidMessage?: string;
  /**
   * Whether the module can actually serve a server-side render of the draft.
   * Only documents has a preview endpoint; where it is absent the editor
   * must not offer the toggle — a control whose only possible outcome is the
   * same message a failed render gives, for a different reason, is worse
   * than none. Defaults to false.
   */
  previewSupported?: boolean;
}

/**
 * Basic HTML sanity check for the body field. The backend only sanitises, it
 * does not reject malformed markup, so a tag-balance check is the cheap guard
 * that keeps a half-written `<table>` from being saved as-is.
 */
export function hasBalancedHtml(html: string): boolean {
  const VOID_TAGS = new Set([
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
  ]);
  const tagRe = /<\/?([a-zA-Z][a-zA-Z0-9]*)([^>]*)>/g;
  const stack: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = tagRe.exec(html)) !== null) {
    const isClosing = match[0].startsWith("</");
    const tag = match[1].toLowerCase();
    if (isClosing) {
      if (stack.pop() !== tag) return false;
    } else if (!VOID_TAGS.has(tag) && !match[2].trimEnd().endsWith("/")) {
      stack.push(tag);
    }
  }
  return stack.length === 0;
}

interface HtmlBodyFieldProps {
  module: TemplateUrlSegment;
  bodyHtml: string;
  onBodyChange: (html: string) => void;
  bodyError?: string;
  /** Whether the module can serve a preview at all. */
  previewSupported: boolean;
  showPreview: boolean;
  onTogglePreview: () => void;
}

/**
 * The HTML body with its optional preview. Lives outside the modal so the
 * modal stays under the complexity budget — and so the answer to "can this
 * editor show a preview" is one prop read, not a condition threaded through
 * the form.
 */
function HtmlBodyField({
  module,
  bodyHtml,
  onBodyChange,
  bodyError,
  previewSupported,
  showPreview,
  onTogglePreview,
}: HtmlBodyFieldProps) {
  const { t } = useTranslation("common");

  return (
    <>
      <div className="flex items-center justify-between mb-1">
        <p className="block text-xs font-medium text-on-muted">
          {t("templates.html_body", "HTML Body")}
        </p>
        {previewSupported && (
          <Button
            size="content"
            type="button"
            variant="link"
            onClick={onTogglePreview}
            className="px-0 text-xs text-on-primary gap-1 active:scale-100 min-h-11 md:min-h-0 min-w-11 md:min-w-0"
          >
            <Eye size={12} />
            {showPreview
              ? t("templates.hide_preview", "Hide preview")
              : t("templates.show_preview", "Show preview")}
          </Button>
        )}
      </div>
      {previewSupported && showPreview ? (
        <div className="border border-border rounded-lg bg-white p-4 min-h-[300px] max-h-[500px] overflow-auto">
          <TemplatePreviewFrame module={module} bodyHtml={bodyHtml} />
        </div>
      ) : (
        <Textarea
          aria-label={t("templates.html_body", "HTML Body")}
          value={bodyHtml}
          onChange={(e) => onBodyChange(e.target.value)}
          error={bodyError}
          rows={16}
          className="w-full rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-on font-mono resize-y dark:[color-scheme:dark]"
          placeholder="<html>..."
        />
      )}
    </>
  );
}

export function TemplateEditorModal({
  module,
  template,
  documentTypes,
  onClose,
  i18nNamespace = "common",
  placeholderDescriptions,
  namePlaceholder,
  htmlInvalidMessage,
  previewSupported = false,
}: TemplateEditorModalProps) {
  const { t } = useTranslation(i18nNamespace);
  const {
    data: placeholders = [],
    isError: placeholdersFailed,
    error: placeholdersError,
    refetch: refetchPlaceholders,
  } = useTemplatePlaceholders(module);
  const createMutation = useCreateTemplate(module);
  const updateMutation = useUpdateTemplate(module);

  const [name, setName] = useState(template?.name ?? "");
  const [docType, setDocType] = useState<string>(
    template?.document_type ?? documentTypes[0]?.value ?? "DEFAULT",
  );
  const [bodyHtml, setBodyHtml] = useState(template?.body_html ?? "");
  const [isDefault, setIsDefault] = useState(template?.is_default ?? false);
  const [showPreview, setShowPreview] = useState(false);
  const [bodyError, setBodyError] = useState<string | undefined>(undefined);

  const isEdit = Boolean(template);
  const isPending = createMutation.isPending || updateMutation.isPending;

  const handleSubmit = () => {
    if (!name.trim() || !bodyHtml.trim()) return;
    // the body was saved without any check. Surface a basic tag-balance
    // problem at the field instead of silently persisting half-written HTML.
    if (!hasBalancedHtml(bodyHtml)) {
      setBodyError(
        htmlInvalidMessage ??
          "The HTML looks unbalanced — check for unclosed tags.",
      );
      return;
    }
    setBodyError(undefined);

    if (isEdit && template) {
      const data: DocumentTemplateUpdate = {
        name,
        document_type: docType,
        body_html: bodyHtml,
        is_default: isDefault,
      };
      updateMutation.mutate(
        { templateId: template.id, data },
        { onSuccess: onClose },
      );
    } else {
      const data: DocumentTemplateCreate = {
        name,
        module: TEMPLATE_MODULE_NAME_BY_SEGMENT[module],
        document_type: docType,
        body_html: bodyHtml,
        is_default: isDefault,
      };
      createMutation.mutate(data, { onSuccess: onClose });
    }
  };

  const insertPlaceholder = (key: string) => {
    setBodyHtml((prev) => prev + key);
  };

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="3xl"
      aria-labelledby="template-editor-title"
    >
      <>
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2
            id="template-editor-title"
            className="text-lg font-semibold text-on"
          >
            {isEdit
              ? t("common:templates.edit", "Edit Template")
              : t("common:templates.create", "Create Template")}
          </h2>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
            className="text-on-muted hover:text-on text-xl"
          >
            ×
          </Button>
        </div>

        <div className="flex-1 overflow-auto p-4 space-y-4">
          <div className="grid grid-cols-1 items-end md:grid-cols-3 gap-3">
            <div
              className={
                documentTypes.length > 1 ? "md:col-span-2" : "md:col-span-3"
              }
            >
              <Input
                label={t("common:templates.name", "Name")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={
                  namePlaceholder ?? "e.g. Company Handover Protocol"
                }
              />
            </div>
            {/* A required field with a single possible value is not a choice
 — hide it until a module actually has more than one
                document type. */}
            {documentTypes.length > 1 && (
              <div>
                <NativeSelect
                  label={t("common:templates.type", "Type")}
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                >
                  {documentTypes.map((dt) => (
                    <option key={dt.value} value={dt.value}>
                      {dt.label}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="is_default"
              checked={isDefault}
              onChange={(e) => setIsDefault(e.target.checked)}
              label={t(
                "common:templates.set_default",
                "Set as default template",
              )}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
            <div className="lg:col-span-3">
              <HtmlBodyField
                module={module}
                bodyHtml={bodyHtml}
                onBodyChange={(value) => {
                  setBodyHtml(value);
                  if (bodyError) setBodyError(undefined);
                }}
                bodyError={bodyError}
                previewSupported={previewSupported}
                showPreview={showPreview}
                onTogglePreview={() => setShowPreview(!showPreview)}
              />
            </div>

            <div className="lg:col-span-1">
              <p className="block text-xs font-medium text-on-muted mb-1">
                {t("common:templates.placeholders", "Placeholders")}
              </p>
              <div className="border border-border rounded-lg bg-surface-raised p-2 max-h-[400px] overflow-auto space-y-1">
                {placeholdersFailed && (
                  <InlineQueryError
                    error={placeholdersError}
                    onRetry={() => void refetchPlaceholders()}
                  />
                )}
                {placeholders.map((p: PlaceholderInfo) => {
                  // One resolver, one reading: the tooltip and the line under
                  // the key are the same sentence. They used to be resolved
                  // separately, so hovering a symbol answered in the API's
                  // English while the text six lines below it answered in the
                  // reader's language.
                  const descriptionKey = placeholderDescriptions.find(
                    (d) => d.key === p.key,
                  )?.descriptionKey;
                  const description = descriptionKey
                    ? t(descriptionKey)
                    : p.description;
                  return (
                    <Button
                      size="content"
                      key={p.key}
                      type="button"
                      variant="ghost"
                      className="w-full flex-col items-stretch px-2 py-1.5 rounded text-xs justify-start hover:bg-primary-50 dark:hover:bg-primary-900/30 active:bg-primary-50 dark:active:bg-primary-900/30 group active:scale-100"
                      onClick={() => insertPlaceholder(p.key)}
                      title={description}
                    >
                      <code className="text-on-primary font-mono text-xs">
                        {p.key}
                      </code>
                      <div className="text-on-secondary text-[10px] mt-0.5">
                        {description}
                      </div>
                      {/* an example value and the empty-field marker
                        turn the list into usable truth for a template
                        author, not just a name dump. */}
                      {p.example ? (
                        <code className="text-[10px] text-on-secondary mt-0.5 truncate">
                          {t("common:templates.example", "Example")}:{" "}
                          {p.example}
                        </code>
                      ) : null}
                      {p.possibly_empty ? (
                        <span className="text-[10px] text-amber-700 dark:text-amber-400 mt-0.5">
                          {t("common:templates.possiblyEmpty", "May be empty")}
                        </span>
                      ) : null}
                    </Button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-border">
          <Button variant="outline" onClick={onClose} disabled={isPending}>
            {t("common:actions.cancel", "Cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!name.trim() || !bodyHtml.trim() || isPending}
          >
            {isPending
              ? t("common:form.saving", "Saving…")
              : isEdit
                ? t("common:actions.save", "Save")
                : t("common:templates.create", "Create Template")}
          </Button>
        </div>
      </>
    </Sheet>
  );
}
