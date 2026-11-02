import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import i18n from "@/i18n/config";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { templatesApi } from "@/modules/shared/lib/templates";
import type {
  BuiltInTemplate,
  DocumentTemplate,
  DocumentTemplateCreate,
  DocumentTemplateUpdate,
  PlaceholderInfo,
  TemplateUrlSegment,
} from "@/modules/shared/lib/templates";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";

export function useDocumentTemplates(module: TemplateUrlSegment) {
  return useQuery<DocumentTemplate[], Error>({
    queryKey: queryKeys.templates.list(module),
    queryFn: () => templatesApi.list(module),
  });
}

export function useTemplatePlaceholders(module: TemplateUrlSegment) {
  return useQuery<PlaceholderInfo[], Error>({
    queryKey: queryKeys.templates.placeholders(module),
    queryFn: () => templatesApi.getPlaceholders(module),
  });
}

/**
 * The layouts a PDF falls back to, readable without copying them first.
 *
 * Only the warehouse module ships them today; the hook is enabled per module
 * so a screen that has none does not ask.
 */
export function useBuiltInTemplates(
  module: TemplateUrlSegment,
  enabled = true,
) {
  return useQuery<BuiltInTemplate[], Error>({
    queryKey: queryKeys.templates.builtIn(module),
    queryFn: () => templatesApi.getBuiltIns(module),
    enabled,
  });
}

export function useCreateTemplate(module: TemplateUrlSegment) {
  return useAppMutation<DocumentTemplate, DocumentTemplateCreate>(
    (data: DocumentTemplateCreate) => templatesApi.create(module, data),
    (qc) => {
      invalidation.templates(qc, module);
    },
  );
}

export function useUpdateTemplate(module: TemplateUrlSegment) {
  return useAppMutation<
    DocumentTemplate,
    { templateId: string; data: DocumentTemplateUpdate }
  >(
    ({ templateId, data }) => templatesApi.update(module, templateId, data),
    (qc) => {
      invalidation.templates(qc, module);
    },
  );
}

export function useDeleteTemplate(module: TemplateUrlSegment) {
  return useAppMutation<void, string>(
    (templateId: string) => templatesApi.delete(module, templateId),
    (qc) => {
      invalidation.templates(qc, module);
    },
  );
}

/**
 * Copy the current built-in next to an organization's older copy.
 *
 * Nothing happens on its own and nothing is overwritten — the refreshed
 * layout arrives as a second template, and which one prints stays a decision
 * somebody makes.
 */
export function useRefreshTemplateCopy(module: TemplateUrlSegment) {
  return useAppMutation<DocumentTemplate, string>(
    (templateId: string) => templatesApi.refreshCopy(module, templateId),
    (qc) => {
      invalidation.templates(qc, module);
    },
  );
}

/**
 * Copies the built-in layouts into the organization as editable templates.
 *
 * The operation is idempotent: pressed a second time the server copies
 * nothing and answers `201` with an empty list. The message therefore comes
 * from the answer rather than from the request having gone through --
 * somebody who deleted their own copy and wants it back used to be told the
 * layouts had been copied, and then went looking for a row that was never
 * created. It lives here so all three template screens say the same thing;
 * two of them said nothing at all.
 */
export function useSeedDefaultTemplates(module: TemplateUrlSegment) {
  return useAppMutation<DocumentTemplate[], void>(
    () => templatesApi.seedDefaults(module),
    (qc, created) => {
      invalidation.templates(qc, module);
      if (created.length === 0) {
        toast.info(i18n.t("common:templates.seeded_none"));
      } else {
        toast.success(
          i18n.t("common:templates.seeded_count", { count: created.length }),
        );
      }
    },
  );
}

/**
 * One template as a file, for the user to save under its own name.
 *
 * A download changes nothing on the server, so there is nothing to
 * invalidate — the mutation wrapper exists for the failure it can report.
 */
export function useExportTemplate(module: TemplateUrlSegment) {
  return useAppMutation<Blob, string>(
    (templateId: string) => templatesApi.exportTemplate(module, templateId),
    () => {},
  );
}

/**
 * A template from an exported file, saved as the organization's own.
 *
 * The server validates before saving — unknown placeholders come back
 * named in the refusal — so the success message can speak of a template
 * that renders.
 */
export function useImportTemplate(module: TemplateUrlSegment) {
  return useAppMutation<DocumentTemplate, File>(
    (file: File) => templatesApi.importTemplate(module, file),
    (qc) => {
      invalidation.templates(qc, module);
    },
  );
}
