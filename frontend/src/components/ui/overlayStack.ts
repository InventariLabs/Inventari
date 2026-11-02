/**
 * The open sheets, in the order they were opened.
 *
 * Two problems meet here, and both are about who owns an Escape press.
 *
 * A `Sheet` opened from inside a Radix dialog — the date picker below `sm:`,
 * for instance — closes itself on Escape from its own `document` listener.
 * Radix listens on `document` too, in the capture phase, and it registered
 * first, so one press dismissed the dialog underneath in the same keystroke
 * and took the half-filled form with it. Radix asks its `onEscapeKeyDown`
 * handler first and stands down when the event comes back prevented, so the
 * dialog only needs to know that something is stacked above it —
 * {@link hasOverlaySheetOpen}.
 *
 * Facing the other way: two sheets, one over the other — the storage wizard
 * and the location list its first step opens. Both listen on `document`, and
 * a press used to close both: the list AND the wizard under it, which raised
 * its "discard this draft?" question over a list that no longer existed. One
 * press belongs to one layer, the highest one, so every sheet registers here
 * and asks {@link OverlaySheetHandle.isTopmost} before it acts.
 */

interface OpenSheet {
  /** The panel this sheet renders, for focus fallbacks. */
  panel: HTMLElement | null;
}

const openSheets: OpenSheet[] = [];

export interface OverlaySheetHandle {
  /** Whether this sheet is the highest one open — the one Escape is for. */
  isTopmost: () => boolean;
  /** Call when the sheet closes. */
  release: () => void;
}

/**
 * Call when a sheet opens; call the returned handle's `release` when it
 * closes.
 *
 * `panel` is the sheet's own surface, so that focus has somewhere inside the
 * sheet to land when the element it came from is gone —
 * {@link getTopmostOverlaySheetPanel}.
 */
export function registerOverlaySheet(
  panel: HTMLElement | null = null,
): OverlaySheetHandle {
  const sheet: OpenSheet = { panel };
  openSheets.push(sheet);
  let released = false;
  return {
    isTopmost: () => openSheets[openSheets.length - 1] === sheet,
    release: () => {
      if (released) return;
      released = true;
      const index = openSheets.indexOf(sheet);
      if (index !== -1) openSheets.splice(index, 1);
    },
  };
}

export function hasOverlaySheetOpen(): boolean {
  return openSheets.length > 0;
}

/**
 * The panel of the highest open sheet, for focus to fall back to.
 *
 * A question raised over a sheet — `ConfirmDialog` — returns focus to the
 * element it took it from; when that element closed in the meantime (a list
 * the reader picked in), the sheet it belongs to is the next best address.
 * The panel carries `tabIndex={-1}` so it can take the focus at all.
 */
export function getTopmostOverlaySheetPanel(): HTMLElement | null {
  for (let i = openSheets.length - 1; i >= 0; i -= 1) {
    const { panel } = openSheets[i];
    if (panel?.isConnected) return panel;
  }
  return null;
}

/**
 * Whether a Radix popper layer — a popover, a combobox, a select — is open.
 *
 * The mirror image of the stack above: there, a sheet stacked on a dialog;
 * here, a list opened from inside a sheet. Radix closes that list from its
 * own document listener, and the sheet used to close itself in the same
 * keystroke, so an Escape aimed at a unit list took the whole form with it.
 *
 * Read from the DOM rather than counted, because these layers are opened by
 * Radix itself and nothing in this codebase is told when they appear.
 */
export function hasPopperLayerOpen(): boolean {
  return document.querySelector("[data-radix-popper-content-wrapper]") !== null;
}

/**
 * Whether a suggestion list — the product picker of a line editor — is open.
 *
 * The same problem as {@link hasPopperLayerOpen}, for a list that is not
 * Radix's: the picker closes itself from its input's key handler, which runs
 * after the sheet's capture-phase listener, so the sheet closed — or asked its
 * discard question — on an Escape aimed at the list.
 *
 * The list carries `role="listbox"` only while it holds results, so that role
 * cannot be the only signal: the empty "No products found" panel carries no
 * listbox, and an Escape aimed at it used to reach the sheet while the panel
 * stayed open. The picker marks every open panel with
 * `data-line-item-dropdown`, which is what this reads alongside the role.
 */
export function hasListboxOpen(): boolean {
  return (
    document.querySelector('[role="listbox"]') !== null ||
    document.querySelector("[data-line-item-dropdown]") !== null
  );
}

/**
 * Whether a modal question — `ConfirmDialog`, which is Radix's
 * `role="alertdialog"` — is open over everything else.
 *
 * The other half of the same problem, facing the other way. Radix answers
 * Escape in the capture phase, so the question is already dismissed by the
 * time a sheet's own listener runs; what the sheet must not then do is act on
 * the same press — close itself, or ask its discard question a second time.
 *
 * `alertdialog` and never `dialog`: a sheet opened from *inside* a Radix
 * dialog — the date picker in a form — must still close on the key, and the
 * dialog underneath defers to it through {@link hasOverlaySheetOpen} instead.
 */
export function hasAlertDialogOpen(): boolean {
  return document.querySelector('[role="alertdialog"]') !== null;
}
