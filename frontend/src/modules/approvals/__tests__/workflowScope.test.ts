import { describe, it, expect } from "vitest";
import i18n from "@/test/mocks/i18n";
import {
  describeWorkflowScope,
  type WorkflowScope,
} from "@/modules/approvals/workflowScope";

const t = i18n.getFixedT("en", "approvals");

const all: WorkflowScope = {
  holds: "all",
  conditions: [],
  required_by_settings: [],
};

describe("describeWorkflowScope", () => {
  it("names every confirmed document when the document settings are silent", () => {
    expect(describeWorkflowScope(t, "document", all)).toBe(
      "every confirmed document",
    );
  });

  it("names every checkout for an equipment workflow", () => {
    expect(describeWorkflowScope(t, "equipment_checkout", all)).toBe(
      "every checkout of every asset",
    );
  });

  it("says a purchase-order workflow holds nothing until the order settings ask", () => {
    expect(
      describeWorkflowScope(t, "purchase_order", {
        holds: "nothing",
        conditions: [],
        required_by_settings: [],
      }),
    ).toMatch(/^nothing/);
  });

  it("lists the document types and the threshold the settings name", () => {
    const scope: WorkflowScope = {
      holds: "some",
      conditions: [
        {
          kind: "document_types",
          document_types: ["OUT", "SCRAP"],
          amount: null,
          currency: null,
          unpriced_included: false,
        },
        {
          kind: "value_above",
          document_types: [],
          amount: "100.00",
          currency: "EUR",
          unpriced_included: true,
        },
      ],
      required_by_settings: [
        "approval_required_for_types",
        "approval_threshold",
      ],
    };
    const sentence = describeWorkflowScope(t, "document", scope);
    expect(sentence).toContain("Goods Issue, Scrap");
    expect(sentence).toContain("€100.00");
    expect(sentence).toContain("documents with no value");
  });

  it("names the foreign-currency rule of a purchase-order threshold", () => {
    const sentence = describeWorkflowScope(t, "purchase_order", {
      holds: "some",
      conditions: [
        {
          kind: "value_above",
          document_types: [],
          amount: "500.00",
          currency: "PLN",
          unpriced_included: true,
        },
        {
          kind: "foreign_currency",
          document_types: [],
          amount: null,
          currency: "PLN",
          unpriced_included: false,
        },
      ],
      required_by_settings: ["approval_threshold"],
    });
    expect(sentence).toContain("500");
    expect(sentence).toContain("in a currency other than PLN");
  });
});
