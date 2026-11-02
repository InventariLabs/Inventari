import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Routes,
  Route,
  Link,
  useLocation,
} from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { useNavLeaveGuard } from "./useNavLeaveGuard";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useFormGuardStore } from "@/store/formGuardStore";

/**
 * The gate between a dirty form and the navigation that would throw it away.
 * The browser's back button stays outside this gate — react-router's blocker
 * needs a data router this app does not mount.
 */
function NavProbe() {
  const { guardClick, confirmDialogProps } = useNavLeaveGuard();
  const location = useLocation();
  return (
    <div onClickCapture={guardClick}>
      <Link to="/other">Other page</Link>
      <Link to="/here">Current page</Link>
      <span data-testid="path">{location.pathname}</span>
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}

function renderProbe() {
  return render(
    <MemoryRouter initialEntries={["/here"]}>
      <Routes>
        <Route path="*" element={<NavProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("useNavLeaveGuard", () => {
  beforeEach(() => {
    useFormGuardStore.getState().setDirtyForm(null);
  });

  it("lets a link through when no form is dirty", async () => {
    const user = userEvent.setup();
    renderProbe();

    await user.click(screen.getByText("Other page"));

    expect(screen.getByTestId("path")).toHaveTextContent("/other");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks before a link leaves a dirty form behind", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderProbe();

    await user.click(screen.getByText("Other page"));

    // The click is stopped before the router sees it; the reader is asked.
    expect(screen.getByTestId("path")).toHaveTextContent("/here");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(
      screen.getByText("The asset form holds unsaved changes. Leave anyway?"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Leave anyway" }));

    // Confirmation resolves a promise; navigation can commit after the click.
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/other"),
    );
  });

  it("keeps the reader on the form when they decline", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderProbe();

    await user.click(screen.getByText("Other page"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/here");
  });

  it("does not ask for a link to the page the reader is already on", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderProbe();

    await user.click(screen.getByText("Current page"));

    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/here");
  });
});
