import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  type InitialEntry,
} from "react-router-dom";
import { useShellBack } from "./useShellBack";

const moduleOf = (path: string) =>
  path.startsWith("/purchase-orders")
    ? "/purchase-orders"
    : path.startsWith("/warehouse")
      ? "/warehouse"
      : "/inventory";

/** What AppShell does: one header Back that lives across every screen. */
function Shell() {
  const { pathname } = useLocation();
  const back = useShellBack(moduleOf(pathname), "/launcher");
  return (
    <>
      <output data-testid="at">{pathname}</output>
      <button onClick={back}>Back</button>
    </>
  );
}

const toStart = { backTo: "/warehouse/todo" };

function renderApp(entries: InitialEntry[], index?: number) {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={index}>
      <Shell />
      <Routes>
        <Route
          path="/launcher"
          element={<Link to="/warehouse/todo">go</Link>}
        />
        <Route
          path="/warehouse/todo"
          element={
            <>
              <Link to="/warehouse/move" state={toStart}>
                move
              </Link>
              <Link to="/inventory/stock" state={toStart}>
                stock
              </Link>
            </>
          }
        />
        <Route path="/warehouse/move" element={<p>move</p>} />
        <Route path="/inventory/stock" element={<p>stock</p>} />
        <Route
          path="/purchase-orders"
          element={<Link to="/purchase-orders/7">order</Link>}
        />
        <Route
          path="/purchase-orders/7"
          element={
            <Link
              to="/warehouse/receive"
              state={{ backTo: "/purchase-orders/7" }}
            >
              receive
            </Link>
          }
        />
        <Route path="/warehouse/receive" element={<p>receipt</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const at = () => screen.getByTestId("at").textContent;
const click = (role: "link" | "button", name: string) =>
  act(() => screen.getByRole(role, { name }).click());
const link = (name: string) => click("link", name);
const back = () => click("button", "Back");

describe("useShellBack", () => {
  it("leaves an action opened from the module start by Back, Back", () => {
    renderApp(["/launcher"]);
    link("go");
    link("move");
    expect(at()).toBe("/warehouse/move");

    back();
    expect(at()).toBe("/warehouse/todo");
    back();
    expect(at()).toBe("/launcher");
  });

  it("does the same for a screen of another module that names the start", () => {
    renderApp(["/launcher"]);
    link("go");
    link("stock");
    back();
    expect(at()).toBe("/warehouse/todo");
    back();
    expect(at()).toBe("/launcher");
  });

  it("walks receipt, order, list, launcher with no screen shown twice", () => {
    renderApp(["/launcher", "/purchase-orders"], 1);
    link("order");
    link("receive");
    expect(at()).toBe("/warehouse/receive");

    back();
    expect(at()).toBe("/purchase-orders/7");
    back();
    expect(at()).toBe("/purchase-orders");
    back();
    expect(at()).toBe("/launcher");
  });

  it("puts the named screen in place of this one when the entry before is another", () => {
    // A reload or a direct link: the shell never saw the entry before.
    renderApp(
      [
        "/launcher",
        "/inventory/stock",
        { pathname: "/warehouse/move", state: toStart },
      ],
      2,
    );
    back();
    expect(at()).toBe("/warehouse/todo");
    // The move screen is gone from the history, not buried under the start.
    back();
    expect(at()).toBe("/inventory/stock");
  });
});
