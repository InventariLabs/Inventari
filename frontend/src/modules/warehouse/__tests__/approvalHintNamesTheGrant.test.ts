/**
 * The approval hint describes the grant, because that is what the API checks.
 *
 * `documents_approval_router._require_approver` gates on `approvals:approve`;
 * it deliberately stopped gating on the role names `admin`/`manager`. The
 * settings hint kept repeating the abandoned rule, so an organization with a
 * custom approver role read that its role could not approve. This pins the
 * text to the rule that is actually enforced.
 */
import { describe, expect, it } from "vitest";

import de from "../i18n/de.json";
import en from "../i18n/en.json";
import es from "../i18n/es.json";
import fr from "../i18n/fr.json";
import pl from "../i18n/pl.json";

const LOCALES = { en, pl, de, fr, es } as const;

/** How the same permission is labelled on the roles screen, per language. */
const PERMISSION_LABEL: Record<keyof typeof LOCALES, string> = {
  en: "Approve requests",
  pl: "Akceptacja zgłoszeń",
  de: "Anträge genehmigen",
  fr: "Approuver les demandes",
  es: "Aprobar solicitudes",
};

describe("approval workflow hint", () => {
  for (const [lang, bundle] of Object.entries(LOCALES)) {
    const hint = bundle.profile.approvalWorkflowHint;

    it(`names the permission rather than a built-in role (${lang})`, () => {
      expect(hint).toContain(PERMISSION_LABEL[lang as keyof typeof LOCALES]);
    });

    it(`does not promise that only Admin or Manager can approve (${lang})`, () => {
      expect(hint).not.toMatch(/\bAdmin\b/i);
      expect(hint).not.toMatch(/\bManager\b/i);
      expect(hint).not.toMatch(/\bKierownik/i);
      expect(hint).not.toMatch(/\bgerente\b/i);
    });
  }
});

describe("approval workflow heading", () => {
  it("calls the section a flow, as the hint and consequence sentences below do (pl)", () => {
    expect(pl.profile.approvalWorkflow).toBe("Przepływ akceptacji");
    expect(pl.profile.approvalHowItWorks).toContain("przepływ");
  });
});
