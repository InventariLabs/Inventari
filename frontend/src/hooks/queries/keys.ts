/**
 * Centralized query key constants.
 * Single source of truth for all TanStack Query keys.
 * Import and use these instead of raw string arrays.
 */
export const queryKeys = {
  auditLog: {
    list: (filters: unknown) => ["audit-log", filters] as const,
    targetTypes: ["audit-log", "target-types"] as const,
  },
  stockMoves: {
    /** The ledger prefix — what every writer of stock invalidates. */
    all: ["stock-moves"] as const,
    list: (filters: unknown) => ["stock-moves", filters] as const,
  },
  stockLots: {
    /** Every lot query at once — what a stock write invalidates. */
    all: ["stock-lots"] as const,
    list: (filters: unknown) => ["stock-lots", "list", filters] as const,
    detail: (lotId: string) => ["stock-lots", lotId] as const,
  },
  stockQuants: {
    /** Every quant query at once — what a stock write invalidates. */
    all: ["stock-quants"] as const,
    list: (filters: unknown) => ["stock-quants", filters] as const,
  },
  stockAsOf: {
    report: (query: unknown) => ["stock-as-of", query] as const,
  },
  items: {
    all: ["items"] as const,
    /** Under the namespace root on purpose: a receipt, a correction or a
     * return funnels through `invalidation.documents()` → `items()`, which
     * clears the `["items"]` prefix. The singular root this key used to
     * carry escaped every one of those invalidations, and an open item card
     * kept the stock from before the write for the whole session. */
    detail: (id: string) => ["items", "detail", id] as const,
    search: (q: string, storageId?: string) =>
      storageId
        ? (["items-search", q, storageId] as const)
        : (["items-search", q] as const),
    history: ["items", "history"] as const,
    itemHistory: (itemId: string) => ["items", itemId, "history"] as const,
    storageItems: (storageId: string) => ["storage-items", storageId] as const,
    /** Every location's product list at once — what a mutation invalidates
     * when it does not know which shelf it just changed, including the case
     * that matters most: a product moved from one to another. */
    allStorageItems: ["storage-items"] as const,
    archived: ["items", "archived"] as const,
    attachments: (itemId: string) => ["attachments", itemId] as const,
  },

  inventory: {
    /** The unit the catalogue will count a typed product in, asked as the
     * form's fields stand — the barcode and the debounced name are both
     * part of the question. */
    templateUnitHint: (barcode: string, name: string) =>
      ["template-unit-hint", barcode, name] as const,
    /** Existing products whose name contains the one being typed. */
    productNameSuggestions: (name: string) =>
      ["product-name-suggestions", name] as const,
  },

  storages: {
    all: ["storages"] as const,
    tree: ["storages-tree"] as const,
    /** Under the namespace root on purpose: the tree editor, the hierarchy
     * creation and the code generator do not know which card is open, and a
     * detail on a root of its own (`["storage", id]`) escaped every prefix
     * invalidation they fired — the open card kept the state from before the
     * write for the whole staleTime. */
    detail: (id: string) => ["storages", "detail", id] as const,
    /** Under the namespace root: a numbering rewrites codes the tree shows,
     *  and invalidating `storages` refreshes both. */
    codes: (id: string) => ["storages", "codes", id] as const,
    items: (storageId: string) => ["storage-items", storageId] as const,
    breadcrumb: (id: string) => ["storage-breadcrumb", id] as const,
    types: ["storage-types"] as const,
  },

  categories: {
    all: ["categories"] as const,
    /** The equipment campaign scope picker: the creation dialog and the
     * parameters card ask the same question and must land on one entry.
     * It stays under the `["categories"]` root, the prefix
     * `invalidation.categories` clears. */
    equipmentScope: ["categories", "equipment-scope-picker"] as const,
  },

  stats: {
    overview: ["stats", "overview"] as const,
    byStorage: ["stats", "by-storage"] as const,
    byCategory: ["stats", "by-category"] as const,
    expiryForecast: ["stats", "expiry-forecast"] as const,
    costAnalysis: (period: string) =>
      ["stats", "cost-analysis", period] as const,
    rotationAnalysis: ["stats", "rotation-analysis"] as const,
    smartAlerts: ["stats", "smart-alerts"] as const,
    expenseForecast: (period: string) =>
      ["stats", "expense-forecast", period] as const,
    purchasePatterns: ["stats", "purchase-patterns"] as const,
    config: ["stats", "config"] as const,
    reconciliation: ["stats", "reconciliation"] as const,
    launcherBadge: ["stats", "overview", "launcher-badge"] as const,
    // Under `overview` on purpose: every write that moves stock already
    // invalidates that prefix, and the short-product rows must follow it.
    lowStock: ["stats", "overview", "low-stock"] as const,
  },

  labels: {
    all: ["labels"] as const,
  },

  webhooks: {
    all: ["webhooks"] as const,
    events: ["webhook-events"] as const,
    deliveries: (webhookId: string, cursor: string | null) =>
      ["webhook-deliveries", webhookId, cursor] as const,
  },

  organization: {
    detail: ["organization"] as const,
    members: ["organization-members"] as const,
    invitations: ["organization-invitations"] as const,
    failedEmails: ["organization-failed-emails"] as const,
  },

  admin: {
    /** The bare `["admin"]` root — what `invalidation.admin()` clears. It is
     * not the prefix of the cloud-admin entries below, which have roots of
     * their own; the announcements list is the one key that sits under it. */
    all: ["admin"] as const,
    announcements: ["admin", "announcements"] as const,
    registrationRequests: ["registration-requests"] as const,
    organizations: ["cloud-admin-orgs"] as const,
    stats: ["cloud-admin-stats"] as const,
    allModules: ["cloud-admin-all-modules"] as const,
    aiUsage: (days: number) => ["cloud-ai-usage", days] as const,
    orgAiStats: (orgId: string) => ["org-ai-stats", orgId] as const,
    systemSettings: ["cloud-system-settings"] as const,
    cloudOrganizations: ["cloud-organizations"] as const,
    initStatus: ["init-status"] as const,
    registerInvitation: (code: string | null) =>
      ["register-invitation", code] as const,
    registerApprovedRequest: (token: string | null) =>
      ["register-approved-request", token] as const,
    appVersion: ["app-version"] as const,
  },

  notifications: {
    all: ["notifications"] as const,
  },

  shoppingLists: {
    all: ["shopping-lists"] as const,
    active: ["active-shopping-list"] as const,
    detail: (id: string) => ["shopping-lists", "detail", id] as const,
    /** The whole suggestions namespace, prefix of both the per-list
     *  suggestions and the list-free preview below. What a list holds is
     *  what makes a proposal obsolete, so a write to a list invalidates
     *  this whole family, not only the list itself. */
    suggestionsAll: ["shopping-suggestions"] as const,
    suggestions: (listId: string) => ["shopping-suggestions", listId] as const,
    /** The list-free preview: keyed by what was asked for, since the
     *  answer differs by source and no list identifies it. */
    suggestionsPreview: (sources?: Record<string, boolean | undefined>) =>
      ["shopping-suggestions", "preview", sources ?? {}] as const,
  },

  recipes: {
    all: (params?: unknown) =>
      params ? (["recipes", params] as const) : (["recipes"] as const),
    available: (params?: unknown) =>
      params
        ? (["recipes", "available", params] as const)
        : (["recipes", "available"] as const),
    /** The whole detail family hangs off the namespace root: a list-level
     * caller — a duplicate, a bulk delete, a tag change — invalidates the
     * namespace without an id to hand, and a detail on a root of its own
     * (`["recipe", id]`) escaped every one of them, leaving the open card on
     * the state from before the write for the whole staleTime. */
    detail: (id: string) => ["recipes", "detail", id] as const,
    /** Every servings value's availability at once — a stock write makes
     *  all of them stale, and the writer does not know which one the open
     *  card asked for. */
    availabilityAll: (id: string) =>
      ["recipes", "detail", id, "availability"] as const,
    availability: (id: string, servings: number) =>
      ["recipes", "detail", id, "availability", servings] as const,
    nutrition: (id: string, servings: number) =>
      ["recipes", "detail", id, "nutrition", servings] as const,
    history: (id: string) => ["recipes", "detail", id, "history"] as const,
    cost: (id: string, servings?: number) =>
      ["recipes", "detail", id, "cost", servings] as const,
    tags: ["recipe-tags"] as const,
    /** The same list, counted for the view the reader is in — search, tag,
     *  favorite and collection narrowing answer on the chips themselves. */
    tagsFor: (params: unknown) => ["recipe-tags", params] as const,
    collections: ["recipe-collections"] as const,
    /** The global backlog of ingredients no recipe has linked yet — the
     *  mass-matching screen's list. It hangs off the namespace root, so the
     *  recipe mutations' prefix invalidation refreshes it too. */
    unlinkedIngredients: ["recipes", "unlinked-ingredients"] as const,
    /** The unit each linked ingredient is kept in, by template id — one
     * answer for the whole set, so the ids are part of the key. */
    ingredientStockUnits: (ids: string[]) =>
      ["ingredient-stock-units", ids] as const,
  },

  mealPlans: {
    all: (params?: unknown) =>
      params ? (["meal-plans", params] as const) : (["meal-plans"] as const),
    /** Under the namespace root for the same reason as the recipe detail:
     * the delete flow invalidates the namespace without the id in hand. */
    detail: (id: string) => ["meal-plans", "detail", id] as const,
    suggestions: (params: unknown) =>
      ["meal-plan-suggestions", params] as const,
    exclusions: ["shopping-exclusions"] as const,
  },

  stockTakes: {
    /** The namespace root — what a writer of stock takes invalidates. The
     * parameterised list sits under `list`, the way `stockMoves` splits its
     * own root from its filters: a parameterised `all(status)` stood here,
     * and invalidating through it cleared `["stock-takes", ""]` and nothing
     * beside it — not the other statuses, not the launcher actions, and not
     * the take an open counting screen reads. */
    all: ["stock-takes"] as const,
    list: (status?: string) => ["stock-takes", status ?? ""] as const,
    detail: (id: string) => ["stock-takes", "detail", id] as const,
    report: (id: string) => ["stock-takes", "detail", id, "report"] as const,
    /** When each location was last counted — under the root, so closing a
     * count refreshes it with everything else. */
    locations: ["stock-takes", "locations"] as const,
    launcherActions: [
      "stock-takes",
      "in_progress",
      "launcher-actions",
    ] as const,
  },

  modules: {
    my: ["my-modules"] as const,
    available: ["modules", "available"] as const,
    focus: ["modules", "focus"] as const,
    settings: (name: string) => ["modules", "settings", name] as const,
    /** Placeholder for a settings query that is disabled until a module is chosen. */
    settingsNone: ["modules", "settings", "none"] as const,
  },

  uoms: {
    all: ["uoms"] as const,
    categories: ["uoms", "categories"] as const,
  },

  announcements: {
    active: ["announcements", "active"] as const,
  },

  documents: {
    all: ["documents"] as const,
    detail: (id: string) => ["documents", id] as const,
    sourceNumbers: (ids: string[]) =>
      ["documents", "source-numbers", ids] as const,
    corrections: (documentId: string) =>
      ["documents", documentId, "corrections"] as const,
    /** The scanning session still open over the document, if any. */
    scanSession: (documentId: string) =>
      ["documents", documentId, "scan-session"] as const,
    /** The dispatch's packages; under the document, so its writes refresh them. */
    packing: (documentId: string) =>
      ["documents", documentId, "packing"] as const,
    /** The reserve move an alert proposes for one reorder rule. */
    replenishmentProposal: (ruleId: string) =>
      ["documents", "replenishment-proposal", ruleId] as const,
    /** The organization's carriers; under the documents, so a completion
     * that names a new one refreshes them. */
    carriers: ["documents", "carriers"] as const,
    profile: ["document-profile"] as const,
    presets: ["document-profile", "presets"] as const,
    /** The registered pick orders the profile's choice is made from. */
    pickOrderStrategies: ["document-profile", "pick-order-strategies"] as const,
    periods: ["inventory-periods"] as const,
    register: (params: unknown) => ["documents-register", params] as const,
    registerRows: (params: unknown) =>
      ["documents-register-rows", params] as const,
    putawayRules: ["putaway-rules"] as const,
    /** The organization's tax rates, and what goods name one of them. */
    taxRates: ["tax-rates"] as const,
    taxRatesCountry: ["tax-rates", "country"] as const,
    taxRatesCategories: ["tax-rates", "categories"] as const,
    taxRateOfProduct: (templateId: string) =>
      ["tax-rates", "products", templateId] as const,
    /** Where a receive sheet's unsaved lines will land, per destination. */
    putawayPreview: (targetLocationId: string | null, inputs: unknown) =>
      ["documents", "putaway-preview", targetLocationId, inputs] as const,
    /** How each warehouse receives: one step, or into a receiving area. */
    putawayReceivingModes: ["putaway-receiving-modes"] as const,
    putawayHomeSilenced: ["putaway-home-silenced"] as const,
    /** Every capacity entry of the organization — the locations tab's list. */
    putawayCapacityAll: ["putaway-capacity"] as const,
    putawayCapacity: (locationId: string) =>
      ["putaway-capacity", locationId] as const,
    /** Every location whose product mix was chosen; mixed shelves have no row. */
    putawayCapacitySettings: ["putaway-capacity-settings"] as const,
    putawayCapacitySetting: (locationId: string) =>
      ["putaway-capacity-setting", locationId] as const,
    /** Every occupancy answer, per warehouse — one read per shown subtree. */
    putawayOccupancyAll: ["putaway-occupancy"] as const,
    putawayOccupancy: (locationId: string) =>
      ["putaway-occupancy", locationId] as const,
    // Under the same root as the per-location read, so the one invalidation
    // a limit change already makes refreshes the screen too.
    putawayOccupancyOverview: ["putaway-occupancy", "overview"] as const,
    awaitingApproval: ["documents", "awaiting-my-approval"] as const,
    awaitingApprovalPage: (offset: number, limit: number) =>
      ["documents", "awaiting-my-approval", offset, limit] as const,
    /**
     * The key of the document's approval entry. The requirement nests under
     * it on purpose: the invalidation that clears the request also clears the
     * rule that asked for one, so the two answers never drift apart.
     */
    /** Every document's approval entry — the prefix of `approval`. */
    approvalAll: ["document-approval"] as const,
    approval: (docId: string) => ["document-approval", docId] as const,
    approvalRequirement: (docId: string) =>
      ["document-approval", docId, "requirement"] as const,
  },

  partners: {
    all: ["partners"] as const,
    detail: (id: string) => ["partners", id] as const,
    employees: (search: string) => ["partners", "employees", search] as const,
  },

  equipment: {
    all: ["equipment"] as const,
    dashboard: ["equipment", "dashboard"] as const,
    assets: {
      all: ["equipment", "assets"] as const,
      list: (params: unknown) =>
        ["equipment", "assets", "list", params] as const,
      detail: (id: string) => ["equipment", "assets", "detail", id] as const,
    },
    assignments: {
      active: ["equipment", "assignments", "active"] as const,
      itemHistory: (itemId: string) =>
        ["equipment", "assignments", "item", itemId] as const,
    },
    warrantyAlerts: (days?: number) =>
      ["equipment", "warranty-alerts", days ?? 30] as const,
    warrantyBadge: [
      "equipment",
      "warranty-alerts",
      30,
      "launcher-badge",
    ] as const,
    maintenance: {
      all: ["equipment", "maintenance"] as const,
      itemLogs: (itemId: string) =>
        ["equipment", "maintenance", "item", itemId] as const,
    },
    timeline: (itemId: string) => ["equipment", "timeline", itemId] as const,
    templates: ["equipment", "templates"] as const,
    placeholders: ["equipment", "placeholders"] as const,
    models: ["equipment", "models"] as const,
    campaigns: {
      list: ["equipment", "campaigns"] as const,
      detail: (id: string) => ["equipment", "campaigns", id] as const,
      scopePreview: (type: string, filterId: string) =>
        ["equipment", "campaigns", "scope-preview", type, filterId] as const,
    },
    valuation: {
      fleet: ["equipment", "valuation", "fleet"] as const,
      asset: (id: string) => ["equipment", "valuation", "asset", id] as const,
    },
  },

  /** The public attestation page, reached by token with no session. Read
   * once and never refetched: nothing in this tree invalidates it. */
  attestation: {
    response: (token: string | undefined) => ["attestation", token] as const,
  },

  purchaseOrders: {
    all: ["purchase-orders"] as const,
    list: (params: unknown) => ["purchase-orders", params] as const,
    detail: (id: string) => ["purchase-orders", id] as const,
    linkedReceipts: (poId: string) =>
      ["purchase-orders", poId, "linked-receipts"] as const,
    pendingQuantities: (poId: string) =>
      ["purchase-orders", poId, "pending-quantities"] as const,
    approvalRequirement: (poId: string) =>
      ["purchase-orders", poId, "approval-requirement"] as const,
    settings: () => ["purchase-orders", "settings"] as const,
    pricelistForPartner: (partnerId: string, params?: unknown) =>
      ["purchase-orders", "pricelist", partnerId, params] as const,
    pricelistForTemplate: (templateId: string) =>
      ["purchase-orders", "pricelist", "template", templateId] as const,
    pricelistBestForTemplate: (templateId: string) =>
      ["purchase-orders", "pricelist", "best", templateId] as const,
    reorderRules: (params?: unknown) =>
      ["purchase-orders", "reorder-rules", params] as const,
    replenishmentAlerts: () =>
      ["purchase-orders", "replenishment-alerts"] as const,
  },

  apiKeys: {
    all: ["api-keys"] as const,
    capabilities: ["api-keys", "capabilities"] as const,
  },

  printing: {
    labelScan: (code: string) => ["label-scan", code] as const,
    agents: ["printing", "agents"] as const,
    jobs: ["printing", "jobs"] as const,
  },

  onboarding: {
    profiles: ["onboarding", "profiles"] as const,
    countryPreset: (country: string) =>
      ["onboarding", "country-preset", country] as const,
  },

  templates: {
    list: (module: string) => ["templates", module] as const,
    placeholders: (module: string) =>
      ["templates", module, "placeholders"] as const,
    builtIn: (module: string) => ["templates", module, "built-in"] as const,
  },

  /** Rendered Jinja previews. The layout source is part of the key: the
   * editor asks "does this render" on every keystroke, and an answer belongs
   * to the exact source it was asked about. So does the UI language: the
   * labels a layout prints are rendered in the language the request carried. */
  templatePreview: {
    render: (module: string, bodyHtml: string, language: string) =>
      ["template-preview", module, bodyHtml, language] as const,
  },

  productTemplates: {
    count: ["product-templates", "count"] as const,
    stock: (templateId: string) =>
      ["product-templates", templateId, "stock"] as const,
  },

  users: {
    orgMembers: ["users", "org-members"] as const,
    orgRoles: ["users", "org-roles"] as const,
  },

  roles: {
    /** The RBAC matrix's role list. Every create, rename, permission edit
     * and delete clears the whole namespace — the pickers that read it are
     * spread across screens. */
    all: ["roles"] as const,
    /** Who holds a role — fetched while the delete dialog is open, because
     * that is the one moment their names matter. */
    members: (roleId: string | null) => ["roles", roleId, "members"] as const,
    /** The permission catalog the matrix renders — the backend's own list,
     * not the hand-maintained copy of the enum it replaced. */
    permissionCatalog: ["roles", "permission-catalog"] as const,
    permissionCatalogAll: ["roles", "permission-catalog", "all"] as const,
  },

  approvals: {
    /** The namespace root: the request queue and the workflow list both sit
     * under it, so one invalidation reaches everything a decision changes. */
    all: ["approvals"] as const,
    workflows: ["approvals", "workflows"] as const,
    /** Whether a request would land for one target type — one bit, keyed by
     *  the type it answers for. Nested under `workflows` so a workflow write
     *  invalidates it with the list it was computed from. */
    workflowConfigured: (targetType: string) =>
      ["approvals", "workflows", "configured", targetType] as const,
    /** What switching one workflow off would release; nested under
     *  `workflows` so the write that switches it off invalidates the count. */
    workflowWaiting: (id: string) =>
      ["approvals", "workflows", "waiting", id] as const,
    requests: ["approvals", "requests"] as const,
  },

  commandPalette: {
    search: (query: string, enabledModules: unknown) =>
      ["command-palette-search", query, enabledModules] as const,
  },

  settings: {
    detail: ["settings"] as const,
  },

  about: {
    detail: ["about"] as const,
  },

  aiConnections: {
    all: ["ai-connections"] as const,
    purposes: ["ai-connections", "purposes"] as const,
    bindings: ["ai-connections", "bindings"] as const,
  },

  maker: {
    /** The whole namespace at once — `["maker"]`, the root every BoM,
     * production, pricing and recipe key sits under, and what
     * `invalidation.maker` clears. */
    all: ["maker"] as const,
    bom: (templateId: string) => ["maker", "bom", templateId] as const,
    bomTree: (templateId: string) =>
      ["maker", "bom", "tree", templateId] as const,
    bomSummary: (templateId: string) =>
      ["maker", "bom", "summary", templateId] as const,
    bomSummaryBatch: (templateIds: string[]) =>
      ["maker", "bom", "summary", "batch", [...templateIds].sort()] as const,
    bomParents: ["maker", "bom", "parents"] as const,
    bomTemplateIds: () => ["maker", "bom", "template-ids"] as const,
    bomWhereUsed: ["maker", "bom", "where-used"] as const,
    bomCostEstimate: (templateId: string, recipeId?: string, qty?: string) =>
      [
        "maker",
        "bom",
        "cost-estimate",
        templateId,
        recipeId ?? "default",
        qty ?? "1",
      ] as const,
    productionList: (params?: unknown) =>
      params
        ? (["maker", "production", params] as const)
        : (["maker", "production"] as const),
    productionDetail: (id: string) => ["maker", "production", id] as const,
    /** The order's stock-move feed, read beside the order itself — reached
     * by `invalidation.maker` through the `maker.all` prefix. */
    productionStockMoves: (orderId?: string) =>
      ["maker", "production", orderId ?? "", "stock-moves"] as const,
    monthlyResult: (months: number) =>
      ["maker", "production", "monthly-result", months] as const,
    /** What a run on the production sheet would take and cost, per form state. */
    productionPreview: (payload: unknown) =>
      ["maker", "production-preview", payload] as const,
    breakdown: (templateId: string, qty: string, recipeId?: string | null) =>
      ["maker", "breakdown", templateId, qty, recipeId ?? null] as const,
    /** Placeholder for a breakdown query that is disabled until a template is chosen. */
    breakdownNoop: ["maker", "breakdown", "noop"] as const,
    margin: (templateId: string) =>
      ["maker", "pricing", "margin", templateId] as const,
    /** Placeholder for a margin query that is disabled until a template is chosen. */
    marginNoop: ["maker", "pricing", "margin", "noop"] as const,

    // BoM recipes. Shapes are byte-identical to the inline `["maker",
    // "recipes", ...]` arrays that `modules/maker/hooks/useRecipes.ts` used
    // before the migration, so nothing already cached is orphaned.
    recipesAll: ["maker", "recipes"] as const,
    recipeCatalog: (
      search: string | undefined,
      sort: string,
      skip: number,
      limit: number,
    ) => ["maker", "recipes", "catalog", search, sort, skip, limit] as const,
    recipeDetail: (id: string | undefined) =>
      ["maker", "recipes", "detail", id] as const,
    recipeSettings: ["maker", "recipes", "settings"] as const,
    recipeAvailability: (
      id: string | undefined,
      batches: string | undefined,
      locationId: string | undefined,
    ) => ["maker", "recipes", "availability", id, batches, locationId] as const,
  },
} as const;
