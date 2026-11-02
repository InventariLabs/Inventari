import { describe, expect, it } from "vitest";
import { suggestPartnerMapping } from "./partnerImportMapping";

describe("suggestPartnerMapping", () => {
  it("reads a Polish company sheet without a click per column", () => {
    const mapping = suggestPartnerMapping([
      "Nazwa",
      "NIP",
      "Kod pocztowy",
      "Miasto",
      "Ulica",
      "Kraj",
      "E-mail",
      "Telefon",
      "Osoba kontaktowa",
      "Uwagi",
    ]);
    expect(mapping).toMatchObject({
      name: "Nazwa",
      tax_id: "NIP",
      postal_code: "Kod pocztowy",
      city: "Miasto",
      street: "Ulica",
      country: "Kraj",
      email: "E-mail",
      phone: "Telefon",
      contact_person: "Osoba kontaktowa",
      notes: "Uwagi",
    });
    expect(mapping.code).toBe("");
  });

  it("tells the postal code from the partner code and the tax id", () => {
    const mapping = suggestPartnerMapping([
      "Company",
      "Partner code",
      "Postal code",
      "Tax ID",
      "Type",
      "Website",
    ]);
    expect(mapping).toMatchObject({
      name: "Company",
      code: "Partner code",
      postal_code: "Postal code",
      tax_id: "Tax ID",
      type: "Type",
      website: "Website",
    });
  });
});
