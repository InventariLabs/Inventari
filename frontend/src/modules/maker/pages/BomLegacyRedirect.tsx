import { Navigate } from "react-router-dom";

/**
 * `/maker/bom` was the second formula editor, removed when composing a
 * formula moved onto the recipe screen. The route stays as a redirect: the
 * old URL was reachable from the item edit modal and the items table for
 * months, so it lives on in bookmarks and browser history, and a saved link
 * should land on the catalog rather than a not-found page.
 *
 * The old `?parent=` product is deliberately dropped — it addressed a
 * product, and a product can own several formulas, which is the ambiguity
 * that got the screen removed in the first place.
 */
export default function BomLegacyRedirect() {
  return <Navigate to="/maker" replace />;
}
