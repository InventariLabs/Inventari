import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

type Field = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

function isField(target: EventTarget | null): target is Field {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  );
}

/** The sentence for the first rule the field breaks, or null when no rule here is one the browser words. */
function messageFor(field: Field, t: TFunction<"common">): string | null {
  const { validity } = field;
  if (validity.valueMissing) return t("nativeValidation.valueMissing");
  if (validity.typeMismatch) {
    return field instanceof HTMLInputElement && field.type === "email"
      ? t("nativeValidation.typeMismatchEmail")
      : t("nativeValidation.typeMismatchUrl");
  }
  if (field instanceof HTMLSelectElement) return null;
  if (validity.tooShort) {
    return t("nativeValidation.tooShort", { min: field.minLength });
  }
  if (validity.tooLong) {
    return t("nativeValidation.tooLong", { max: field.maxLength });
  }
  if (field instanceof HTMLInputElement) {
    if (validity.rangeUnderflow) {
      return t("nativeValidation.rangeUnderflow", { min: field.min });
    }
    if (validity.rangeOverflow) {
      return t("nativeValidation.rangeOverflow", { max: field.max });
    }
    if (validity.stepMismatch || validity.badInput) {
      return t("nativeValidation.badInput");
    }
    if (validity.patternMismatch) {
      return field.title || t("nativeValidation.patternMismatch");
    }
  }
  return null;
}

/**
 * The checks the browser performs on a form (`required`, `minLength`, `type`,
 * `min`…) speak the browser's language, which is not necessarily the one the
 * app was set to: an English app on a Polish browser told a reader to
 * "Wypełnij to pole". The bubble's sentence is the field's `validationMessage`
 * at the moment it is shown, so it is replaced when the field reports itself
 * invalid and handed back to the browser as soon as the field is edited.
 *
 * One listener for the whole document rather than a prop on every form: the
 * rule is the same on every screen, and a form added tomorrow is covered.
 */
export function useNativeValidationMessages(): void {
  const { t } = useTranslation("common");
  // Fields whose current custom message is ours, so one a screen set itself is
  // never overwritten or cleared. Kept across a language change: the listeners
  // are rebuilt for the new `t`, the fields they marked are still ours to release.
  const ours = useRef(new WeakSet<Field>());

  useEffect(() => {
    const onInvalid = (event: Event) => {
      const { target } = event;
      if (!isField(target) || target.validity.customError) return;
      const message = messageFor(target, t);
      if (!message) return;
      target.setCustomValidity(message);
      ours.current.add(target);
    };
    const release = (event: Event) => {
      const { target } = event;
      if (!isField(target) || !ours.current.has(target)) return;
      target.setCustomValidity("");
      ours.current.delete(target);
    };

    document.addEventListener("invalid", onInvalid, true);
    document.addEventListener("input", release, true);
    document.addEventListener("change", release, true);
    return () => {
      document.removeEventListener("invalid", onInvalid, true);
      document.removeEventListener("input", release, true);
      document.removeEventListener("change", release, true);
    };
  }, [t]);
}
