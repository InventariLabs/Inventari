import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { ReadableError } from "@/lib/errors";
import type { DocumentView } from "@/lib/moduleRegistry";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { ModuleDocumentActions } from "./ModuleDocumentActions";

const toastError = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({
  toast: { error: toastError, success: toastSuccess },
}));

let canWrite = true;
vi.mock("@/hooks/useCanWrite", () => ({ useCanWrite: () => canWrite }));

const enabled = vi.hoisted(() => ({ modules: [] as string[] }));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useEnabledModulesOptional: () => enabled.modules,
}));

const run = vi.fn<(doc: DocumentView) => Promise<string | void>>();

moduleRegistry.register({
  name: "certs_actions_demo",
  routes: [],
  documentActionContributors: [
    {
      key: "file",
      label: "File the certificates",
      isAvailable: (doc) => doc.type === "IN" && doc.status === "CONFIRMED",
      run: (doc) => run(doc),
    },
  ],
});

const receipt = (status: string): WarehouseDocument =>
  ({
    id: "d1",
    number: "PZ/2026/014",
    type: "IN",
    status,
    meta_data: null,
    lines: [
      {
        id: "l1",
        batch_number: "LOT-7",
        meta_data: { certs_actions_demo: { number: "C-17" } },
      },
    ],
  }) as unknown as WarehouseDocument;

describe("ModuleDocumentActions", () => {
  beforeEach(() => {
    canWrite = true;
    enabled.modules = ["certs_actions_demo"];
    run.mockReset();
    toastError.mockReset();
    toastSuccess.mockReset();
  });

  it("offers a module's action where the module says it belongs", () => {
    const { unmount } = renderWithProviders(
      <ModuleDocumentActions doc={receipt("CONFIRMED")} />,
    );
    expect(
      screen.getByRole("button", { name: "File the certificates" }),
    ).toBeInTheDocument();
    unmount();

    renderWithProviders(<ModuleDocumentActions doc={receipt("COMPLETED")} />);
    expect(
      screen.queryByRole("button", { name: "File the certificates" }),
    ).not.toBeInTheDocument();
  });

  it("hands the action the document with its lines' module fields", async () => {
    run.mockResolvedValue();
    renderWithProviders(<ModuleDocumentActions doc={receipt("CONFIRMED")} />);

    await userEvent.click(
      screen.getByRole("button", { name: "File the certificates" }),
    );

    expect(run).toHaveBeenCalledWith({
      id: "d1",
      type: "IN",
      number: "PZ/2026/014",
      status: "CONFIRMED",
      metaData: {},
      lines: [
        {
          id: "l1",
          batchNumber: "LOT-7",
          metaData: { certs_actions_demo: { number: "C-17" } },
        },
      ],
    });
    expect(toastError).not.toHaveBeenCalled();
    // Nothing to say, nothing shown.
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("shows the sentence an action resolves with", async () => {
    // A key nobody translated reads as itself.
    run.mockResolvedValue("1 certificate filed");
    renderWithProviders(<ModuleDocumentActions doc={receipt("CONFIRMED")} />);

    await userEvent.click(
      screen.getByRole("button", { name: "File the certificates" }),
    );

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("1 certificate filed"),
    );
  });

  it("shows the module's own sentence when the action is refused", async () => {
    run.mockRejectedValue(new ReadableError("Certificate C-17 has lapsed"));
    renderWithProviders(<ModuleDocumentActions doc={receipt("CONFIRMED")} />);

    await userEvent.click(
      screen.getByRole("button", { name: "File the certificates" }),
    );

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Certificate C-17 has lapsed"),
    );
    // The button is pressable again once the refusal is shown.
    expect(
      screen.getByRole("button", { name: "File the certificates" }),
    ).toBeEnabled();
  });

  it("offers nothing to a reader who may not write documents", () => {
    canWrite = false;
    renderWithProviders(<ModuleDocumentActions doc={receipt("CONFIRMED")} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers nothing while the module is switched off", () => {
    enabled.modules = [];
    renderWithProviders(<ModuleDocumentActions doc={receipt("CONFIRMED")} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
