import type { Item, ScannedTemplate, StorageType } from "@/types";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";

/**
 * The approval request a target module reads for its own record and hands to
 * the approvals module's slots. A target module (the warehouse documents, the
 * purchase orders) names it through this alias instead of importing the
 * approvals module's API file.
 */
export type TargetApprovalRequest = ApprovalRequest;

/**
 * One line of a document that is still being filled in, as a contributor
 * sees it. Deliberately small: the working shape of the screen is the
 * warehouse module's own business, this is what a rule about a line needs.
 */
export interface DraftLineView {
  /** Stable for the life of the draft; a module keys its own values by it. */
  key: string;
  itemId: string | null;
  productTemplateId: string | null;
  name: string;
  quantity: string;
  batchNumber: string | null;
  /** What modules keep on the line, each under its own name. */
  metaData: DocumentMetaData;
}

/**
 * Other modules' own fields on a document or a line: one key per module,
 * named as the module is, holding that module's values — the shape of the
 * `meta_data` the documents API stores and the pre-post check reads.
 */
export type DocumentMetaData = Record<string, Record<string, unknown>>;

/**
 * Put your module's values on the form, under your module's name; they are
 * sent with the document when the screen saves or posts it. Replaces what
 * the module had there; `null` (or an empty object) removes the key. Other
 * modules' keys are left alone.
 */
export type SetMetaData = (
  module: string,
  values: Record<string, unknown> | null,
) => void;

/**
 * Save your module's values on a document that already exists, under your
 * module's name — at once, not with a later press. Refused once the document
 * is completed or cancelled; the promise rejects with the server's answer.
 */
export type SaveMetaData = (
  module: string,
  values: Record<string, unknown> | null,
) => Promise<void>;

/** Which screen a document form slot is on. */
export type DocumentFormAction = "receive" | "issue" | "document";

/**
 * Ask to run something just before the screen saves or posts the document —
 * the moment a module writes the values it collected to its own API.
 *
 * The callback may be async. If it throws, nothing is sent and the screen
 * shows the message: throw a `ReadableError` (from `@/module-sdk`) with a
 * sentence for the reader, so a module can stop a document whose own field is
 * missing before the server is asked. A failed request to the module's own
 * API shows its 4xx message the same way. Returns the function that withdraws
 * the callback; call it when the field leaves the screen.
 */
export type RegisterBeforeSubmit = (
  callback: () => void | Promise<void>,
) => () => void;

/**
 * Maps slot names to the data shape they receive.
 * Use with TypedSlot<K> to get full compile-time safety.
 */
