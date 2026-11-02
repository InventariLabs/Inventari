// Re-export from modular structure — all code should import from this file
export { moduleRegistry } from "./moduleRegistry/registry";
export { applyNavOverrides } from "./moduleRegistry/registryQueries";
export { getCoreSectionForPath } from "./moduleRegistry/coreSections";
export { resolveModuleTarget } from "./moduleRegistry/resolveModuleTarget";
export { slotComponent } from "./moduleRegistry/moduleInterfaces";
export type {
  ActionItem,
  AdoptableCoreSection,
  DocumentActionContributor,
  DocumentColumnContributor,
  DocumentFilterContributor,
  DocumentView,
  FrontendModule,
  LabelPurposeConfig,
  ListFilterContributor,
  ModuleNavItem,
  ModuleRoute,
  NavOverride,
  SearchProvider,
  SearchResult,
  SettingsSection,
  SlotContribution,
} from "./moduleRegistry/moduleInterfaces";
export type {
  DocumentFormAction,
  DocumentMetaData,
  DraftLineView,
  RegisterBeforeSubmit,
  SaveMetaData,
  SetMetaData,
  SlotDataMap,
  TargetApprovalRequest,
} from "./moduleRegistry/slotProps";
