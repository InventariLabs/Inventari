/**
 * What the journal's Detail column says about the document behind an entry.
 *
 * The number has been written into `meta_data` all along — a quantity change
 * a document executed names it, and a correction names both its own and the
 * one it corrects — and the screen read only the change list and the reason.
 * The row an auditor came for said "Document execution" and stopped, while
 * the reference that answers "which one" sat in the payload unread.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAuthStore } from "@/store/authStore";
import { AuditDetail, AuditTarget } from "./AuditLogEntry";
import { tFor } from "@/test/mocks/i18n";
import type { AuditLogEntry } from "@/types/core";

// Which modules the organization runs. A link to a document is worth
// offering only where the module answering it is switched on.
const enabledModules = { value: ["warehouse"] };
vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabledModules.value,
}));

const DOCUMENT_ID = "8f2a1111-2222-3333-4444-555555555555";

function signIn(permissions: string[]) {
  useAuthStore.setState({
    user: {
      id: "u-1",
      email: "reader@example.com",
      full_name: "Reader",
      preferred_language: "en",
      role: "user",
      is_active: true,
      is_superuser: false,
      is_blocked: false,
      permissions,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    isAuthenticated: true,
  });
}

function quantityRow(meta: Record<string, unknown> | null): AuditLogEntry {
  return {
    id: "row-1",
    organization_id: "org-1",
    user_id: "u-1",
    user_email: "reader@example.com",
    action: "QUANTITY_CHANGE",
    target_type: "item",
    target_id: "item-1",
    snapshot: {
      name: "Coffee Beans",
      before: { quantity: "18.000" },
      after: { quantity: "0.000" },
    },
    reason: "document_execution",
    meta_data: meta,
    created_at: "2026-09-26T10:00:00Z",
  };
}

function renderDetail(row: AuditLogEntry) {
  return render(
    <MemoryRouter>
      <AuditDetail
        row={row}
        changes={[]}
        expanded={false}
        onToggle={() => {}}
        t={tFor("common")}
      />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  enabledModules.value = ["warehouse"];
  signIn(["warehouse:read"]);
});

describe("AuditTarget — the record the row is about", () => {
  function renderTarget(row: AuditLogEntry) {
    return render(
      <MemoryRouter>
        <AuditTarget row={row} t={tFor("common")} onCopy={() => {}} />
      </MemoryRouter>,
    );
  }

  it("names the document an approval entry is about", () => {
    // The entry is about the approval request, but the reader is after the
    // document: eight characters of the request's uuid answered nothing.
    renderTarget({
      ...quantityRow(null),
      target_type: "approval_request",
      target_id: "8d6f4bf7-1111-2222-3333-444455556666",
      snapshot: {
        approves: {
          type: "document",
          id: DOCUMENT_ID,
          number: "IN/2026/003",
        },
      },
    });

    expect(screen.getByText("IN/2026/003")).toBeInTheDocument();
  });

  it("names an invitation by its address and the role's own name", () => {
    // Filed under the invitation, not the organization: "Night Shift" is the
    // name the organization gave a custom role, which no catalogue carries.
    renderTarget({
      ...quantityRow(null),
      target_type: "invitation",
      snapshot: { invited_email: "anna@example.com", role: "Night Shift" },
    });

    expect(
      screen.getByText("anna@example.com · Night Shift"),
    ).toBeInTheDocument();
  });

  it("falls back to the identifier for an approval entry with no number", () => {
    renderTarget({
      ...quantityRow(null),
      target_type: "approval_request",
      target_id: "8d6f4bf7-1111-2222-3333-444455556666",
      snapshot: { approves: { type: "document", id: DOCUMENT_ID } },
    });

    expect(screen.getAllByText("8d6f4bf7").length).toBeGreaterThan(0);
  });
});

describe("AuditDetail — the document behind the row", () => {
  it("names the document a quantity change came from", () => {
    renderDetail(
      quantityRow({
        document_type: "OUT",
        document_number: "OUT/2026/003",
        source_document_id: DOCUMENT_ID,
      }),
    );

    expect(screen.getByText("OUT/2026/003")).toBeInTheDocument();
  });

  it("names the production run beside its reason code", () => {
    renderDetail({
      ...quantityRow({ production_order_number: "PR/2026/0001" }),
      reason: "production_run",
    });

    expect(screen.getByText(/PR\/2026\/0001/)).toBeInTheDocument();
  });

  it("links the number to the document when the reader may open it", () => {
    renderDetail(
      quantityRow({
        document_number: "OUT/2026/003",
        source_document_id: DOCUMENT_ID,
      }),
    );

    expect(screen.getByText("OUT/2026/003").closest("a")).toHaveAttribute(
      "href",
      `/warehouse/documents/${DOCUMENT_ID}`,
    );
  });

  it("keeps the number readable where the link would be refused", () => {
    // No right to read documents: the number is the useful half and stays;
    // the link would end in a denial after the click.
    signIn([]);
    renderDetail(
      quantityRow({
        document_number: "OUT/2026/003",
        source_document_id: DOCUMENT_ID,
      }),
    );

    expect(screen.getByText(/OUT\/2026\/003/)).toBeInTheDocument();
    expect(screen.getByText(/OUT\/2026\/003/).closest("a")).toBeNull();
  });

  it("does not link into a module the organization does not run", () => {
    enabledModules.value = ["inventory"];
    renderDetail(
      quantityRow({
        document_number: "OUT/2026/003",
        source_document_id: DOCUMENT_ID,
      }),
    );

    expect(screen.getByText(/OUT\/2026\/003/).closest("a")).toBeNull();
  });

  it("says which document a correction corrects", () => {
    renderDetail(
      quantityRow({
        document_number: "CORRECTION/2026/001",
        corrects_document_number: "IN/2026/024",
        source_document_id: DOCUMENT_ID,
      }),
    );

    expect(screen.getByText("CORRECTION/2026/001")).toBeInTheDocument();
    expect(screen.getByText(/corrects IN\/2026\/024/)).toBeInTheDocument();
  });

  it("shows nothing about documents where the row carries none", () => {
    renderDetail(quantityRow(null));

    expect(screen.queryByText("Document:")).toBeNull();
  });
});

describe("AuditDetail — the sub-collections a deleted collection took", () => {
  const deletion = (meta: Record<string, unknown> | null): AuditLogEntry => ({
    ...quantityRow(meta),
    action: "HARD_DELETE",
    target_type: "recipe_collection",
    snapshot: { name: "Obiady" },
    reason: null,
  });

  it("names every sub-collection that went with it", () => {
    renderDetail(
      deletion({
        removed_collections: [
          { id: "c-2", name: "Makarony" },
          { id: "c-3", name: "Carbonara" },
        ],
      }),
    );

    expect(
      screen.getByText("Sub-collections removed: Makarony, Carbonara"),
    ).toBeInTheDocument();
  });

  it("shows nothing extra when none went", () => {
    renderDetail(deletion(null));

    expect(screen.queryByText(/Sub-collections removed/)).toBeNull();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
