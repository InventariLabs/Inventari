//
// The canonical role sets moved beside the Core usePartners shim, where any
// module can read them without a cross-module edge: `@/hooks/partnerRoles`.
// This file keeps the partners module's own imports stable.
//
export * from "@/hooks/partnerRoles";
