/**
 * Runs module-contributed validation rules against a core form.
 *
 * `ModuleRegistry.getValidationRules` has always collected these rules; what
 * was missing was anyone calling it, so a module could declare a rule and
 * watch it never run. This hook is the other half.
 *
 * The contract that makes it safe to let module code into a core form:
 *
 * - **Core errors win.** A rule only fills a field the form found no fault
 *   with. A module cannot mask a required-field message with its own.
 * - **A throwing rule is skipped, not fatal.** Rules come from modules and run
 *   inside core forms, so an exception must not wedge the form shut and leave
 *   the user unable to save. It is logged and the remaining rules still run.
 * - **Rules run on submit**, matching when core validation runs, so a module
 *   rule and a core rule surface together rather than in two waves.
 */
import { useCallback } from "react";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { CoreFormName } from "@/lib/moduleRegistry/moduleInterfaces";

/** Error key used for cross-field ('*') rule messages. */
export const FORM_LEVEL_ERROR_KEY = "__form__";

export function useModuleValidation(form: CoreFormName) {
  // Optional on purpose: a core form must still render and save where no
  // ModulesProvider is mounted. Module validation is an enrichment.
  const enabledModules = useEnabledModulesOptional();

  return useCallback(
    (formData: Record<string, unknown>): Record<string, string> => {
      const rules = moduleRegistry.getValidationRules(form, enabledModules);
      const errors: Record<string, string> = {};

      for (const rule of rules) {
        const key = rule.field === "*" ? FORM_LEVEL_ERROR_KEY : rule.field;
        if (errors[key]) continue; // first rule by priority wins

        let message: string | null;
        try {
          const value = rule.field === "*" ? undefined : formData[rule.field];
          message = rule.validator(value, formData);
        } catch (error) {
          console.error(
            `[moduleValidation] rule for ${form}.${rule.field} threw; skipping`,
            error,
          );
          continue;
        }

        if (message) errors[key] = message;
      }

      return errors;
    },
    [form, enabledModules],
  );
}
