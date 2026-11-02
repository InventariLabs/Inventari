import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Monitor } from "lucide-react";
import { server } from "@/test/mocks/server";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { LabelGenerateModal } from "./LabelGenerateModal";

// One module claims a purpose; the registry is the only place the generate
// form learns that anything other than products can own a label.
vi.spyOn(moduleRegistry, "getLabelPurposes").mockReturnValue([
  {
    contextTag: "equipment",
    icon: Monitor,
    labelKey: "equipment:labels.purpose",
    defaultPrefix: "EQP",
  },
]);

function Harness() {
  const [genData, setGenData] = useState({
    count: 1,
    prefix: "STM",
    label_type: "GENERIC",
    description: "",
    target_location_id: "",
    context_tag: "",
  });
  return (
    <LabelGenerateModal
      open
      onClose={() => {}}
      genData={genData}
      setGenData={setGenData}
      defaultPrefix="STM"
    />
  );
}

describe("LabelGenerateModal — label purpose", () => {
  let queryClient: QueryClient;
  let generatePayload: unknown;

  beforeEach(() => {
    generatePayload = undefined;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    server.use(
      http.post("/api/v1/labels/pool/generate", async ({ request }) => {
        generatePayload = await request.json();
        return HttpResponse.json([], { status: 201 });
      }),
    );
  });

  const renderModal = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <Harness />
      </QueryClientProvider>,
    );

  it("stamps the chosen purpose on the batch and follows it with the prefix", async () => {
    renderModal();

    fireEvent.click(screen.getByRole("radio", { name: "Equipment" }));

    // The prefix is what makes a printed sheet recognisable by eye, so it
    // moves with the purpose instead of staying on the product default.
    await waitFor(() => {
      expect(screen.getByDisplayValue("EQP")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("export-labels-btn"));

    await waitFor(() => {
      expect(generatePayload).toMatchObject({
        prefix: "EQP",
        context_tag: "equipment",
      });
    });
  });

  it("sends no tag at all for plain product labels", async () => {
    renderModal();

    fireEvent.click(screen.getByTestId("export-labels-btn"));

    await waitFor(() => {
      expect(generatePayload).toMatchObject({
        prefix: "STM",
        context_tag: null,
      });
    });
  });

  it("refuses an empty prefix here, not at the server", () => {
    // Every other shape this field can hold is already settled while the
    // reader types: the input strips anything outside [A-Z0-9] and caps
    // the length, so what it holds is always something the scanner reads.
    // An emptied field was the one exception — it left as a request and
    // came back a 422 with no field attached to it.
    renderModal();

    const prefix = screen.getByDisplayValue("STM");
    fireEvent.change(prefix, { target: { value: "" } });

    expect(screen.getByTestId("export-labels-btn")).toBeDisabled();
  });

  it("keeps the button live for a prefix carrying a digit", async () => {
    // B12 is the example in the API field's own description, and it used
    // to produce a sticker the scanner refused. Nothing here may treat it
    // as the malformed one.
    renderModal();

    const prefix = screen.getByDisplayValue("STM");
    fireEvent.change(prefix, { target: { value: "B12" } });

    const button = screen.getByTestId("export-labels-btn");
    expect(button).not.toBeDisabled();
    fireEvent.click(button);

    await waitFor(() => {
      expect(generatePayload).toMatchObject({ prefix: "B12" });
    });
  });

  it("sends the number of labels and the internal description as typed", async () => {
    renderModal();

    fireEvent.change(screen.getByLabelText("Number of labels (1–500)"), {
      target: { value: "25" },
    });
    fireEvent.change(screen.getByLabelText("Description (Internal use)"), {
      target: { value: "Cold shelf" },
    });
    fireEvent.click(screen.getByTestId("export-labels-btn"));

    await waitFor(() => {
      expect(generatePayload).toMatchObject({
        count: 25,
        description: "Cold shelf",
      });
    });
  });

  it("falls back to one label when the count is cleared, never to zero or NaN", async () => {
    renderModal();

    fireEvent.change(screen.getByLabelText("Number of labels (1–500)"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByTestId("export-labels-btn"));

    await waitFor(() => {
      expect(generatePayload).toMatchObject({ count: 1 });
    });
  });
});
