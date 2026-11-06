/**
 * Wording the catalogues settled on, kept so a later edit does not bring the
 * old sentence back: the product-form tab that reads a photo, the German word
 * for who holds a piece of equipment and for approval in the equipment module,
 * and the Spanish launcher greeting's register.
 */
import { describe, expect, it } from "vitest";

import plLabels from "../locales/pl/labels.json";
import deEquipment from "../../modules/equipment/i18n/de.json";
import esLauncher from "../../modules/launcher/i18n/es.json";

describe("catalogue wording", () => {
  it("names the Polish vision tab after what it does, not after label scanning", () => {
    expect(plLabels.quickAdd.tabVision).not.toMatch(/etykiet/i);
    expect(plLabels.quickAdd.tabVision).toMatch(/zdj/i);
  });

  it("calls a piece of equipment's holder Inhaber in German, never Halterung", () => {
    expect(JSON.stringify(deEquipment.attestation)).not.toMatch(/Halterung/);
  });

  it("keeps German equipment approvals in the Genehmigung family", () => {
    expect(JSON.stringify(deEquipment.approvals)).not.toMatch(
      /freigab|freigeb/i,
    );
  });

  it("greets in Spanish with the formal register the launcher already uses", () => {
    const launcher = JSON.stringify(esLauncher);
    expect(launcher).not.toMatch(/\bTe\b|\bHas\b|\btu\b|\bPuedes\b/);
    expect(esLauncher.launcher.joinedOrganization).toBe(
      "Se ha unido a {{organization}}",
    );
  });
});
