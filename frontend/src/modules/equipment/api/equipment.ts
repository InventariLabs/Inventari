import { equipmentAssignmentsApi } from "./equipment_assignments";
import { equipmentMaintenanceApi } from "./equipment_maintenance";
import { equipmentCampaignsApi } from "./equipment_campaigns";
import { equipmentModelsApi } from "./equipment_models";
import { equipmentAssetsApi } from "./equipment_assets";
import { equipmentDashboardApi } from "./equipment_dashboard";

export type {
  EquipmentAssignment,
  AssignmentCreate,
  AssignmentCheckin,
} from "./equipment_assignments";

export type {
  MaintenanceLog,
  MaintenanceLogCreate,
} from "./equipment_maintenance";

export type {
  AuditResponseRecord,
  CampaignResponseRecord,
  CampaignCreate,
  ScopeType,
} from "./equipment_campaigns";

export type {
  EquipmentModel,
  EquipmentModelCreate,
  EquipmentModelUpdate,
} from "./equipment_models";

export type {
  BulkEquipmentEntry,
  EquipmentAttachment,
} from "./equipment_assets";

export type {
  ImportAnalyzeResult,
  ImportExecuteResult,
} from "./equipment_dashboard";

export const equipmentApi = {
  ...equipmentAssignmentsApi,
  ...equipmentMaintenanceApi,
  ...equipmentCampaignsApi,
  ...equipmentModelsApi,
  ...equipmentAssetsApi,
  ...equipmentDashboardApi,
};
