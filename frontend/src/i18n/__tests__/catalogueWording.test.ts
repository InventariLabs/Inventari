/**
 * Wording the catalogues settled on, kept so a later edit does not bring the
 * old sentence back: the product-form tab that reads a photo, the German word
 * for who holds a piece of equipment and for approval in the equipment module,
 * the Spanish launcher greeting's register, and the word a workflow release
 * repeats from the approvals screens.
 */
import { describe, expect, it } from "vitest";

import enLabels from "../locales/en/labels.json";
import deLabels from "../locales/de/labels.json";
import esLabels from "../locales/es/labels.json";
import frLabels from "../locales/fr/labels.json";
import ptLabels from "../locales/pt/labels.json";
import plLabels from "../locales/pl/labels.json";
import enItems from "../locales/en/items.json";
import frItems from "../locales/fr/items.json";
import plCommon from "../locales/pl/common.json";
import esCommon from "../locales/es/common.json";
import enCommon from "../locales/en/common.json";
import deCommon from "../locales/de/common.json";
import frCommon from "../locales/fr/common.json";
import ptCommon from "../locales/pt/common.json";
import deApprovals from "../../modules/approvals/i18n/de.json";
import frApprovals from "../../modules/approvals/i18n/fr.json";
import ptApprovals from "../../modules/approvals/i18n/pt.json";
import plApprovals from "../../modules/approvals/i18n/pl.json";
import frPurchaseOrders from "../../modules/purchase_orders/i18n/fr.json";
import frEquipment from "../../modules/equipment/i18n/fr.json";
import frMaker from "../../modules/maker/i18n/fr.json";
import frWarehouse from "../../modules/warehouse/i18n/fr.json";
import deWarehouse from "../../modules/warehouse/i18n/de.json";
import plWarehouse from "../../modules/warehouse/i18n/pl.json";
import ptWarehouse from "../../modules/warehouse/i18n/pt.json";
import enWarehouse from "../../modules/warehouse/i18n/en.json";
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

  it("names a workflow release in the words the approvals screens use", () => {
    // The administrator switches the workflow off on the approvals screens, so
    // the audit log's reason repeats their word — Workflow, Flux, and excluído
    // — rather than inventing Ablauf, Circuit or eliminado beside it.
    const catalogues = [
      [deCommon, deApprovals],
      [frCommon, frApprovals],
      [ptCommon, ptApprovals],
    ] as const;

    for (const [core, approvals] of catalogues) {
      const reasons = core.settings.audit.reasons;
      expect(reasons["workflow deactivated"]).toBe(
        approvals.workflows.deactivated,
      );
      expect(reasons["workflow deleted"]).toBe(approvals.workflows.deleted);
    }
  });

  it("calls an approval workflow by one word per language", () => {
    const text = (o: unknown) => JSON.stringify(o);
    expect(text(deApprovals)).not.toMatch(/Ablauf|Abläufe/);
    expect(text(frApprovals)).not.toMatch(/circuit/i);
    expect(text(frPurchaseOrders)).not.toMatch(/circuit/i);
    // The verb for switching a workflow off is the one the dialog, the audit
    // reason and the toast share.
    expect(text(plApprovals.workflows)).not.toMatch(/ezaktyw|ktywuj|ktywowan/);
    expect(plApprovals.workflows.deactivated).toBe(
      plCommon.settings.audit.reasons["workflow deactivated"],
    );
  });

  it("keeps the French equipment direction and yield wording in one pair of words", () => {
    // The assets a person holds are the ones borrowed, never "borrowed from you".
    expect(frEquipment.my_assets.empty_hint).not.toMatch(/sont emprunt/);
    expect(frMaker.bom.yieldLabel).toBe(frMaker.detail.line.yieldLabel);
    expect(frWarehouse.navigation.scan).not.toMatch(/^Scan document$/);
  });

  it("names the Modules page by its title where the focus-mode copy points to it", () => {
    for (const catalogue of [plCommon, esCommon, frCommon, enCommon]) {
      const copy = JSON.stringify(catalogue.focusLock);
      expect(copy).not.toMatch(/sklep|tienda|boutique|store/i);
    }
    for (const catalogue of [
      plCommon,
      esCommon,
      frCommon,
      enCommon,
      deCommon,
      ptCommon,
    ]) {
      expect(catalogue.settings.moduleSettings.unknownModuleHint).not.toMatch(
        /sklep|tienda|magasin|\bstore\b|Store|loja/,
      );
    }
  });

  it("names the pick list and the packing slip as the document type labels do", () => {
    const sentences = JSON.stringify([
      deWarehouse,
      frWarehouse,
      plWarehouse,
      ptWarehouse,
    ]);
    expect(sentences).not.toMatch(
      /lista kompletacyjna|Packschein|liste de prélèvement|guia de embalagem/i,
    );
  });

  it("keeps the Custom workspace mode free of the word profile in Polish", () => {
    expect(plCommon.profiles.clean_core.description).not.toMatch(/profil/i);
  });

  it("names an asset's return and disposal in item history as its buttons do", () => {
    expect(enItems.history.actions.CHECKIN).toBe("Returned");
    expect(enItems.history.actions.DISPOSED).toBe(
      enItems.deletionReasons.DISPOSED,
    );
    expect(frItems.history.actions.DISPOSED).toBe(
      frItems.deletionReasons.DISPOSED,
    );
  });

  it("keeps the photo tab of the product form free of the Vision AI product name", () => {
    for (const labels of [enLabels, deLabels, esLabels, frLabels, ptLabels]) {
      expect(labels.quickAdd.tabVision).not.toMatch(/vision|visão/i);
      expect(labels.quickAdd.visionTitle).not.toMatch(/vision|visão/i);
    }
  });

  it("submits the typed execution panel under the verb of its heading", () => {
    // The panel's submit reuses the heading's label, so no catalogue keeps a
    // second name for the act ("Confirm & complete") beside the menu's Confirm.
    for (const warehouse of [
      enWarehouse,
      deWarehouse,
      plWarehouse,
      ptWarehouse,
      frWarehouse,
    ]) {
      expect(warehouse.detail).not.toHaveProperty("executionSubmit");
    }
  });

  it("describes a record-only document without naming a taking from stock", () => {
    for (const warehouse of [
      enWarehouse,
      frWarehouse,
      deWarehouse,
      plWarehouse,
      ptWarehouse,
    ]) {
      const copy = JSON.stringify([
        warehouse.actions.postNowRecordOnly,
        warehouse.confirmDialog.postNowRecordOnlyMessage,
        warehouse.toast.completedRecordOnly,
      ]);
      expect(copy).not.toMatch(/taken|prélev|entnommen|pobran|zdjęt|retirad/i);
    }
  });
});
