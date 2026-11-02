import { render, screen } from "@testing-library/react";
import { useEffect, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  PageHeaderContext,
  useModulePageHeader,
  type PageHeaderData,
} from "./useModulePageHeader";

function Page() {
  const { setHeader } = useModulePageHeader();
  useEffect(() => {
    setHeader({ title: "Webhooks", actions: <button>Add webhook</button> });
  }, [setHeader]);
  return <div>page body</div>;
}

function Shell({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.title && <h1>{data.title}</h1>}
      {data.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

describe("useModulePageHeader without a provider", () => {
  it("says so instead of dropping the header in silence", () => {
    // Only SettingsShell and ModuleShell provide the context. A page mounted
    // on a flat route under AppShell used to hand its title and its actions to
    // a no-op default — which is how `/webhooks` lost the only button that
    // could add a second webhook.
    const complain = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    render(<Page />);

    expect(complain).toHaveBeenCalledTimes(1);
    expect(complain.mock.calls[0][0]).toContain("PageHeaderContext");
    expect(complain.mock.calls[0][0]).toContain("Webhooks");
    complain.mockRestore();
  });

  it("stays quiet when the shell provides one", () => {
    const complain = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    render(
      <Shell>
        <Page />
      </Shell>,
    );

    expect(screen.getByRole("heading", { name: "Webhooks" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add webhook" })).toBeVisible();
    expect(complain).not.toHaveBeenCalled();
    complain.mockRestore();
  });
});