export interface SlotDataMap {
  item_edit_extra: {
    item: Item;
    formData: Record<string, unknown>;
    handleInputChange: (field: string, value: unknown) => void;
    storageType?: StorageType;
    /**
     * Ask the host form to release the reader, warning first if there are
     * unsaved edits. A slot rendered inside a form cannot see what the form is
     * holding, so anything that navigates away goes through here rather than
     * linking straight out.
     */
    requestLeave?: (go: () => void) => void;
  };
  quick_action_extra: { item: Item };
  /**
   * The slot inside the stock-action sheet, fed straight from the scan
   * response. Reusing `ScannedTemplate` rather than restating it: the hand-
   * written copy had drifted into fields the providers never send (`unit`,
   * `weight`) while omitting `metadata`, which they always do.
   */
  stock_action_extra: {
    barcode: string;
    template: ScannedTemplate | undefined;
  };
  global_notifications: Record<string, never>;
  items_page_header_extra: Record<string, never>;
  dashboard_widgets: { organizationId: string };
  quick_add_product_info: {
    formData: Record<string, unknown>;
    storageTypeCode?: string;
    /** The context tag of the category picked on the form, when it has one. */
    categoryContextTag?: string | null;
  };
  /**
   * The inventory dashboard's attention card, beside its "view all" link: an
   * action that opens the replenish modal (``dashboard_replenish_modal``).
   * ``onOpen`` opens it; the contributor decides whether there is anything to
   * replenish and draws nothing when there is not.
   */
  dashboard_replenish_action: {
    onOpen: () => void;
  };
  dashboard_replenish_modal: {
    isOpen: boolean;
    onClose: () => void;
  };
  /**
   * The inventory dashboard, beside the recent moves: a card of what a module
   * keeps going alongside the stock (the active shopping list).
   */
  dashboard_activity_aside: Record<string, never>;
  storage_item_edit_modal: {
    itemId: string;
    onClose: () => void;
  };
  /**
   * The product page's contribution slot: the record names a shelf and a
   * catalogue product, and a module that owns a fact about that pair
   * (putaway capacity) renders its sentence here.
   */
  item_detail_extra: {
    item: Item;
  };
  /**
   * The "cook a batch for stock" sheet on a culinary recipe's page. The recipe
   * page owns when it is open; the production module draws it and creates
   * the snapshot recipe and the DRAFT order. ``servings`` is what one batch
   * of the recipe yields.
   */
  recipe_cook_for_stock: {
    open: boolean;
    onClose: () => void;
    recipe: { id: string; name: string; servings: number };
  };
  shopping_list_add_item: {
    listId: string;
    onClose: () => void;
    onSuccess: () => void;
  };
  /** Slot rendered inside the AI Settings tab for per-module AI configuration. */
  settings_ai_module_config: Record<string, never>;
  /**
   * Slot rendered on the main Settings page as a standalone card/section.
   * Use for module-specific admin settings that don't belong to AI/Email tabs.
   * Example: nutrition module could add a "Food Database" management card.
   */
  settings_module_card: Record<string, never>;
  /**
   * Slot rendered below the items list on a Storage detail page.
   * Receives the storage context so modules can render type-specific content.
   * Example: a temperature-tracking module could add a sensor chart for FREEZER/FRIDGE types.
   */
  storage_detail_extra: {
    storageId: string;
    storageTypeCode: string | undefined;
  };
  /**
   * Slot rendered on each row of the location tree, beside its name.
   *
   * One contributor reads one cached answer for the whole tree, so a row
   * costs a lookup, not a request. A module that knows how full a place is
   * (putaway limits) draws it here; a row it knows nothing about stays plain.
   */
  storage_tree_row_extra: {
    storageId: string;
  };
  /**
   * Slot rendered in the Settings tab of a location's page: how a warehouse
   * module treats this place (walk order, what may stand here, limits).
   *
   * Carries what the storage register already knows, so the contributor reads
   * only its own module's facts. A module that is off renders nothing, and the
   * page has no empty section to explain.
   */
  storage_warehouse_strip: {
    storageId: string;
    storageName: string;
    fullPath: string | null;
    /** The walk order the register holds; `null` when the place has none. */
    sequence: number | null;
  };
  /**
   * Slot rendered in the Moves tab of a location's page.
   *
   * Separate from `storage_detail_extra` because it answers a different
   * question: what moved through here, not what may be stored here. The
   * location page puts each in its own tab.
   */
  storage_moves: {
    storageId: string;
    storageTypeCode: string | undefined;
  };
  /**
   * Slot rendered below a document's lines and totals on its detail page.
   * Receives the document's identity and state so a contributor can decide
   * whether it has anything to say yet — a draft has moved nothing.
   * Example: the movement ledger showing what the document did to stock.
   */
  document_detail_extra: {
    documentId: string;
    documentStatus: string;
    /**
     * What modules keep on the document, each under its own name. Optional
     * because the slot predates it; the warehouse's page always passes it.
     */
    metaData?: DocumentMetaData;
    /** Fill a field on the saved document — a confirmed one included. */
    saveMetaData?: SaveMetaData;
  };
  /**
   * Slot rendered under each line of a document on its detail page, in the
   * table and in the phone's cards alike. A module that keeps a fact about a
   * line (a certificate, a grade) shows it here and, while the document is
   * not yet posted, may let the reader fill it with `saveMetaData` — a field
   * its pre-post check asks for before the goods are booked. Render nothing
   * for a line the module knows nothing about.
   */
  document_detail_line_extra: {
    documentId: string;
    documentStatus: string;
    line: {
      id: string;
      lineNumber: number;
      itemId: string | null;
      productTemplateId: string | null;
      name: string | null;
      batchNumber: string | null;
      /** What modules keep on the line, each under its own name. */
      metaData: DocumentMetaData;
    };
    /** Fill a field on this line of the saved document. */
    saveMetaData: SaveMetaData;
  };
  /**
   * Slot rendered among the document-level fields of the Receive and Issue
   * screens and of the document form (a new document, or a draft edited).
   * A module adds its own field or panel here (a carrier's reference, a
   * dock). A value that belongs to the document goes on it through
   * `setMetaData` and travels with the save; a value the module keeps in its
   * own records is saved to its own API from a `registerBeforeSubmit`
   * callback — the document may not exist until the press that posts it.
   *
   * `lines` is the draft as it stands, so a panel can summarise or check it.
   */
  document_form_extra: {
    action: DocumentFormAction;
    /** The document the screen is about to write (`IN`, `OUT`, `SCRAP`, …). */
    documentType: string;
    partnerId: string | null;
    lines: DraftLineView[];
    /** What modules keep on the document, each under its own name. */
    metaData: DocumentMetaData;
    setMetaData: SetMetaData;
    registerBeforeSubmit: RegisterBeforeSubmit;
  };
  /**
   * Slot rendered on each line of the Receive and Issue screens and of the
   * document form, below the line's own fields. A module adds a per-line
   * field here (a certificate number, a customs code): `line.metaData` holds
   * what it wrote, `setMetaData` writes it back onto this line, and it is
   * sent with the line. The line disappears with its row: withdraw a
   * `registerBeforeSubmit` callback on unmount.
   */
  document_line_form_extra: {
    action: DocumentFormAction;
    documentType: string;
    line: DraftLineView;
    setMetaData: SetMetaData;
    registerBeforeSubmit: RegisterBeforeSubmit;
  };
  /** Slot rendered in document/resource detail views to show approval status and actions. */
  approval_status_badge: {
    targetType: string;
    targetId: string;
    /**
     * The request on this target, as the target module's own per-target
     * endpoint answers it (documents: ``GET /approvals/documents/{id}/approval``).
     *
     * Pass it and the card reads nothing else. The type-wide request list
     * cannot stand in for it: the server scopes that list by ``approvals:read``
     * (one sees one's own requests and the open ones one may decide), so a
     * request raised by somebody else is invisible there and the card used to
     * conclude "no request" and offer "Request Approval" on a document that
     * already had one — on an approved document, one click took it back to
     * the approval queue. It is also paginated, so the guess went wrong for
     * everybody past the first page.
     *
     * ``null`` is a settled "there is no request"; ``undefined`` means the
     * read has not landed yet and the card says nothing rather than offer a
     * request the target may already have. Leave the key out entirely and the
     * card falls back to the type list — for callers that have no per-target
     * read yet, with all the blindness above still applying.
     */
    approval?: TargetApprovalRequest | null;
    /**
     * The module whose write right raising a request on this target
     * answers to. The generic ``POST /approvals/requests`` checks
     * ``approvals:write``; a module proxying the request through its own
     * endpoints (documents, purchase_orders) names itself here so the
     * request button is gated on the right the API actually checks.
     */
    requestModule?: string;
    /**
     * What raising a request will do to the target's state, in one
     * sentence. Name it when the request does more than ask — documents
     * take a confirmed document back to the approval queue — and the
     * button asks first with this sentence, instead of one silent click.
     */
    requestConsequence?: string;
    /** Approve adapter; receives the note typed in the confirm dialog. */
    onApprove?: (requestId: string, notes?: string) => Promise<void>;
    /**
     * Override for the "Request approval" action. Target modules whose
     * request creation must also transition the entity (e.g. documents
     * park in PENDING_APPROVAL) MUST provide this adapter — the generic
     * POST /approvals/requests endpoint does not touch entity state.
     */
    onRequest?: () => Promise<void>;
    /**
     * Override for the reject action, routed through the target module's
     * endpoint (e.g. documents return to DRAFT via the rework loop).
     */
    onReject?: (requestId: string, notes: string) => Promise<void>;
  };
  /**
   * Slot rendered where a screen of the target module names an approval
   * request's state: the badge for ``status`` (``PENDING``, ``IN_PROGRESS``,
   * ``APPROVED``, ``REJECTED`` or ``CANCELLED``). Nothing renders without the
   * approvals module.
   */
  approval_request_badge: {
    status: string;
  };
  /**
   * Slot rendered on a queue card of the target module: how far the request
   * has got through its stages, and the approve / reject panel for a reader
   * who may decide it. ``onApprove`` and ``onReject`` are the target module's
   * own endpoints, so the entity moves with the decision (a document is
   * confirmed, or returned to its draft).
   */
  approval_decision_panel: {
    approval: TargetApprovalRequest;
    onApprove: (
      request: TargetApprovalRequest,
      notes?: string,
    ) => Promise<void>;
    onReject: (request: TargetApprovalRequest, notes: string) => Promise<void>;
  };
  /**
   * Slot rendered above a queue of the target module: the open requests of
   * ``targetType`` parked at a stage nobody can decide. They never reach a
   * decider's queue, so without this section they read as an empty queue.
   * ``targetHref`` is where the target module shows one record.
   */
  approval_parked_requests: {
    targetType: string;
    targetHref: (targetId: string) => string;
  };
  /**
   * Slot rendered on the document approval settings: what the configured
   * threshold and types do given the document workflows that exist, and a
   * warning with the way to create one when approval is asked for and none
   * does. ``approvalRequested`` is whether the settings on screen ask for
   * approval at all.
   */
  document_approval_setup_notice: {
    approvalRequested: boolean;
  };
}
