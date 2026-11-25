import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  type InitialEntry,
} from "react-router-dom";
import { useBackToScreen, useShellBack } from "./useShellBack";

const moduleOf = (path: string) =>
  path.startsWith("/purchase-orders")
    ? "/purchase-orders"
    : path.startsWith("/warehouse")
      ? "/warehouse"
      : "/inventory";

// The screens the app registers: `/warehouse/documents` is not one of them,
// only a document under it is, and the module root `/warehouse` only sends
// the person on to History.
const SCREENS = [
  "/warehouse/todo",
  "/warehouse/history",
  "/warehouse/receive",
  "/inventory/stock",
];

/** What AppShell does: one header Back that lives across every screen. */
function Shell() {
  const { pathname } = useLocation();
  const back = useShellBack(moduleOf(pathname), "/launcher", (path) =>
    SCREENS.includes(path),
  );
  return (
    <>
      <output data-testid="at">{pathname}</output>
      <button onClick={back}>Back</button>
    </>
  );
}

/** The posted result's "Back to start" button. */
function BackToStart() {
  const toStartScreen = useBackToScreen("/warehouse/todo");
  return <button onClick={toStartScreen}>Back to start</button>;
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
        <Route path="/warehouse/move" element={<BackToStart />} />
        <Route
          path="/inventory/stock"
          element={
            <Link to="/warehouse/move" state={toStart}>
              move from stock
            </Link>
          }
        />
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
        <Route path="/warehouse/receive" element={<BackToStart />} />
        <Route path="/warehouse/documents/7" element={<p>document</p>} />
        <Route path="/inventory/items/42" element={<p>item</p>} />
        <Route path="/warehouse" element={<p>module root</p>} />
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
  beforeEach(() => sessionStorage.clear());

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

  it("pops to the screen it came from when a reload hid the entry before", () => {
    // After a reload the shell never saw the entry before, but the browser
    // counts one: replacing would show the start twice in a row.
    renderApp(
      [
        "/launcher",
        "/warehouse/todo",
        { pathname: "/warehouse/move", state: toStart },
      ],
      2,
    );
    back();
    expect(at()).toBe("/warehouse/todo");
    back();
    expect(at()).toBe("/launcher");
  });

  it("puts the named screen in place of this one when the entry before is another", () => {
    renderApp(["/launcher", "/inventory/stock"], 1);
    link("move from stock");
    expect(at()).toBe("/warehouse/move");
    back();
    expect(at()).toBe("/warehouse/todo");
    // The move screen is gone from the history, not buried under the start.
    back();
    expect(at()).toBe("/inventory/stock");
  });

  it("puts the named screen in place of this one when nothing is left to pop", () => {
    renderApp([{ pathname: "/warehouse/move", state: toStart }]);
    back();
    expect(at()).toBe("/warehouse/todo");
  });

  it("leads home from a document opened by a direct link, past a path no screen answers", () => {
    // The receiving sheet's way in: the receive page replaces itself with the
    // document, so a phone that opened that link has no entry to pop.
    renderApp(["/warehouse/documents/7"]);
    back();
    expect(at()).toBe("/launcher");
  });

  it("never climbs from History to a root that sends the person straight back", () => {
    renderApp(["/warehouse/history"]);
    back();
    expect(at()).toBe("/launcher");
  });

  it("goes home when the module registers no screen above this one", () => {
    // In this fixture `/inventory` has a stock screen but no root of its own: the
    // climb runs out of screens and the launcher is the only answer left.
    renderApp(["/inventory/items/42"]);
    back();
    expect(at()).toBe("/launcher");
  });

  it("leaves a posted result for the start without a second copy of it", () => {
    renderApp(["/launcher"]);
    link("go");
    link("move");
    click("button", "Back to start");
    expect(at()).toBe("/warehouse/todo");
    // The form the reader finished is not behind the start any more.
    back();
    expect(at()).toBe("/launcher");
  });

  it("sends a posted result to the start after a reload, not to the order it came from", () => {
    // The receipt was opened from the order, then the tab reloaded: the shell
    // reads the entry before from the tab's storage and does not pop to the
    // order as if it were the start.
    sessionStorage.setItem(
      "inventari.shell-entry-before",
      JSON.stringify({ key: "receipt", path: "/purchase-orders/7" }),
    );
    renderApp(
      [
        "/launcher",
        "/purchase-orders/7",
        { pathname: "/warehouse/receive", key: "receipt" },
      ],
      2,
    );
    click("button", "Back to start");
    expect(at()).toBe("/warehouse/todo");
    back();
    expect(at()).toBe("/purchase-orders/7");
  });

  it("keeps the entry before across a reload for the header", () => {
    renderApp(["/launcher", "/purchase-orders"], 1);
    link("order");
    link("receive");
    const saved = JSON.parse(
      sessionStorage.getItem("inventari.shell-entry-before") ?? "null",
    );
    expect(saved.path).toBe("/purchase-orders/7");
  });
});
