// Analytics / reporting types.
//
// These are aliases of the generated OpenAPI schemas, not copies of them.
// A hand-written copy would drift from the backend unseen, because
// `make check-api-types` guards `api-generated.ts` and nothing guards a
// hand-written file. Aliasing keeps these types under that gate.

import type { components } from "@/types/api-generated";

type Schemas = components["schemas"];

// Cost Analysis
export type CostAnalysis = components["schemas"]["CostAnalysis"];
export type CategoryCostItem = components["schemas"]["CategoryCostItem"];
export type MonthlyTrendItem = components["schemas"]["MonthlyTrendItem"];
export type SavingsOpportunity = components["schemas"]["SavingsOpportunity"];

// Rotation Analysis
//
// The row shapes (rotation items, per-category rows, recurring products,
// seasonal products, bulk opportunities) are read off the response type
// where they are used. Re-exporting each one separately only creates a
// second name for the same thing to drift from.
export type RotationAnalysis = Schemas["RotationAnalysisResponse"];

// Smart Alerts
export type SmartAlerts = Schemas["SmartAlertsResponse"];
export type SmartAlert = Schemas["AlertItem"];

// Expense Forecast
export type ExpenseForecast = Schemas["ExpenseForecastResponse"];

// Purchase Patterns
export type PurchasePatterns = Schemas["PurchasePatternsResponse"];

// Reconciliation
export type Reconciliation = Schemas["ReconciliationResponse"];
