// Barrel re-export — all public types for Inventari.
// Consumers: import type { SomeType } from "@/types" — no changes needed.
//
// To add new types: create/edit the appropriate domain file, not this file.
//   core.ts       — FieldDefinition, Uom, User, Organization, auth, modules
//   inventory.ts  — Item, Category, StorageLocation, Labels
//   partners.ts   — Partner
//   documents.ts  — WarehouseDocument, DocumentLine, DocumentProfile
//   stock-takes.ts — StockTake
//   shopping.ts   — ShoppingList, ShoppingListItem
//   analytics.ts  — CostAnalysis, RotationAnalysis, SmartAlerts, Forecasts
//   recipes.ts    — Recipe, RecipeIngredient, Picking, Nutrition, Cost
//   webhooks.ts   — WebhookEndpoint, WebhookDelivery
//   notifications.ts — Announcement, UserNotification
//   nutrition.ts  — IngredientDefault, UnitConversion

export * from "./core";
export * from "./inventory";
export * from "./partners";
