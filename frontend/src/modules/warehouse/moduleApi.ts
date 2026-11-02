/**
 * What the warehouse module publishes to the modules that depend on it.
 *
 * `check:boundaries` counts every import of a module's internals as an edge;
 * this file is the one it lets through. A name is added here when a second
 * module needs it, and removing or renaming one is a breaking change for
 * them — the same rule the backend's `warehouse_api` follows.
 */
export { useProductSearch } from "./hooks/useProductSearch";
export { DocumentStatusBadge } from "./components/DocumentStatusBadge";
export {
  documentsProductsApi,
  type CatalogueSearchResult,
} from "./api/documents_products";
