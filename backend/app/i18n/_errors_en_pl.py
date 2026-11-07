from app.i18n._types import ErrorMessages

ERRORS_EN_PL: dict[str, ErrorMessages] = {
    'en': {
        'invalid_credentials': 'Invalid email or password',
        'invalid_input': 'Invalid input',
        'not_authenticated': 'Not authenticated',
        'user_already_exists': 'User with this email already exists',
        'user_already_in_organization': 'User already belongs to an organization',
        'token_expired': 'Authentication token has expired',
        'token_invalid': 'Invalid authentication token',
        'insufficient_permissions': 'You do not have permission to perform this action',
        'import_create_forbidden': 'This account does not hold the permissions {permissions}, so the import may not create missing locations or categories on its behalf. Turn off the matching toggles in the import dialog, or ask for the permission',
        'import_create_forbidden_one': 'This account does not hold the permission {permissions}, so the import may not create missing locations or categories on its behalf. Turn off the matching toggles in the import dialog, or ask for the permission',
        'import_stubs_forbidden': 'This account does not hold {permissions}, so the import may not create temporary products for unmatched barcodes on its behalf. Clear the "Create product stubs for unmatched barcodes" checkbox in the import dialog, or ask for the permission',
        'user_blocked': 'Your account has been blocked. Reason: {reason}',
        'user_blocked_no_reason': 'No reason provided',
        'uom_not_found': 'Unit not found',
        'import_job_not_found': 'Import not found',
        'user_not_found': 'User not found',
        'user_email_required': 'This account has no email address, so it has no assets to show.',
        'user_inactive': 'Your account is pending approval by an administrator.',
        'item_not_found': 'Item not found',
        'item_quantity_above_ceiling': 'The quantity {quantity} is past what the column holds — the largest storable value is {ceiling}',
        'item_quantity_raise_in_virtual_location': 'This product stands in {location}, where stock is not counted — move it back to a shelf first, then add to it',
        'counted_quantity_above_ceiling': 'The counted quantity {quantity} is past what the column holds — the largest storable value is {ceiling}',
        'item_create_failed': 'Failed to create item',
        'item_update_failed': 'Failed to update item',
        'item_delete_failed': 'Failed to delete item',
        'storage_not_found': 'Storage location not found',
        'storage_create_failed': 'Failed to create storage location',
        'storage_update_failed': 'Failed to update storage location',
        'storage_delete_failed': 'Failed to delete storage location',
        'storage_delete_failed_items': 'Cannot delete a storage location that contains items. Move or delete them first.',
        'storage_delete_blocked_by_production_orders': 'Cannot delete storage location: it is used by production orders.',
        'storage_type_not_found': 'Storage location type not found',
        'storage_type_create_failed': 'Failed to create storage location type',
        'storage_type_update_failed': 'Failed to update storage location type',
        'storage_type_delete_failed': 'Failed to delete storage location type',
        'storage_type_exists': 'A storage location type with this code already exists',
        'storage_type_no_access': 'You do not have access to this storage location type',
        'storage_type_in_use': 'Storage location type is in use by {count} locations',
        'storage_usage_immutable': "A storage location's purpose is set by the system and cannot be changed.",
        'storage_type_system_modify': 'System storage location types cannot be modified',
        'storage_type_system_delete': 'System storage location types cannot be deleted',
        'category_not_found': 'Category not found',
        'category_create_failed': 'Failed to create category',
        'category_update_failed': 'Failed to update category',
        'category_delete_failed': 'Failed to delete category',
        'storage_archived': 'This location is archived. Restore it before storing products here.',
        'stock_take_not_found': 'Stock take not found',
        'stock_take_already_completed': 'Stock take has already been completed',
        'stock_take_not_in_progress': 'Stock take is not in progress',
        'stock_take_create_failed': 'Failed to create stock take',
        'stock_take_update_failed': 'Failed to update stock take',
        'shopping_list_not_found': 'Shopping list not found',
        'shopping_list_create_failed': 'Failed to create shopping list',
        'shopping_list_update_failed': 'Failed to update shopping list',
        'shopping_list_not_writable': 'This shopping list is {status} and cannot be modified. Reactivate it first.',
        'shopping_list_delete_failed': 'Failed to delete shopping list',
        'shopping_list_item_not_found': 'Shopping list item not found',
        'shopping_list_item_quantity_rounds_to_zero': "Quantity {quantity} rounds to zero at the store's precision — the smallest countable amount is {smallest}",
        'shopping_list_item_quantity_above_ceiling': 'The quantity {quantity} is past what the column holds — the largest storable value is {ceiling}',
        'shopping_list_item_uom_unknown': 'Unknown unit of measure (uom_id: {uom_id}) — the unit does not exist',
        'shopping_list_item_item_unknown': 'Unknown product (item_id: {item_id}) — the item does not exist',
        'shopping_list_item_category_unknown': 'Unknown category (category_id: {category_id}) — the category does not exist',
        'shopping_list_item_template_unknown': 'Unknown product template (template_id: {template_id}) — the template does not exist',
        'organization_not_found': 'Organization not found',
        'organization_create_failed': 'Failed to create organization',
        'organization_update_failed': 'Failed to update organization',
        'organization_delete_failed': 'Failed to delete organization',
        'smtp_not_configured': 'This organization has no email sending configured',
        'demo_smtp_settings_locked': 'This is the public demo, so the mail server is fixed: every message the app would send is caught in the demo inbox. Email settings cannot be changed here.',
        'demo_credentials_locked': 'This is the public demo, where every email lands in a public inbox. Passwords cannot be changed or reset here, and visitors need no account.',
        'demo_registration_locked': 'This is the public demo, where visitors need no account. Request Access is not available here — use Try the demo to look around.',
        'role_in_use': 'This role is still assigned to somebody. Change their role first, then delete it.',
        'role_name_taken': 'A role named "{name}" already exists in this organisation.',
        'invitation_not_found': 'Invitation not found',
        'organization_invite_invalid': "This invitation can't be used. Check that you are registering with the e-mail address it was sent to, or ask for a new one.",
        'organization_invite_link_dead': "This invitation link doesn't work any more. Ask whoever sent it for a new one.",
        'organization_invite_expired': 'Organization invitation has expired',
        'email_test_failed': 'Test email could not be sent',
        'module_org_required': 'You must belong to an organization to manage modules. Please sign in again or contact support.',
        'module_premium_locked': "Module '{module}' is a premium feature. Contact the system administrator to enable it for your organization.",
        'module_always_on': "Module '{module}' is always enabled and cannot be turned off.",
        'module_requires_other': "Module '{required}' must be enabled first.",
        'module_blocks_dependent': "Module '{dependent}' depends on '{module}' and is currently enabled. Disable '{dependent}' first.",
        'webhook_url_loopback': 'This address points back at the server itself ({host}), so the webhook would never leave the machine. Use an address reachable from the internet, or ask whoever runs this installation to allow local addresses (the WEBHOOKS_ALLOW_PRIVATE_NETWORKS setting).',
        'webhook_url_private': 'This address ({host}) is not publicly routable or is reserved for protocol infrastructure, so the server refuses to call it. Use an address reachable from the internet, or ask whoever runs this installation to allow local addresses (the WEBHOOKS_ALLOW_PRIVATE_NETWORKS setting).',
        'webhook_url_unresolved': "The host name '{host}' could not be resolved, so the address cannot be checked. Use a name that resolves publicly, or ask whoever runs this installation to allow local addresses (the WEBHOOKS_ALLOW_PRIVATE_NETWORKS setting).",
        'webhook_url_rebinding': "The host name '{host}' resolves to an address that is not publicly routable or is reserved for protocol infrastructure ({resolved}). Use an address reachable from the internet, or ask whoever runs this installation to allow local addresses (the WEBHOOKS_ALLOW_PRIVATE_NETWORKS setting).",
        'reg_request_new_title': 'New access request',
        'reg_request_new_content': 'User {name} is requesting access to the system.',
        'reg_request_approved_title': 'Access request approved',
        'reg_request_approved_content': 'Access for {email} has been approved by {admin}.',
        'reg_link_undelivered_title': 'Registration link not delivered',
        'reg_link_undelivered_content': 'The email with the registration link could not be delivered to {email}. Pass this link on yourself: {link}',
        'reg_request_rejected_title': 'Access request rejected',
        'reg_request_rejected_content': 'Access for {email} has been rejected by {admin}.',
        # The scheduled reconciliation warns each admin in the language that
        # admin reads. A notification row is stored as text and read months
        # later, so the language it is written in is the language it keeps —
        # and the sentence names the tabs exactly as the interface does,
        # because "Stats → Reconciliation" points at no label a Polish reader
        # can find on the screen it sends them to.
        'reconciliation_drift_title': 'Stock drift detected',
        'reconciliation_drift_content': (
            'The scheduled stock check found numbers that do not agree — '
            '{pairs}. See Statistics → Reconciliation.'
        ),
        'reconciliation_drift_standing_title': 'Stock drift still standing',
        'reconciliation_drift_standing_content': (
            'The disagreement reported earlier has not changed and is still '
            'there — {pairs}. See Statistics → Reconciliation.'
        ),
        'reconciliation_pair_quant_ledger': 'the shelf vs the movement ledger: {count}',
        'reconciliation_pair_layer_quant': 'the cost history vs the shelf: {count}',
        'event_delivery_dead_title': 'A background task keeps failing',
        'event_delivery_dead_content': (
            'The handler {handler} of the event {event} failed {attempts} times and was stopped. Last error: {error}. The event is kept in event_deliveries for inspection.'
        ),
        'field_required': 'This field is required',
        'invalid_email': 'Invalid email format',
        'password_too_short': 'Password must be at least 8 characters',
        'password_invalid': 'Password must contain at least one uppercase letter, one lowercase letter, and one number',
        'password_too_long': 'Password may be at most {max_bytes} bytes long',
        'password_needs_lowercase': 'Password must contain at least one lowercase letter',
        'password_needs_uppercase': 'Password must contain at least one uppercase letter',
        'password_needs_digit': 'Password must contain at least one digit',
        'sku_format_invalid': 'SKU may contain only letters, digits, dashes, underscores and slashes',
        'sku_in_use': 'SKU {sku} already belongs to another product',
        'custom_field_required': 'The field "{field}" is required',
        'field_multi_select_shape': 'The field "{field}" must be a list of options',
        'field_option_not_allowed': 'The value "{value}" is not one of the options of the field "{field}": {options}',
        'field_money_shape': 'The field "{field}" must hold an amount and a currency, and nothing else',
        'field_money_amount': 'The amount of the field "{field}" must be a number',
        'field_money_currency': 'The currency of the field "{field}" must be a 3-letter ISO 4217 code, such as EUR',
        'field_select_shape': 'The field "{field}" must be a single option',
        'item_limit_reached': 'Item limit reached for this organization. Upgrade to Inventari Cloud.',
        'item_archived': 'Item is archived and can be restored from the archive',
        'announcement_type_invalid': 'Invalid announcement type. Allowed: {allowed}',
        'ai_provider_invalid': 'Invalid provider. Allowed: {allowed}',
        'field_options_required': 'A field of type {type} needs a non-empty list of options',
        'member_role_exactly_one': 'Provide exactly one of role or role_id',
        'reason_blank': 'The reason must not be blank',
        'discrepancy_reason_required': 'A discrepancy reason is required',
        'invalid_uuid': 'Invalid UUID format',
        'sheet_unreadable': 'This file could not be read as a spreadsheet. Check that it is a valid .xlsx or .csv file and try again.',
        'pasted_text_unreadable': 'The pasted text could not be read as a table. Paste rows copied from a spreadsheet, with the same number of columns in each.',
        'webhook_url_malformed': 'This is not a valid web address. Enter a full address such as https://example.com/hook.',
        'recipe_extraction_failed': 'The recipe could not be extracted from this page. Try again, or enter the recipe by hand.',
        'invalid_date': 'Invalid date format',
        'value_must_be_positive': 'Value must be positive',
        'value_must_be_greater_than_zero': 'Value must be greater than zero',
        'insufficient_quantity': 'Not enough stock to perform this action',
        'file_type_not_allowed': 'File type not allowed',
        'file_signature_mismatch': 'File signature does not match the declared file type',
        'file_too_large': 'File exceeds the maximum allowed size (10 MB)',
        'file_type_not_allowed_list': 'File type not allowed. Allowed: {allowed}',
        'file_content_type_missing': 'The file does not say what type it is (the Content-Type header is missing).',
        'file_empty': 'The file is empty.',
        'file_not_webp': 'This file is not a valid WebP image.',
        'import_too_many_rows': 'The file has {count} rows; the limit is {limit}. Split it into smaller files.',
        'storage_location_ambiguous': '"{text}" matches {count} storage locations ({shown}). Name the path instead, for example "{example}".',
        'pagination_cursor_invalid': 'Invalid or expired pagination cursor',
        'webhook_url_scheme': 'Only {schemes} addresses are allowed for webhooks.',
        'webhook_url_no_hostname': 'The webhook address must include a host name, for example https://example.com/hook.',
        'picking_already_picked': '{name} has already been picked',
        'picking_unit_mismatch': (
            'Cannot compare units for {name} — the recipe and the stock use '
            'different measures. Record what one unit of stock weighs or '
            'holds, then scan again.'
        ),
        'picking_picked': '{name} ✓ — taking {quantity}',
        'invalid_mapping_json': 'Invalid mapping JSON',
        'extra_cost_not_a_receipt': 'Extra costs belong on a receipt: only goods coming in can carry the cost of getting them here.',
        'extra_cost_document_posted': (
            'This receipt is already posted, so an extra cost cannot be added to it: the goods may have left the shelf and there is nothing left to charge. Issue a correction to the receipt while its period is open instead.'
        ),
        'extra_cost_currency_mismatch': (
            "The extra cost is in a different currency than the document. Enter it in the document's currency — converting at a rate nobody recorded would put a number in the stock value with no history behind it."
        ),
        'document_shipment_dispatch_only': 'Only a dispatch records a shipment: a carrier takes goods that leave the warehouse.',
        'document_tracking_template_invalid': 'The tracking link for "{carrier}" must be a web address starting with https:// or http:// and containing {{tracking_number}} where the number goes.',
        'packing_not_a_dispatch': 'Only a dispatch is packed: packages hold goods leaving the warehouse.',
        'packing_document_not_open': 'Packages can be changed only while the dispatch is confirmed and not yet completed. A completed dispatch keeps its packages as they were shipped.',
        'packing_exceeds_picked': '{name}: only {remaining} picked and not yet packed. A package holds what was picked, and nothing that is already in another package.',
        'packing_exceeds_done': '{name}: the packages hold {packed}, more than the {done} this dispatch ships. Take the difference out of the packages first, or complete with the quantity they hold.',
        'packing_nothing_to_pack': 'Everything picked is already packed, so there is nothing left for a new package.',
        'packing_no_packages': 'This dispatch has no packages yet, so there is no packing slip to print. Pack it first.',
        'package_not_found': 'Package not found',
        'packing_scan_unrecognized': "No product carries the code {code}. Scan the product's own barcode, or tap its line to pack it.",
        'packing_scan_not_in_document': '{name} is not on this dispatch, so it does not go in its packages.',
        'invalid_image_extension': 'Invalid image extension',
        'invalid_role': 'Invalid role. Allowed: {roles}',
        'role_not_in_organization': 'Role does not belong to this organization',
        'failed_to_read_file': 'Failed to read file: {error}',
        'only_image_files_allowed': 'Only image files are allowed (jpg, png, gif, webp)',
        'image_unreadable': 'This file could not be read as an image',
        'image_too_large': 'Image too large (max {limit})',
        'demo_upload_file_limit': 'The demo accepts files up to {limit}',
        'demo_upload_total_limit': 'The demo has reached its upload limit ({limit}). Uploads open again after the next reset',
        'demo_sandbox_cap_reached': 'The demo has handed out all its copies for today. Please come back tomorrow',
        'demo_sandbox_pool_empty': 'Every demo copy is taken right now and new ones are being prepared. Try again in a minute',
        'barcode_or_sku_required': 'Either barcode or sku query parameter is required',
        'barcode_names_one_record': 'One barcode cannot name {count} records: {barcode}',
        'storage_no_short_code': 'Storage has no short code. Generate one first.',
        'refresh_token_expired_grace': 'Refresh token expired beyond grace period',
        'refresh_token_revoked': 'Refresh token has been revoked',
        'cannot_remove_yourself': 'Cannot remove yourself',
        'cannot_change_own_role': 'Cannot change your own role',
        'label_in_use_by_product': 'Cannot delete a label assigned to an active product. Delete the product first.',
        'label_already_assigned': 'Label already assigned',
        'no_labels_available': 'No labels available for printing',
        'unauthorized': 'Authentication required',
        'forbidden': 'Access denied',
        'organization_required': 'Organization required',
        'not_found': 'Resource not found',
        'conflict': 'Resource conflict',
        'internal_error': 'An internal error occurred',
        'rate_limit_exceeded': 'Too many requests. Try again later.',
        'service_unavailable': 'Service temporarily unavailable',
        'stock_take_edit_completed': 'Cannot edit a completed or cancelled stock take',
        'stock_take_delete_completed': 'Can only delete draft or active stock takes',
        'stock_take_not_active': 'Stock take is not active',
        'stock_take_surplus_item_id_required': 'Choose the product this surplus item is.',
        'stock_take_surplus_quantity_required': 'Enter the counted quantity for this surplus item.',
        'stock_lot_not_found': 'Stock lot not found',
        'stock_moves_export_too_many': '{total} movements match — more than the {limit} one sheet carries. Narrow the dates, the place or the product and export again.',
        'stock_take_close_requires_finalize': 'A stock take is closed by finalising it (POST /stock-takes/{id}/complete), not by a status change',
        'period_already_closed': 'Period {period} is already closed.',
        'period_closed_for_date': 'Period {period} is closed, so nothing can be dated in it. Change the document date, or ask someone who may reopen the period.',
        'period_closed_for_stock_change': 'Period {period} is closed, so no stock can be recorded in it. Ask someone who may reopen the period.',
        'transfer_more_than_the_record_holds': 'The record "{item_name}" holds {available} and the line moves {requested}. Lower the line, or move the rest from another record.',
        'transfer_cannot_split_serialized_record': 'A transfer cannot split the serialized record {serial_number}; transfer the whole record.',
        'use_partially_more_than_left': 'The record "{item_name}" holds {available} of this package and {requested} was given as left. Say how much is left, which cannot be more than there is.',
        'use_partially_serialized': 'The serialized record {serial_number} cannot be opened and split; use it whole.',
        'use_partially_needs_counted_unit': '"{item_name}" is kept in a measured unit, so there is no package to open. Take what you use from the quantity.',
        'use_partially_pack_has_no_measure': '"{item_name}" is counted in packs and the product does not say how much one holds, so only "opened" or "finished" can be recorded.',
        'use_by_needs_open_package': 'The record "{item_name}" is sealed, so it has no use-by to set. Open it first; until then it is judged by the batch\'s date.',
        'period_not_closed': 'Period {period} is not closed.',
        'wms_session_now_held_by': 'This session is now held by {owner}; scans are no longer accepted from here.',
        'wms_session_held_by_other_user': 'Another user has an active session on this document (opened by {owner}).',
        'wms_pick_document_not_found': 'Document {document} was not found in this organization, so the picking session was not started.',
        'wms_pick_document_not_confirmed': 'Document {number} is not confirmed, so the picking session was not started. Only confirmed documents can be picked.',
        'wms_pick_document_not_dispatch': 'Document {number} is not a dispatch, so the picking session was not started. Only dispatches can be picked together.',
        'wms_pick_document_in_session': 'Document {number} is already being picked in another session (opened by {owner}), so the picking session was not started.',
        'wms_line_document_closed': 'Document {number} is {status}, so its lines in this session can no longer be changed.',
        'wms_short_below_scanned': 'The final quantity cannot be below the scanned quantity ({scanned}); to record less, say the count replaces the scans.',
        'wms_short_pick_needs_outcome': 'A line picked short needs a reason: Shortage owes the rest on a backorder, any other reason closes the gap.',
        'wms_session_not_found': 'The active session was not found. It may have been completed or cancelled.',
        'wms_line_not_found': 'The session line was not found.',
        'wms_line_not_pending': 'The session line was not found or is no longer pending.',
        'wms_quantity_cannot_be_negative': 'The quantity cannot be negative.',
        'wms_quantity_above_expected': 'The quantity cannot exceed the expected quantity.',
        'wms_cannot_complete_no_lines': 'The session cannot be completed: it has no lines.',
        'wms_cannot_complete_lines_pending': 'The session cannot be completed: {count} line(s) are still pending.',
        'wms_cannot_complete_destination_not_scanned': 'The session cannot be completed: the destination location has not been scanned yet.',
        'wms_document_not_confirmed': 'The document was not found or is not confirmed.',
        'wms_document_type_not_supported': 'This session does not handle documents of type {document_type}.',
        'wms_nothing_to_undo': 'This line has nothing recorded to undo.',
        'wms_undo_line_is_packed': '{name}: a package already holds {packed} of what was picked. Take it out of the package first, then undo the pick.',
        'wms_skip_line_is_packed': '{name}: a package already holds {packed} of what was picked. Take it out of the package first, then skip the line.',
        'wms_cancel_session_is_packed': '{name}: a package already holds {packed} of what was picked. Take it out of the package first, then cancel the session.',
        'wms_barcode_required': 'Scan a barcode first.',
        'document_execution_line_foreign': 'This execution line does not belong to the document.',
        'document_execution_line_repeated': 'Each document line can be executed only once.',
        'document_done_quantity_negative': 'The done quantity cannot be negative: {quantity}.',
        'document_done_quantity_above_expected': 'The done quantity {quantity} exceeds the expected quantity (max {expected}).',
        'document_held_quantity_negative': 'The held quantity cannot be negative: {quantity}.',
        'document_held_quantity_above_received': 'The held quantity {quantity} exceeds the quantity received ({received}).',
        'document_held_quantity_needs_receipt': 'Only a receipt can hold goods back.',
        'document_held_quantity_needs_code': 'A held quantity needs the code Damage or Quality hold.',
        'document_partial_needs_discrepancy_code': 'A partial execution needs a discrepancy code.',
        'document_correction_above_expected': 'A correction of {quantity} exceeds the expected quantity {expected} in absolute terms.',
        'document_correction_sign_mismatch': 'A correction must keep the sign of the expected difference: {quantity} against {expected}.',
        'document_correction_missing_original': 'This correction does not name the document it corrects.',
        'document_correction_original_not_found': 'The corrected document {document} was not found.',
        'document_correction_would_go_negative': 'The correction would take {item} below zero: current {current}, change {delta}, result {result}.',
        'document_adjustment_would_go_negative': 'The adjustment would take {item} below zero: current {current}, change {delta}, result {result}.',
        'document_line_needs_identity': 'The document line must name a record, a product or a name.',
        'document_rework_wrong_status': 'A document in {status} status cannot be reworked to draft; only a confirmed document or one awaiting approval can.',
        'stock_record_not_found': 'The record {item} was not found.',
        'stock_product_not_found': 'The product {product} was not found.',
        'stock_insufficient_record': 'Insufficient stock for "{item}": available {available}, requested {requested}.',
        'receipt_needs_target_location': 'The receipt document has no target location.',
        'receipt_needs_quarantine_location': 'The receipt includes damaged goods or goods on a quality hold, but the document profile names no quarantine location. Set one in the document settings.',
        'transfer_needs_target_location': 'The transfer document has no target location.',
        'receiving_mode_needs_a_warehouse': 'Only a top-level location chooses how it receives.',
        'putaway_needs_another_location': 'The goods already stand there: choose the location they go to.',
        'replenishment_nothing_to_move': 'There is nothing to carry from reserve: the shelf no longer has the stock, or the pick face no longer needs it.',
        'replenishment_shelf_scan_required': 'Scan the reserve location you are taking the goods from.',
        'replenishment_shelf_scan_mismatch': 'That code names another shelf: scan the reserve location the goods are taken from.',
        'putaway_shelf_scan_required': 'Scan the shelf label before the goods go on it.',
        'home_shelf_receiving': 'A receiving area cannot be a home location: goods only wait there.',
        'home_shelf_quarantine': 'A quarantine location cannot be a home location: goods held back are not kept there.',
        'home_shelf_not_stock': 'This location does not take stock, so it cannot be a home location.',
        'stock_take_status_unchangeable': 'Cannot change status from {current} to {new}.',
        'api_keys_limit_reached': 'The organization already has {count} active API keys, which is the maximum. Revoke one to create another.',
        'document_pdf_requires_confirmed': 'A PDF is produced from a confirmed or completed document. This one is {status}.',
        'documents_pdf_require_confirmed': 'A merged PDF is produced from confirmed or completed documents only. Not printable: {numbers}.',
        'stock_take_item_not_found': 'Stock take item not found',
        'stock_take_item_already_exists': 'Item already added to this stock take',
        'stock_take_item_outside_location': 'This item is stored outside the location being counted; counting it here would overwrite the quantity it has there',
        'stock_take_shelf_outside_location': 'This location is not part of the count of {location}',
        'stock_take_uncounted_items': '{count} uncounted items remaining',
        'stock_none_at_location': 'There is no {product} at {location}.',
        'stock_all_batches_held': 'Every batch of {product} at {location} is quarantined or on hold, so none of it can be used.',
        'stock_not_enough': '{location} has {available} of {product} available and {requested} was asked for.',
        'stock_take_over_cap': '{count} counted quantity(ies) are far above the system stock. Review them, then confirm to save the counted numbers.',
        'stock_take_over_tolerance': "{count} counted quantity(ies) differ from the system stock by more than this stock take's tolerance. Someone who may accept them has to say so before they are posted.",
        'stock_take_tolerance_reason_missing': '{count} counted quantity(ies) differ by more than the tolerance and do not say why. Give each one a reason, then finish the count.',
        'stock_take_tolerance_not_allowed': 'Accepting a difference beyond the tolerance needs the stock take approval permission.',
        'stock_take_awaiting_recount': '{count} row(s) were sent back to be counted again. Count them, then finish the stock take.',
        'stock_take_stock_moved': '{count} row(s) were counted against a quantity the stock no longer has. They have been sent back to be counted again.',
        'document_not_found': 'Document not found',
        'work_item_not_found': 'Task not found',
        'work_item_taken': 'Someone else has just taken this task.',
        'pdf_generation_failed': 'PDF generation failed',
        'import_only_draft': 'Can only import lines to DRAFT documents',
        'paste_empty': 'No rows to import — paste at least a header row and one data row',
        'import_asset_name_missing': 'Missing asset name',
        'import_line_name_missing': 'Missing product name',
        'import_location_unresolved': 'Could not resolve storage location',
        'import_location_not_found': 'No location is named “{value}”',
        'import_price_invalid': 'Column "{column}": "{value}" is not a price',
        'import_date_invalid': 'Column "{column}": "{value}" is not a date',
        'import_job_failed': 'The import stopped because of an unexpected error.',
        'import_job_interrupted': 'The import was interrupted before it finished.',
        'import_column_not_a_number': 'Column "{column}": "{value}" is not a number',
        'import_quantity_not_positive': 'Column "{column}": the quantity has to be greater than zero, "{value}" is not',
        'import_column_location_not_found': 'Column "{column}": location "{value}" not found',
        'import_column_category_not_found': 'Column "{column}": category "{value}" not found',
        'import_unknown_unit': 'Column "{column}": unknown unit "{value}". Known units: {units}',
        'import_column_not_yes_no': 'Column "{column}": "{value}" is not yes or no',
        'import_column_not_in_options': 'Column "{column}": "{value}" is not one of the choices: {options}',
        'import_column_quantity_blank': 'Column "{column}": the quantity is empty. Fill it in, or clear the quantity mapping to import every row as 1',
        'import_column_field_shape': 'Column "{column}": the value does not fit the field the column is mapped to',
        'import_field_required_unreadable': 'Field "{field}" is required and cannot be read from a cell',
        'import_field_required_no_column': 'Field "{field}" is required and the sheet has no column for it',
        'import_column_field_required': 'Column "{column}": the field is required',
        'import_column_reason': 'Column "{column}": {reason}',
        'import_row_failed': 'The row could not be imported',
        'document_lines_quantity_not_positive': 'Lines {lines} have a quantity of zero or less. Correct them before confirming.',
        'document_delivery_lines_reference_items': 'Delivery document lines must reference existing items',
        'document_scrap_lines_reference_items': 'Scrap document lines must reference existing items',
        'document_reason_scrap_only': 'Only a scrap document can carry a scrapping reason',
        'document_scrap_reason_required': 'A scrap document says why the goods are written off: choose a reason, and with Other write it in the notes',
        'document_transfer_lines_reference_items': 'Transfer document lines must reference existing items',
        'document_correction_lines_reference_items': 'Correction document lines must reference existing items',
        'document_adjustment_lines_reference_items': 'Adjustment document lines must reference existing items',
        'recipe_collection_name_taken': 'A recipe collection named "{name}" already exists in this organisation.',
        'recipe_name_taken': 'A BOM with this name already exists for this product.',
        'recipe_not_found': 'Recipe not found',
        'picking_active_recipe_locked': 'Ingredients cannot be edited while a picking session is active. Cancel or complete the session first.',
        'meal_plan_dates_exclude_entries': 'Remove the entries on the excluded dates first.',
        'meal_plan_position_taken': 'Could not find a free position in that meal.',
        'meal_plan_entry_date_out_of_range': "The entry date is outside the plan's date range.",
        'meal_plan_slot_not_enabled': 'That meal is not enabled for this plan.',
        'shopping_exclusion_exists': 'This exclusion already exists.',
        'shopping_item_already_purchased': 'This item is already marked as purchased.',
        'shopping_item_already_purchased_reset': 'This item is already marked as purchased. Mark it as not purchased first to change it.',
        'shopping_list_not_editable': 'A completed or archived shopping list cannot be edited.',
        'shopping_lists_module_disabled': 'The shopping lists module is not enabled for this organisation.',
        'maker_recipe_not_found': 'BOM not found',
        'uom_quantity_non_negative': 'Quantity must be non-negative',
        'uom_conversion_unavailable': (
            'Quantity in {unit} cannot be converted to the stock unit {stock_unit}'
        ),
        'webhook_not_found': 'Webhook not found',
        'putaway_rule_not_found': 'Putaway rule not found',
        'document_line_not_found': 'Document line not found',
        'putaway_unknown_context_tag': "Unknown category group '{value}' — choose one that an existing category defines",
        'putaway_unknown_storage_type': "Unknown storage type '{value}' — choose one of the organization's storage types",
        'location_not_internal': "'{name}' is a virtual location — goods can only be put away in real storage locations",
        'location_archived': "'{name}' is archived — restore it first, or choose a location the lists still show",
        'line_target_receipt_only': 'A destination can be named on receipt lines only — dispatch and transfer lines take their shelves from the document',
        'line_target_already_received': 'This line was already received in the open receiving session; its goods stay on the shelf they were received to',
        'exclusion_not_found': 'Exclusion not found',
        'tag_not_found': "Tag '{tag}' not found in any recipe",
        'meal_plan_not_found': 'Meal plan not found',
        'meal_plan_entry_not_found': 'Meal plan entry not found',
        'meal_plan_slot_conflict': 'Entries exist in disabled slots: {slots}',
        'attachment_not_found': 'Attachment not found',
        'api_key_not_found': 'API key not found',
        'invalid_api_key': 'Invalid or expired API key',
        'api_key_unknown': 'No API key matches this value — check it for typos',
        'api_key_expired': 'This API key has expired — issue a new one',
        'api_key_revoked': 'This API key was revoked — issue a new one',
        'api_key_owner_inactive': 'The account this API key belongs to is inactive.',
        'unit_conversion_already_exists': 'A conversion from {unit} for "{ingredient}" already exists in this organisation. Edit it instead.',
        'conversion_not_found': 'Conversion not found',
        'conversion_not_found_or_system': 'Conversion not found or is a system default',
        'template_not_found': 'Template not found',
        'template_import_not_json': 'The file could not be read as a template export — it is not valid JSON.',
        'template_import_wrong_kind': 'This file is not an exported document template.',
        'template_import_wrong_version': 'The file was exported in format version {version}; this installation reads version {supported}.',
        'template_import_invalid_field': 'The field "{field}" is missing or is not valid.',
        'template_import_unknown_placeholders': 'The template references fields that do not exist: {placeholders}.',
        'template_import_not_renderable': 'The template could not be rendered: {detail}',
        'model_not_found': 'Equipment model not found',
        'widget_not_found': 'Widget not found',
        'bom_line_not_found': 'BOM line not found',
        'bom_line_already_exists': (
            'This BOM already lists that ingredient — a BOM line between the '
            'two products already exists.'
        ),
        'bom_depth_exceeded': (
            'This BOM is nested more than {max_depth} levels deep — too deep to '
            'resolve.'
        ),
        'cost_line_not_found': 'Cost line not found',
        'production_order_not_found': 'Production order not found',
        'production_no_recipe': ('No BOM for this product — create a BOM first'),
        'production_recipe_not_found': (
            'BOM {recipe_id} not found in this organization'
        ),
        'production_recipe_product_mismatch': (
            'This BOM does not belong to this product'
        ),
        'production_complete_not_draft': (
            'This production order already has status {status} — only a draft '
            'can be completed.'
        ),
        'production_reverse_not_completed': (
            'This production run is {status}, so there is nothing to take back — only a completed run can be undone.'
        ),
        'production_reverse_output_used': (
            'This run cannot be undone: some of what it made has already left its location. Record a stock correction for what is left instead.'
        ),
        'production_cancel_not_draft': (
            'This production order already has status {status} — only a draft '
            'can be cancelled.'
        ),
        'production_update_not_draft': (
            'This production order already has status {status} — only a draft '
            'can be edited.'
        ),
        'production_actual_qty_must_be_positive': (
            'The produced quantity must be greater than zero.'
        ),
        'production_overproduction_disabled': (
            'Overproduction is disabled in settings — this order cannot produce '
            'more than planned.'
        ),
        'production_ingredient_unmeasurable': (
            "An ingredient's unit cannot be compared with its stock, so what to "
            "take off the shelf for it is unknown — fix the BOM line's unit first."
        ),
        'production_short_of_stock': 'Not enough ingredients in stock for this production order.',
        'output_template_not_found': 'Output template not found',
        'purchase_order_not_found': 'Purchase order not found',
        'reorder_rule_not_found': 'Reorder rule not found',
        'pricelist_entry_not_found': 'Pricelist entry not found',
        'reorder_max_below_min': 'max_quantity ({max_quantity}) must be >= min_quantity ({min_quantity})',
        'reorder_safety_stock_negative': 'safety_stock must be >= 0, got {safety_stock}',
        'reorder_min_quantity_negative': 'min_quantity must be >= 0, got {min_quantity}',
        'pricelist_unit_price_not_positive': 'unit_price must be > 0, got {unit_price}',
        'pricelist_min_quantity_not_positive': 'min_quantity must be > 0, got {min_quantity}',
        'pricelist_valid_to_before_valid_from': 'valid_to ({valid_to}) must be >= valid_from ({valid_from})',
        'pricelist_duplicate': (
            'This supplier already has a price for this product over the same '
            'dates and the same minimum quantity. Edit that entry instead of '
            'adding a second one.'
        ),
        'tax_rate_not_found': 'Tax rate not found',
        'announcement_not_found': 'Announcement not found',
        'approval_request_not_found': 'Approval request not found',
        'cycle_count_schedule_not_found': 'Cycle count schedule not found',
        'document_type_config_not_found': 'Document type configuration not found',
        'history_entry_not_found': 'History entry not found',
        'ingredient_not_found': 'Ingredient not found',
        'label_not_found': 'Label not found',
        'scan_unrecognized': 'Code not recognized — no product, label, location or document matches it',
        'member_not_found': 'Member not found',
        'module_not_found': 'Module not found',
        'notification_not_found': 'Notification not found',
        'partner_not_found': 'Partner not found',
        'partner_name_exists': 'Partner with name "{name}" and type "{partner_type}" already exists.',
        'partner_code_exists': 'Partner with code "{code}" already exists.',
        'partner_delete_open_purchase_orders': 'Cannot delete partner: {count} open purchase order(s) reference this partner',
        'partner_import_name_missing': 'Missing partner name',
        'partner_import_duplicate': 'Duplicate partner: "{twin}" already has this name or tax id',
        'product_not_found': 'Product not found',
        'product_template_not_found': 'Product template not found',
        'profile_not_found': 'Profile not found',
        'receiving_session_not_found': 'Receiving session not found',
        'request_not_found': 'Request not found',
        'workflow_not_found': 'Workflow not found',
        'campaign_not_found': 'Campaign not found',
        'attestation_no_active_assignments': 'No active assignments found for the configured scope',
        'attestation_not_draft': 'This campaign is already {status} — only a draft can be launched',
        'attestation_reminders_not_active': 'Reminders can only be sent for a campaign that is running',
        'campaign_deadline_past': 'Campaign deadline must be today or later',
        'attestation_complete_not_allowed': 'A campaign that is {status} cannot be completed',
        'attestation_scope_exceeds_limit': 'The scope covers more than {limit} items. Narrow it, or split the attestation into smaller ones.',
        'assignment_not_found': 'Assignment not found',
        'maintenance_log_not_found': 'Maintenance log not found',
        'equipment_cannot_checkout_retired': 'Cannot check out a retired asset',
        'equipment_cannot_checkout_in_maintenance': 'Cannot check out an asset that is in maintenance; set it to Available first',
        'equipment_assignment_needs_person_or_location': 'Name the person receiving the asset or the location it is deployed to, not both',
        'equipment_bulk_scope_too_large': '{matched} assets match the filters; one action can cover at most {limit}. Narrow the filters.',
        'equipment_assignment_already_active': 'Item already has an active assignment',
        'equipment_assignment_already_checked_in': 'Assignment already checked in',
        'api_key_cannot_manage': 'API keys cannot manage other API keys',
        'api_key_cannot_create': 'API keys cannot create other API keys',
        'api_key_cannot_revoke': 'API keys cannot revoke other API keys',
        'api_key_scope_refused': 'This API key is limited to {scope} and cannot be used here',
        'api_key_scope_unknown': 'There is no API key scope called "{scope}"',
        'api_key_permission_not_grantable': 'An API key cannot be given {permission}: you do not hold it, or no key carries it',
        'api_key_permission_outside_scope': 'The permission {permission} is not part of the scopes chosen for this key',
        'print_no_agent': 'No printer is connected. Start the Inventari Print Agent next to the printer.',
        'print_choose_agent': 'Several printers are connected. Choose the one to print on.',
        'print_agent_protocol_missing': 'This agent says nothing about the print protocol it speaks: it is older than the versioned protocol. Update the print agent.',
        'print_agent_protocol_unsupported': 'This agent speaks print protocol {agent}; this server speaks print protocol {server}. Update whichever is older.',
        'print_agent_not_found': 'Printer not found',
        'print_job_not_found': 'Print job not found',
        'print_job_nothing_to_print': 'Nothing to print: none of the chosen labels was found',
        'product_label_no_code': 'Nothing to print: none of the chosen products has a code. Generate one on the product form',
        'product_label_too_narrow': 'The code {code} does not fit a label {width} mm wide: its bars need one at least {needed} mm wide. Choose a wider label size',
        'product_label_too_short': 'The label {height} mm tall is too short: after the name and the text, the bars of the code {code} are left too little height for a scanner to read. Choose a taller label size',
        'storage_code_template_invalid': "The code template '{template}' cannot be used. Write placeholders such as {{zone}}-{{rack:02}}-{{level:02}}, with a separator between them, or a prefix of up to five letters and digits such as LOC",
        'storage_code_template_not_tree': 'This warehouse draws random codes: give it a template with placeholders, such as {zone}-{rack:02}-{level:02}, before numbering its locations',
        'storage_code_parent_not_numbered': 'This location cannot be numbered on its own: the places above it do not carry their template codes yet, or it is deeper than the template goes. Number the level above it first',
        'storage_code_number_not_here': 'Only an ordinary location can be numbered, not an archived or virtual one',
        'storage_code_template_not_warehouse': 'A code template belongs to a warehouse, a location at the top of the tree',
        'print_job_not_claimed': 'This print job is not being printed by this printer',
        'print_job_not_retryable': 'Only a failed print job can be sent again',
        'print_job_one_target': 'Send exactly one kind of label: pool labels by id, pool labels by code, or storage locations.',
        'webhook_admin_only': 'Only admins can manage webhooks',
        'approvals_manage_admin_only': 'Only admins and managers can modify approval workflows',
        'approvals_action_admin_only': 'You do not have permission to approve or reject requests',
        'approvals_read_forbidden': 'You do not have permission to view approval requests',
        'approvals_write_forbidden': 'You do not have permission to raise approval requests',
        'documents_approve_requires_grant': 'You do not have permission to approve or reject documents',
        'po_approval_workflow_missing': 'This purchase order needs an approval, but nobody has been set up to give it yet. Ask your administrator to set it up.',
        'po_supplier_required': 'A purchase order cannot be confirmed without a supplier',
        'document_type_requires_partner': 'This document type requires a partner.',
        'partner_has_no_email': 'The partner has no email address.',
        'po_has_no_partner': 'This purchase order has no supplier to send it to.',
        'approval_no_active_workflow': 'No active approval workflow is configured for this action.',
        'po_no_pending_approval_request': 'There is no pending approval request for this purchase order.',
        'po_request_approval_invalid_status': 'This purchase order can no longer be sent for approval.',
        'po_approve_invalid_status': 'Only a purchase order awaiting approval can be approved.',
        'approval_cannot_approve_own_request': 'You cannot approve your own request.',
        'approval_cannot_reject_own_request': 'You cannot reject your own request.',
        'approval_approve_invalid_status': 'Only a request awaiting a decision can be approved.',
        'approval_reject_invalid_status': 'Only a request awaiting a decision can be rejected.',
        'approval_cancel_invalid_status': 'Only an open request can be withdrawn.',
        'approval_decision_already_taken': 'Someone else has already decided on this request.',
        'approval_not_stage_approver': 'You are not an approver for this stage.',
        'approval_only_requester_can_cancel': 'Only the person who raised the request can withdraw it.',
        'approval_workflow_inactive': 'The approval workflow behind this request is no longer active.',
        'approval_target_not_found': 'This record does not exist, so no approval can be requested for it.',
        'approval_request_already_open': 'An approval request is already open for this record.',
        'approval_workflow_no_stages': 'This approval workflow has no stages configured.',
        'approval_workflow_needs_stage': 'An approval workflow needs at least one stage.',
        'approval_workflow_modify_blocked': 'This workflow cannot be changed while requests are waiting on it ({count}: {documents}). The person who raised a request can withdraw it, and an approver can decide it — settle them first.',
        'approval_workflow_delete_blocked': 'This workflow cannot be deleted while requests are waiting on it ({count}: {documents}). The person who raised a request can withdraw it, and an approver can decide it — settle them first.',
        'approval_workflow_archived': 'This workflow was deleted and is archived: its requests still show the stages they went through, so it cannot be changed or switched on again. Create a new workflow in its place.',
        'approval_unknown_approvers': 'Some of the selected approvers do not belong to this organization.',
        'approval_unknown_requesters': 'Some of the selected people or roles do not belong to this organization.',
        'approval_requester_scope_everyone_with_names': 'A workflow that holds everyone names no people or roles.',
        'approval_requester_scope_names_nobody': 'Choose at least one person or role, or everyone.',
        'approval_stage_unsolvable': 'Stage "{label}" could never be decided: none of its named approvers can see approvals. Add at least one approver who has approvals access.',
        'approval_scope_changed': 'What this workflow would hold has changed since you opened this — read it again, and switch the workflow on if it is still what you want.',
        'approval_scope_required': 'Switching a workflow on needs the scope it will hold, as shown to you — send "expected_scope", or the workflow stays off.',
        'approval_stage_open_unsolvable': 'Stage "{label}" waits for anyone holding the approvals approve permission, and nobody in this organization holds it — no request would ever be decided. Grant it to somebody, or name an approver.',
        'approval_required_first': 'This action needs an approval first. Request one before continuing.',
        'approval_workflow_required_but_missing': 'This needs an approval, but no active approval workflow exists for it. Create one, or drop the requirement.',
        'approval_required_after_rejection': 'The approval for this action was rejected. Request a new one before continuing.',
        'approval_granted_for_another_holder': 'The approval was granted for a checkout to {holder}. Request one for this checkout.',
        'document_no_pending_approval_request': 'There is no pending approval request for this document.',
        'document_request_approval_invalid_status': 'Only a confirmed document can be sent for approval.',
        'po_confirm_invalid_status': 'This purchase order cannot be confirmed in its current state.',
        'po_email_invalid_status': 'Cannot send email for a purchase order in status {status}. Only CONFIRMED or COMPLETED are allowed.',
        'po_email_invalid_address': 'Invalid partner email address: {email}',
        'po_partner_inactive': 'Cannot confirm the purchase order: partner "{name}" is inactive',
        'po_partner_not_supplier': 'Cannot confirm the purchase order: partner "{name}" has type "{partner_type}", which is not a supplier type',
        'po_approval_race_condition': 'The approval request could not be created — it may have been handled by another action. Try again.',
        'po_already_cancelled': 'This purchase order is already cancelled',
        'po_cancel_completed': 'Cannot cancel a completed purchase order',
        'po_cancel_received_quantities': 'Cannot cancel this purchase order because quantities have been received — cancel the linked receipts first',
        'po_cancel_open_receipts': 'Cannot cancel this purchase order while receipts are open — complete or cancel them first: {numbers}',
        'po_receipt_requires_confirmed': 'Only CONFIRMED purchase orders can create a receipt',
        'po_line_not_found': 'Purchase order line {po_line_id} not found',
        'po_receive_quantity_exceeds': 'Quantity {quantity} exceeds the remaining {remaining} for line {line}',
        'po_line_product_template_not_found': 'Product template {template_id} not found',
        'po_update_not_draft': 'Only DRAFT purchase orders can be updated',
        'po_lines_received': (
            'Cannot update lines: some items have already been received. Cancel '
            'the linked receipt documents first.'
        ),
        'po_import_not_draft': 'Can only import lines to DRAFT purchase orders',
        'document_insufficient_stock': 'Insufficient stock to confirm: {quantity} of {needed} could not be reserved',
        'document_zone_split_needs_stock_unit': 'The line for "{item_name}" is written in a unit other than the product\'s stock unit and cannot be split over several shelves — write it in the stock unit, or take it from one shelf',
        'document_record_stands_elsewhere': 'The record "{item_name}" stands on "{record_shelf}", but the document takes from "{document_shelf}" — point the document at the shelf the record stands on, or move the record first',
        'document_insufficient_stock_record_elsewhere': 'Insufficient stock to confirm: {quantity} of {needed} could not be reserved on "{document_shelf}"; the record "{item_name}" stands on "{record_shelf}" — point the document at that shelf, or move the record first',
        'stock_would_go_negative': 'That would leave stock below zero. Something else has moved these goods in the meantime — reload and try again.',
        'stock_reserved_over_quantity': 'That would hold more of these goods than are on the shelf. Release a reservation, or count the shelf again.',
        'document_exceeds_order_line': 'This would receive {quantity} against an order line with only {remaining} left — past the {tolerance}% over-receipt tolerance it needs someone who may receive over tolerance',
        'over_receipt_needs_permission': 'Receiving {quantity} goes past the {tolerance}% over-receipt tolerance — this needs someone who may receive over tolerance',
        'over_receipt_confirm_surplus': '{product}: receiving {quantity} is {surplus} more than the {basis} expected. Receive the surplus?',
        'over_receipt_confirm_order_surplus': '{product}: receiving {quantity} is {surplus} more than the {basis} left on order {order}, line {line}. Receive the surplus?',
        'over_receipt_past_ceiling': 'Receiving {quantity} against {basis} goes past the {ceiling}% over-receipt ceiling — nobody may receive that much',
        'document_update_status': 'Only DRAFT documents can be updated',
        'document_correction_locked': 'Correction documents are locked — only notes can be changed. Attempted to change: {fields}. Cancel and create a new correction if the data is wrong.',
        'field_cannot_be_cleared': 'These fields cannot be cleared: {fields}.',
        'ingredient_defaults_unreadable_file': 'The file could not be read. The import expects a .json or .csv file with one row per ingredient.',
        'onboarding_modules_not_offered': "The profile '{profile}' does not offer these modules: {modules}",
        'location_chain_step_incomplete': 'Each step of a location chain needs an id or a name.',
        'current_password_incorrect': 'Current password is incorrect',
        'storage_own_parent': 'A location cannot be its own parent.',
        'storage_short_code_in_use': "Short code '{short_code}' is already in use by another location.",
        'storage_would_cycle': 'Moving this storage location under its own descendant would create a cycle in the location hierarchy.',
        'template_not_builtin_copy': 'This template was not copied from a built-in layout',
        'smtp_config_invalid': 'The email server settings are not valid: {reason}',
        'module_needs_newer_platform': "Module '{module}' requires Inventari {required} or newer; this is version {current}.",
        'document_delete_status': 'Only DRAFT documents can be deleted',
        'document_wms_picking_active': 'This document cannot be completed or cancelled while {sessions} active WMS picking session(s) are in progress. Complete or cancel them first.',
        'document_wms_receiving_active': 'This document cannot be completed or cancelled while {sessions} active WMS receiving session(s) are in progress. Complete or cancel them first.',
        'document_confirm_invalid_status': 'Cannot confirm a document in {status} status',
        'document_lines_need_stock_row': 'A document of type {type} takes goods off a shelf, so every line has to name the stock it takes them from — lines {lines} name only a product',
        'document_lines_need_stock_row_one': 'A document of type {type} takes goods off a shelf, so every line has to name the stock it takes them from — line {lines} names only a product',
        'document_receipt_lines_need_product': 'Lines {lines} name no product from your list, and a receipt puts only products into stock — pick each one from the list or add it as a new product',
        'document_receipt_lines_need_product_one': 'Line {lines} names no product from your list, and a receipt puts only products into stock — pick it from the list or add it as a new product',
        'document_partner_tax_id_required': 'Partner "{name}" has no tax ID, and this organization\'s documents require one to confirm. Add the tax ID on the partner, mark the partner as a private person (consumer), or turn off "Require partner tax ID" in Document settings.',
        'document_complete_invalid_status': 'Cannot complete a document in {status} status',
        'document_complete_unanswered_lines': 'Completing without an answer for every line would book the unanswered ones as delivered in full. Unanswered lines: {lines}. Send their quantities, or set complete_as_planned=true to book them as planned',
        'document_complete_skipped_lines': 'Completing would book the skipped lines as picked or received in full, with nobody having said what became of them. Skipped lines: {lines}. Put each one back on the list, or answer it as short with a reason, before completing — complete_as_planned does not cover them',
        'document_receipt_lines_need_expiry': 'A product taken by earliest expiry cannot be received without an expiry date, or it would sort behind every dated record. Lines: {lines}. Send the lot and expiry with the completion, or put the date on the line',
        'picking_lot_no_longer_available': 'Cannot close picking: lot {lot} can no longer give the {quantity} units picked from it',
        'document_active_approval_request': 'An active approval request exists for this document',
        'document_cancel_invalid_status': 'Only DRAFT, PENDING_APPROVAL or CONFIRMED documents can be cancelled',
        'document_fields_closed': "A completed or cancelled document's fields can no longer change",
        'approval_workflow_not_found': 'Approval workflow not found',
        'po_pdf_invalid_status': 'PDF can only be generated for CONFIRMED or COMPLETED purchase orders. Current status: {status}',
        'po_pdf_generation_failed': 'PDF generation failed',
        'email_delivery_failed': 'Email could not be sent — SMTP may not be configured',
        'invalid_partner_type': 'This partner type is not recognized.',
        'invalid_country_code': 'Country must be a two-letter ISO 3166-1 alpha-2 code (e.g. PL).',
        'invalid_print_page_size': 'Paper size must be A4 or Letter.',
        'invalid_timezone': 'Timezone must be a valid IANA zone name (e.g. Europe/Warsaw).',
        'invalid_currency_code': 'Currency must be a valid ISO 4217 code (e.g. PLN).',
        'admin_permissions_required': 'Admin permissions required for this action',
        'invalid_url_missing_host': 'Invalid URL: missing host',
        'url_must_be_public': 'URL must point to a public host',
        'invalid_url_scheme': 'Invalid URL: must start with http:// or https://',
        'rating_must_be_1_to_5': 'Rating must be between 1 and 5',
        'no_missing_ingredients': 'No missing ingredients to add',
        'picking_session_not_found': 'Picking session not found',
        'barcode_or_item_id_required': 'barcode or item_id required',
        'ingredient_not_found_or_not_picked': 'Ingredient not found or not yet picked',
        'no_valid_images': 'No valid images provided',
        'file_must_be_image': 'File must be an image',
        'vision_file_too_large': 'File is too large',
        'vision_unsupported_image_type': 'The file "{filename}" is not an accepted image type ({content_type}). Accepted: {accepted}.',
        'llm_provider_unreachable': (
            'Could not reach the AI provider behind connection "{name}" '
            '(model "{model}"). Check the address and whether the service is '
            'up in Settings → AI Connections.'
        ),
        'llm_provider_unreachable_generic': (
            'Could not reach the AI provider. Check the connection address and '
            'whether the service is up in Settings → AI Connections.'
        ),
        'llm_provider_timeout': (
            'Connection "{name}" (model "{model}") did not answer in time. The '
            'provider was reached — a model running on your own machine may '
            'simply need longer (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) or a '
            'smaller context window.'
        ),
        'llm_provider_timeout_generic': (
            'The AI provider did not answer in time. It was reached — a model '
            'running on your own machine may simply need longer '
            '(LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) or a smaller context window.'
        ),
        'llm_provider_key_rejected': (
            'The AI provider behind connection "{name}" (model "{model}") '
            'rejected the API key. Check the key in Settings → AI Connections.'
        ),
        'llm_provider_key_rejected_generic': (
            'The AI provider rejected the API key. Check the key in Settings → AI '
            'Connections.'
        ),
        'llm_provider_limit': (
            'Connection "{name}" (model "{model}") was refused by the AI '
            'provider: the plan limit or the account balance is spent. Check the '
            'plan or try again later.'
        ),
        'llm_provider_limit_generic': (
            'The AI provider refused: the plan limit or the account balance is '
            'spent. Check the plan or try again later.'
        ),
        'llm_provider_model_unknown': (
            'The AI provider behind connection "{name}" does not know the model '
            '"{model}". Check the model name in Settings → AI Connections.'
        ),
        'llm_provider_model_unknown_generic': (
            'The AI provider does not know the configured model. Check the model '
            'name in Settings → AI Connections.'
        ),
        'llm_purpose_unbound': (
            'No AI connection has been chosen for this feature yet. Choose '
            'one in Settings → AI Connections.'
        ),
        'llm_connection_test_failed': (
            'The connection test could not be completed. Check the address and '
            'try again.'
        ),
        'llm_base_url_unresolved': (
            'AI connection base URL hostname "{host}" could not be resolved — '
            'check the spelling, a typo here reads as an unreachable provider. '
            'If the address is spelled right, ask whoever runs that server '
            'whether the name is published in DNS.'
        ),
        'llm_base_url_loopback': 'AI connection base URL targets a loopback hostname ({host}). External URLs only — ask whoever runs this installation to allow a local model server (the LLM_ALLOW_PRIVATE_NETWORKS setting).',
        'llm_base_url_private': 'AI connection base URL targets a private or internal address ({host}). External URLs only — ask whoever runs this installation to allow a local model server (the LLM_ALLOW_PRIVATE_NETWORKS setting).',
        'llm_base_url_scheme': 'AI connection base URL must use http or https.',
        'llm_base_url_required_for_http_provider': (
            'This provider is reached over HTTP, so the base URL is '
            'required — for example https://openrouter.ai/api/v1'
        ),
        'llm_base_url_no_hostname': ('AI connection base URL must include a hostname.'),
        'llm_base_url_refused': (
            'AI connection base URL was refused. External URLs only — Set '
            'LLM_ALLOW_PRIVATE_NETWORKS=true on self-hosted installs to allow '
            'a local model server.'
        ),
        'vision_model_returned_nothing': (
            'Connection "{name}" (model "{model}") returned no content. Check '
            'that the model reads images and that its token budget is large '
            'enough — the photo is not the problem here.'
        ),
        'vision_model_returned_nothing_generic': (
            'The model returned no content. Check in Settings → AI Connections '
            'that it reads images at all.'
        ),
        'vision_label_not_understood': (
            'The AI could not read this label using connection "{name}" '
            '(model "{model}"). Try a clearer photo, or choose a different '
            'connection in Settings → AI Connections.'
        ),
        'vision_nutrition_not_understood': (
            'The AI could not read this nutrition table using connection '
            '"{name}" (model "{model}"). Try a clearer photo, or choose a '
            'different connection in Settings → AI Connections.'
        ),
        'vision_label_not_understood_generic': (
            'The AI could not read this label. Try a clearer photo, or a different model in AI Connections.'
        ),
        'vision_nutrition_not_understood_generic': (
            'The AI could not read this nutrition table. Try a clearer photo, or a different model in AI Connections.'
        ),
        'vision_ai_not_configured': (
            'No AI connection has been chosen for image recognition yet. Choose one in Settings → AI Connections.'
        ),
        'invalid_organization_id': 'Invalid organization ID',
        'user_has_no_organization': 'User has no organization',
        'unsupported_import_format': 'Unsupported import format: {format}',
        'unsupported_export_format': 'Unsupported export format: {format}',
        'equipment_default_checkout_template': 'Default checkout protocol',
        'equipment_default_checkin_template': 'Default return protocol',
        'purchase_order_standard_template': 'Standard purchase order',
        'attestation_not_found': 'Attestation link not found',
        'attestation_expired': 'Attestation link has expired',
        'attestation_refused': 'This attestation link cannot accept this action. Ask the organisation that sent it for a new link.',
        'campaign_closed': 'This attestation campaign has been closed — your confirmation can no longer be recorded. If you still hold the equipment, please contact your organisation.',
        'assignment_already_returned': 'This equipment has already been confirmed as returned — no further confirmation is needed.',
        'equipment_bulk_item_failed': ('This asset could not be changed.'),
        'unknown_bulk_action': 'Unknown bulk action: {action}',
        'item_unit_change_blocked_by_stock': (
            'This record holds {quantity} {current_unit}. Changing the unit to '
            '{new_unit} would relabel that number without changing what is on '
            'the shelf. Use it up or write it off first, or record the new unit '
            'on a separate record.'
        ),
        'item_unit_differs_from_template_confirmation_required': (
            '{product} is kept in {template_unit}, and this quantity is given '
            'in {chosen_unit}. It will be converted into {template_unit} when '
            'saved, so confirm that {chosen_unit} is the unit you meant, or '
            'enter the quantity in {template_unit}.'
        ),
        'item_unit_not_convertible_to_card': (
            '{product} is kept in {template_unit}, and a quantity in '
            '{chosen_unit} cannot be converted into it. Enter the quantity in '
            '{template_unit} — or, for pieces, record on the product how much '
            'one piece weighs or holds.'
        ),
        'bom_line_unit_not_convertible': (
            'This ingredient is kept in {stock_unit}, and {line_unit} cannot be '
            'read as {stock_unit}. Use a unit of the same kind, or record what '
            'one {stock_unit} weighs or holds on the product.'
        ),
        'bom_line_self_reference': (
            'A BOM line cannot reference the product itself — it would make '
            'the product an ingredient of its own BOM.'
        ),
        'bom_line_cycle': (
            'This line would close a cycle: the product would become an '
            'ingredient of its own BOM.'
        ),
        'uom_quantity_requires_whole_number': (
            'The unit {unit} takes whole numbers only, so {quantity} cannot '
            'be saved. Round the quantity to a whole number.'
        ),
        'uom_quantity_too_many_decimal_places': (
            'The unit {unit} takes at most {places} decimal place(s), so '
            '{quantity} cannot be saved. Round the quantity to that '
            'precision.'
        ),
        'item_unit_cannot_be_removed': (
            'The unit {unit} cannot be removed: a quantity without a unit says '
            'nothing. Choose another unit instead.'
        ),
        'removal_strategy_of_shared_product': (
            'This product comes from the shared catalogue, so the order '
            "its stock leaves in is the catalogue's and cannot be changed "
            'for one organization.'
        ),
        'piece_unit_missing_from_catalogue': (
            "This installation's unit catalogue has no piece unit, so "
            "'a quantity of what' has no answer. Name a unit explicitly, or "
            'restore the standard unit catalogue.'
        ),
        'stock_as_of_no_history': (
            'This organization records no stock movements, so it has no '
            'history to report on. Today’s stock levels are the only '
            'answer it can give.'
        ),
        'stock_as_of_before_ledger': (
            'The movement ledger starts on {starts_at}. Nothing is known '
            'before that — not zero — so a report for {as_of} would '
            'be a guess.'
        ),
        'stock_as_of_pdf_too_many': (
            'This report has {total} products — more than the {limit} rows '
            'a printout carries. Export it as a spreadsheet instead, or pick '
            'one location to narrow it.'
        ),
        'equipment_still_assigned': (
            'The asset is still checked out to someone. Check it in first.'
        ),
        'equipment_deploy_requires_checkout': (
            'An asset becomes deployed by checking it out to someone. '
            'Check it out instead of setting the status.'
        ),
        'equipment_status_invalid': 'Invalid status: {status}',
        'equipment_status_transition_denied': 'Cannot change status from {old} to {new}',
        'equipment_status_transition_from_retired': 'Cannot change status from {old} to {new}. Retired assets must be explicitly unretired first.',
        'attestation_assignment_required': 'Select the asset you are reporting a problem with',
        'meta_data_spelled_twice': (
            "'meta_data' and 'metadata' name one field spelled twice. Send one of them."
        ),
        'ai_connection_not_found': 'AI connection not found',
        'ai_connection_still_bound': 'This connection is bound to a purpose. Unbind it first.',
        'ai_connection_name_taken': 'A connection named "{name}" already exists in this organisation.',
        'ai_connection_target_required': 'Choose a saved connection or a provider to test.',
        'ai_usage_limit_exceeded_requests': 'The organization has used {used} of {limit} AI requests allowed for {period}. Contact your administrator to raise the limit.',
        'ai_usage_limit_exceeded_scans': 'The organization has used {used} of {limit} label scans allowed for {period}. Contact your administrator to raise the limit.',
        'invalid_reset_token': 'Invalid or expired reset token',
        'modules_no_organization': 'User not associated with any organization',
        'modules_not_enabled': "Module '{module_name}' is not enabled for this organization",
        'invalid_template_module': 'Module must be "{module}"',
        'purge_blocked_by_audit_links': (
            'Item is linked to audit-relevant records and cannot be permanently deleted.'
        ),
        'permanent_delete_disabled': (
            'Permanent deletion is disabled for this organization.'
        ),
        'documents_approval_workflow_missing': 'This document needs an approval, but nobody has been set up to give it yet. Ask your administrator to set it up.',
        'category_delete_blocked_by_items': (
            'Cannot delete category: it is in use ({count}). Move its products to another category first.'
        ),
        'category_system_field_label_locked': (
            'The name of the "{field}" field belongs to the product catalog and cannot be changed.'
        ),
        'storage_delete_blocked_by_movements': (
            'Cannot delete storage location: {count} stock movements reference it. The movement history is immutable — archive this location instead.'
        ),
        'storage_delete_blocked_by_stock': (
            'Cannot delete storage location: the stock register still holds stock here with no record standing on it. Archive this location instead, or bring its stock back to a record first.'
        ),
        'storage_name_collision': (
            'A storage location named "{name}" already exists at this level.'
        ),
        # Built-in pydantic validation errors (RequestValidationError) —
        # chosen by the error's `type`, filled from its `ctx`, by
        # app.i18n._validation.translate_validation_error.
        # A counted noun carries the CLDR plural forms it needs, suffixed with
        # the category; the base row is the form for every other category
        # (service.get_plural_error_message picks one by the number).
        'validation_missing': 'This field is required',
        'validation_string_too_long': 'Should have at most {max_length} characters',
        'validation_string_too_short': 'Should have at least {min_length} characters',
        'validation_string_too_long_one': 'Should have at most {max_length} character',
        'validation_string_too_short_one': 'Should have at least {min_length} character',
        'validation_pattern': 'Does not match the expected format',
        'validation_greater_than_equal': 'Must be greater than or equal to {ge}',
        'validation_greater_than': 'Must be greater than {gt}',
        'validation_less_than_equal': 'Must be less than or equal to {le}',
        'validation_less_than': 'Must be less than {lt}',
        'validation_enum': 'Must be one of: {expected}',
        'validation_int': 'Must be a whole number',
        'validation_number': 'Must be a number',
        'validation_boolean': 'Must be true or false',
        'validation_identifier': 'Must be a valid identifier',
        'validation_date': 'Must be a valid date',
        'document_return_requires_completed': 'A return can only be made against a completed document',
        'document_return_type_not_eligible': 'Returns can only be made against receipts, issues and transfers',
        'document_return_no_lines': 'A return needs at least one line',
        'document_original_line_missing': 'Line {line} does not exist in document {number}',
        'document_return_quantity_not_positive': 'The quantity returned on line {line} must be greater than zero',
        'document_return_quantity_exceeds_left': 'A return of {quantity} is more than what is left of line {line} ({left} of {done})',
        'document_correction_requires_completed': 'Only a completed document can be corrected',
        'document_correction_no_lines': 'A correction needs at least one line',
        'document_correction_below_zero': 'A correction of {delta} would take line {line} below zero — {left} of {done} is left to correct',
        'document_correction_type_not_correctable': 'Documents of this type cannot be corrected',
        'document_undo_type_not_supported': 'Only a receipt, an issue or a transfer can be undone',
        'document_undo_requires_completed': 'Only a posted document can be undone',
        'document_undo_nothing_left': 'Everything this document posted has already been reversed',
        'document_undo_blocked': 'This cannot be undone: {reason} Use Correct to change what is left instead.',
        'document_undo_stock_used': 'This cannot be undone: later movements used the stock it posted. Use Correct to change what is left instead.',
        'document_post_already_posted': 'This document has already been posted — nothing was posted a second time.',
        'document_post_cancelled': 'This document was cancelled, so it cannot be posted.',
        'document_filter_unknown': 'This filter is not available: no enabled module offers it ({name}).',
        'document_post_waiting_for_approval': 'This document is already waiting for approval; the stock moves once it is approved.',
        'document_type_requires_target_location': 'This document type needs a target location',
        'document_type_requires_source_location': 'This document type needs a source location',
        'document_partner_must_be_supplier_or_manufacturer': 'A receipt takes a supplier, a manufacturer or a customer as its partner',
        'document_partner_must_be_customer_or_supplier': 'An issue takes a customer or a supplier as its partner',
        'document_unit_price_required': 'Every line needs a unit price — missing on lines {lines}',
        'document_preset_unknown': 'There is no preset named {name}. Available: {available}',
        'putaway_capacity_exists': 'This location already has a capacity for this product — edit the existing entry instead.',
        'putaway_capacity_not_found': 'Capacity entry not found',
        'no_fields_to_update': 'No fields to update',
        'putaway_rule_needs_location': 'A putaway rule needs at least one location.',
        'putaway_rule_needs_match_key': 'A putaway rule needs at least one condition — a product, a category, a context tag or a storage type.',
        'document_template_wrong_module': 'A document template belongs to the warehouse module',
        'search_query_empty': 'Type something to search for',
        'document_type_invalid': 'There is no document type {type}',
        'settings_payload_not_object': 'The settings must be sent as a JSON object',
        'settings_field_required': "The setting '{field}' is required",
        'settings_field_unknown': "Unknown setting '{field}'",
        'settings_value_not_string': "The setting '{path}' must be text",
        'settings_value_not_integer': "The setting '{path}' must be a whole number",
        'settings_value_not_number': "The setting '{path}' must be a number",
        'settings_value_not_boolean': "The setting '{path}' must be true or false",
        'settings_value_not_object': "The setting '{path}' must be an object",
        'settings_value_not_array': "The setting '{path}' must be a list",
        'settings_text_too_short': "The setting '{path}' must be at least {limit} characters long",
        'settings_text_too_long': "The setting '{path}' must be at most {limit} characters long",
        'settings_number_too_small': "The setting '{path}' must be at least {limit}, got {value}",
        'settings_number_too_large': "The setting '{path}' must be at most {limit}, got {value}",
        'settings_value_not_allowed': "The setting '{path}' must be one of: {allowed} (got {value})",
        'ai_purpose_unknown': "Unknown AI purpose '{purpose}'",
        'attachment_file_type_invalid': 'Invalid file type: {file_type}',
        'not_an_equipment_model': 'Not an equipment model',
        'bom_line_parent_mismatch': "The line's parent product does not match the product this BOM produces",
        'bom_cycle_detected': 'BOM cycle detected at {template_id}',
        'margin_negative': 'The margin must be 0% or more',
        'margin_too_high': 'The margin must be below 100% to give a finite price',
        'label_size_invalid': 'A label height and width must be > 0.',
        'recipe_collection_not_found': 'Collection not found',
        'recipe_collection_parent_not_found': 'Parent collection not found',
        'recipe_collection_own_parent': 'A collection cannot be its own parent',
        'recipe_collection_under_descendant': 'A collection cannot be moved under its descendant',
        'recipe_scrape_failed': 'Failed to scrape recipe from URL',
        'register_date_from_after_date_to': 'The start date must not be after the end date',
        'meal_plan_end_before_start': 'The end date must not be before the start date',
        'meal_plan_too_long': 'Plan cannot exceed {days} days',
        'meal_plan_no_slots': 'Enable at least one meal slot',
        'meal_plan_start_in_past': 'Target start date must not be in the past',
        'meal_plan_empty': 'Cannot generate a shopping list from an empty plan',
        'picking_terminate_reason_invalid': 'Invalid terminate reason: {reason}',
        'recipe_import_name_required': 'name is required in import data',
        'recipe_import_data_required': 'data required for json import',
        'recipe_import_unit_unknown': "Ingredient '{ingredient}' uses the unit '{unit}', which this instance does not know",
        'recipe_import_unit_missing': "Ingredient '{ingredient}' has an amount but no unit",
        'recipe_import_url_required': 'url required for url import',
        'recipe_scrape_fetch_failed': 'Jina Reader fetch failed for {url}: {error}',
        'recipe_scrape_encoding_unsupported': 'Jina Reader returned compressed content that cannot be read safely. Try another import method.',
        'recipe_scrape_empty': 'Jina Reader returned empty content for {url}',
        'recipe_scrape_no_ingredients': 'The AI found no ingredients — the page may not be a recipe',
        'hex_color_invalid': 'Invalid hex color: {color}. Use format #RGB or #RRGGBB',
        'shopping_list_nothing_to_convert': 'No convertible items (all lack a product template)',
        'stock_take_bulk_item_id_required': 'item_id is required for bulk count operations',
        'cycle_count_scope_location_required': 'storage_location_id is required in scope_filter',
        'cycle_count_no_matching_items': 'No items match the schedule criteria',
        'stock_take_active_for_location': 'An active stock take already exists for this storage location',
        'category_name_taken': 'Category with this name already exists',
        'invitation_code_invalid': 'Invalid or expired invitation code',
        'invitation_other_address': 'This invitation was issued for a different email address',
        'role_not_found': 'Role not found',
        'role_other_organization': 'Role belongs to a different organization',
        'user_not_in_organization': 'User does not belong to this organization',
        'template_other_organization': 'Template belongs to a different organization',
        'template_in_use_by_items': 'Cannot delete template: it is used by {count} item(s)',
        'barcode_already_exists': 'Barcode {barcode} already exists',
        'stock_insufficient_for_template': 'Insufficient stock for template {template_id}: requested {requested}, available {available}',
        'stock_lot_not_consumable': 'Batch {lot} is {status} and cannot be consumed or reserved',
        'barcode_in_use': 'Barcode already in use: {barcode}',
        'serial_number_exists': 'Serial number already exists: {serial_number}',
        'item_currency_mismatch': 'Item currency ({item_currency}) must match organization currency ({organization_currency})',
        'organization_currency_missing': 'Organization currency not configured',
        'item_already_deleted': 'Item is already deleted',
        'item_not_deleted': 'Item is not deleted',
        'item_restore_quantity_unknown': 'Cannot restore item: the original quantity is unknown because the deletion history does not hold it',
        'item_purge_requires_archived': 'Only archived items can be purged',
        'item_purge_reason_required': 'A reason is required for permanent deletion in production',
        'relocation_destination_foreign': 'Cannot move item: the destination is not this organization.',
        'relocation_blocked_by_reservations': 'Cannot move item: source stock has outstanding reservations. Release or fulfill them first.',
        'short_code_invalid_format': 'Invalid code format',
        'short_code_duplicate_in_request': 'Duplicate short_code in request: {short_code}',
        'short_codes_taken': 'short_code(s) already in use in this org: {codes}',
        'onboarding_profile_unknown': "Unknown profile: '{profile}'",
        'storage_vanished_during_batch': 'Storage location {location} vanished during the batch.',
        'storage_archive_blocked_by_items': 'Cannot archive: {count} item(s) are still stored here. Move them first or archive with a target location.',
        'storage_archive_target_is_self': 'Cannot move items into the location being archived.',
        'storage_archive_target_is_descendant': 'Cannot move items into a descendant of the location being archived.',
        'storage_archive_target_archived': 'Cannot move items into an archived location.',
        'storage_restore_parent_archived': 'Cannot restore into an archived parent location. Restore the parent first.',
        'storage_delete_blocked_by_references': 'Cannot delete storage location: it is still referenced by other records (constraint "{constraint}"). Archive it instead.',
        'storage_delete_concurrent_movements': 'Cannot delete storage: a concurrent transaction created stock movements referencing it. Retry to refresh the count. Original error: {error}',
        'sole_administrator_cannot_leave': 'Cannot leave the organization as the sole administrator. Please assign another admin first.',
        'sole_administrator_role_locked': 'Cannot change the role of the only administrator. Promote another member first.',
        'organization_member_limit': 'Organization member limit reached. Upgrade to Inventari Cloud for more slots.',
        'registration_failed': 'Unable to complete registration. Please try again or contact support.',
        'superuser_required': 'Superuser permissions required for this action',
        'onboarding_already_completed': 'Onboarding already completed — use /switch-profile',
        'module_dependency_cycle': "Circular dependency detected involving module: '{module}'",
        'module_dependency_cycle_among': 'Circular dependency detected among modules: {modules}',
        'profile_switch_unknown_modules': 'Profile references modules that are not registered: {unknown_modules}',
        'profile_switch_modules_not_allowed': 'Modules not allowed for this organization: {not_allowed_modules}',
        'profile_switch_dependency_unregistered': "Module '{module}' requires '{missing_dependency}', which is not registered.",
        'focus_mode_module_always_on': "Module '{module}' is always on and cannot be the single focus.",
        'focus_mode_module_unregistered': "Module '{module}' is not registered.",
        'focus_mode_module_not_enabled': "Module '{module}' is not enabled for this organization.",
        'focus_mode_already_active': "Organization is already focused on '{module}'.",
        'focus_mode_not_active': 'Organization is not in single-module focus mode.',
    },
    'pl': {
        'invalid_credentials': 'Nieprawidłowy email lub hasło',
        'invalid_input': 'Nieprawidłowe dane',
        'not_authenticated': 'Nie jesteś zalogowany',
        'user_already_exists': 'Użytkownik z tym adresem email już istnieje',
        'user_already_in_organization': 'Użytkownik już należy do organizacji',
        'token_expired': 'Token uwierzytelniający wygasł',
        'token_invalid': 'Nieprawidłowy token uwierzytelniający',
        'insufficient_permissions': 'Nie masz uprawnień do wykonania tej operacji',
        'import_create_forbidden': 'To konto nie ma uprawnień {permissions}, więc import nie może tworzyć za nie brakujących miejsc ani kategorii. Wyłącz odpowiednie przełączniki w oknie importu albo poproś o to uprawnienie',
        'import_create_forbidden_one': 'To konto nie ma uprawnienia {permissions}, więc import nie może tworzyć za nie brakujących miejsc ani kategorii. Wyłącz odpowiednie przełączniki w oknie importu albo poproś o to uprawnienie',
        'import_stubs_forbidden': 'To konto nie ma uprawnienia {permissions}, więc import nie może tworzyć za nie produktów tymczasowych dla niedopasowanych kodów kreskowych. Odznacz pole „Utwórz produkty tymczasowe dla niedopasowanych kodów kreskowych” w oknie importu albo poproś o to uprawnienie',
        'user_blocked': 'Twoje konto zostało zablokowane. Powód: {reason}',
        'user_blocked_no_reason': 'nie podano',
        'uom_not_found': 'Jednostka miary nie została znaleziona',
        'import_job_not_found': 'Nie znaleziono importu',
        'user_not_found': 'Użytkownik nie został znaleziony',
        'user_email_required': 'To konto nie ma adresu e-mail, więc nie ma przypisanych aktywów do pokazania.',
        'user_inactive': 'Twoje konto oczekuje na akceptację przez administratora.',
        'item_not_found': 'Produkt nie został znaleziony',
        'item_quantity_above_ceiling': 'Ilość {quantity} przekracza pojemność kolumny — najwięcej da się zapisać {ceiling}',
        'item_quantity_raise_in_virtual_location': 'Ten produkt stoi w miejscu „{location}”, w którym zapas się nie liczy — przenieś go najpierw na półkę, potem dodaj ilość',
        'counted_quantity_above_ceiling': 'Zliczona ilość {quantity} przekracza pojemność kolumny — najwięcej da się zapisać {ceiling}',
        'item_create_failed': 'Nie udało się utworzyć produktu',
        'item_update_failed': 'Nie udało się zaktualizować produktu',
        'item_delete_failed': 'Nie udało się usunąć produktu',
        'storage_not_found': 'Miejsce przechowywania nie zostało znalezione',
        'storage_create_failed': 'Nie udało się utworzyć miejsca przechowywania',
        'storage_update_failed': 'Nie udało się zaktualizować miejsca przechowywania',
        'storage_delete_failed': 'Nie udało się usunąć miejsca przechowywania',
        'storage_delete_failed_items': 'Nie można usunąć miejsca, w którym są produkty. Przenieś je lub usuń najpierw.',
        'storage_delete_blocked_by_production_orders': 'Nie można usunąć miejsca: jest ono używane przez zlecenia produkcyjne.',
        'storage_type_not_found': 'Typ miejsca przechowywania nie został znaleziony',
        'storage_type_create_failed': 'Nie udało się utworzyć typu miejsca przechowywania',
        'storage_type_update_failed': 'Nie udało się zaktualizować typu miejsca przechowywania',
        'storage_type_delete_failed': 'Nie udało się usunąć typu miejsca przechowywania',
        'storage_type_exists': 'Typ miejsca przechowywania o tym kodzie już istnieje',
        'storage_type_no_access': 'Nie masz dostępu do tego typu miejsca przechowywania',
        'storage_type_in_use': 'Typ miejsca jest używany przez {count} miejsc',
        'storage_usage_immutable': 'Przeznaczenie miejsca ustala system i nie można go zmienić.',
        'storage_type_system_modify': 'Systemowe typy miejsc przechowywania nie mogą być modyfikowane',
        'storage_type_system_delete': 'Systemowe typy miejsc przechowywania nie mogą być usuwane',
        'category_not_found': 'Kategoria nie została znaleziona',
        'category_create_failed': 'Nie udało się utworzyć kategorii',
        'category_update_failed': 'Nie udało się zaktualizować kategorii',
        'category_delete_failed': 'Nie udało się usunąć kategorii',
        'storage_archived': 'To miejsce jest zarchiwizowane. Przywróć je, zanim umieścisz tu produkty.',
        'stock_take_not_found': 'Inwentaryzacja nie została znaleziona',
        'stock_take_already_completed': 'Inwentaryzacja została już zakończona',
        'stock_take_not_in_progress': 'Inwentaryzacja nie jest w toku',
        'stock_take_create_failed': 'Nie udało się utworzyć inwentaryzacji',
        'stock_take_update_failed': 'Nie udało się zaktualizować inwentaryzacji',
        'shopping_list_not_found': 'Lista zakupów nie została znaleziona',
        'shopping_list_create_failed': 'Nie udało się utworzyć listy zakupów',
        'shopping_list_update_failed': 'Nie udało się zaktualizować listy zakupów',
        'shopping_list_not_writable': 'Ta lista zakupów ma status {status} i nie można jej zmieniać. Najpierw ją reaktywuj.',
        'shopping_list_delete_failed': 'Nie udało się usunąć listy zakupów',
        'shopping_list_item_not_found': 'Element listy zakupów nie został znaleziony',
        'shopping_list_item_quantity_rounds_to_zero': 'Ilość {quantity} po zaokrągleniu do precyzji zapisu wynosi zero — najmniejsza zapisywalna ilość to {smallest}',
        'shopping_list_item_quantity_above_ceiling': 'Ilość {quantity} przekracza pojemność kolumny — najwięcej da się zapisać {ceiling}',
        'shopping_list_item_uom_unknown': 'Nieznana jednostka miary (uom_id: {uom_id}) — jednostka nie istnieje',
        'shopping_list_item_item_unknown': 'Nieznany produkt (item_id: {item_id}) — produkt nie istnieje',
        'shopping_list_item_category_unknown': 'Nieznana kategoria (category_id: {category_id}) — kategoria nie istnieje',
        'shopping_list_item_template_unknown': 'Nieznany szablon produktu (template_id: {template_id}) — szablon nie istnieje',
        'organization_not_found': 'Nie znaleziono organizacji',
        'organization_create_failed': 'Nie udało się utworzyć organizacji',
        'organization_update_failed': 'Nie udało się zaktualizować organizacji',
        'organization_delete_failed': 'Nie udało się usunąć organizacji',
        'smtp_not_configured': 'Ta organizacja nie ma skonfigurowanej wysyłki poczty',
        'demo_smtp_settings_locked': 'To publiczne demo, więc serwer poczty jest stały: każda wiadomość, którą wysłałaby aplikacja, trafia do skrzynki demo. Nie można tu zmieniać ustawień e-mail.',
        'demo_credentials_locked': 'To publiczne demo, w którym każda wiadomość trafia do publicznej skrzynki. Haseł nie można tu zmieniać ani resetować, a odwiedzający nie potrzebują konta.',
        'demo_registration_locked': 'To publiczne demo, a odwiedzający nie potrzebują tu konta. Opcja „Poproś o dostęp” nie jest tu dostępna — skorzystaj z „Wypróbuj demo”.',
        'role_in_use': 'Ta rola jest jeszcze komuś przypisana. Najpierw zmień tym osobom rolę, potem ją usuń.',
        'role_name_taken': 'Rola o nazwie "{name}" już istnieje w tej organizacji.',
        'invitation_not_found': 'Nie znaleziono zaproszenia',
        'organization_invite_invalid': 'Nie można użyć tego zaproszenia. Sprawdź, czy rejestrujesz się na adres e-mail, na który je wysłano, albo poproś o nowe.',
        'organization_invite_link_dead': 'Ten link z zaproszeniem już nie działa. Poproś osobę, która go wysłała, o nowy.',
        'organization_invite_expired': 'Zaproszenie do organizacji wygasło',
        'email_test_failed': 'Nie udało się wysłać wiadomości testowej',
        'module_org_required': 'Aby zarządzać modułami, musisz należeć do organizacji. Zaloguj się ponownie lub skontaktuj się z pomocą.',
        'module_premium_locked': 'Moduł „{module}” jest funkcją płatną. Skontaktuj się z administratorem systemu, aby włączyć go dla Twojej organizacji.',
        'module_always_on': 'Moduł „{module}” jest zawsze włączony i nie da się go wyłączyć.',
        'module_requires_other': 'Najpierw trzeba włączyć moduł „{required}”.',
        'module_blocks_dependent': 'Moduł „{dependent}” zależy od „{module}” i jest teraz włączony. Najpierw wyłącz moduł „{dependent}”.',
        'webhook_url_loopback': 'Ten adres wskazuje na sam serwer ({host}), więc wywołanie nigdy nie opuściłoby maszyny. Podaj adres osiągalny z internetu albo poproś osobę, która prowadzi tę instalację, o dopuszczenie adresów lokalnych (ustawienie WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
        'webhook_url_private': 'Ten adres ({host}) nie jest publicznie routowalny lub jest zarezerwowany dla infrastruktury protokołów, więc serwer odmawia takich wywołań. Podaj adres osiągalny z internetu albo poproś osobę, która prowadzi tę instalację, o dopuszczenie adresów lokalnych (ustawienie WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
        'webhook_url_unresolved': 'Nazwy „{host}” nie udało się rozwiązać, więc adresu nie da się sprawdzić. Podaj nazwę rozwiązywalną publicznie albo poproś osobę, która prowadzi tę instalację, o dopuszczenie adresów lokalnych (ustawienie WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
        'webhook_url_rebinding': 'Nazwa „{host}” wskazuje na adres, który nie jest publicznie routowalny lub jest zarezerwowany dla infrastruktury protokołów ({resolved}). Podaj adres osiągalny z internetu albo poproś osobę, która prowadzi tę instalację, o dopuszczenie adresów lokalnych (ustawienie WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
        'reg_request_new_title': 'Nowa prośba o dostęp',
        'reg_request_new_content': 'Użytkownik {name} prosi o dostęp do systemu.',
        'reg_request_approved_title': 'Prośba o dostęp zatwierdzona',
        'reg_request_approved_content': 'Dostęp dla {email} został zatwierdzony przez {admin}.',
        'reg_link_undelivered_title': 'Link rejestracyjny nie dotarł',
        'reg_link_undelivered_content': 'Nie udało się dostarczyć e-maila z linkiem rejestracyjnym do {email}. Przekaż mu ten link samodzielnie: {link}',
        'reg_request_rejected_title': 'Prośba o dostęp odrzucona',
        'reg_request_rejected_content': 'Dostęp dla {email} został odrzucony przez {admin}.',
        # See the comment on the English entry: the text names the tabs the
        # way the interface names them in this language.
        'reconciliation_drift_title': 'Wykryto rozjazd stanów',
        'reconciliation_drift_content': (
            'Zaplanowane uzgodnienie stanu znalazło liczby, które się nie '
            'zgadzają — {pairs}. Zobacz: Statystyki → Uzgodnienie.'
        ),
        'reconciliation_drift_standing_title': 'Rozjazd stanów wciąż trwa',
        'reconciliation_drift_standing_content': (
            'Zgłoszona wcześniej niezgodność nie zmieniła się i nadal jest — '
            '{pairs}. Zobacz: Statystyki → Uzgodnienie.'
        ),
        'reconciliation_pair_quant_ledger': 'półka a rejestr ruchów: {count}',
        'reconciliation_pair_layer_quant': 'historia kosztu a półka: {count}',
        'event_delivery_dead_title': 'Zadanie w tle ciągle się nie udaje',
        'event_delivery_dead_content': (
            'Obsługa {handler} zdarzenia {event} nie powiodła się {attempts} razy i została wstrzymana. Ostatni błąd: {error}. Zdarzenie zostało zachowane w event_deliveries do sprawdzenia.'
        ),
        'field_required': 'To pole jest wymagane',
        'invalid_email': 'Nieprawidłowy format email',
        'password_too_short': 'Hasło musi zawierać co najmniej 8 znaków',
        'password_invalid': 'Hasło musi zawierać co najmniej jedną dużą literę, jedną małą literę i jedną cyfrę',
        'password_too_long': 'Hasło może mieć najwyżej {max_bytes} bajty',
        'password_needs_lowercase': 'Hasło musi zawierać co najmniej jedną małą literę',
        'password_needs_uppercase': 'Hasło musi zawierać co najmniej jedną dużą literę',
        'password_needs_digit': 'Hasło musi zawierać co najmniej jedną cyfrę',
        'sku_format_invalid': 'SKU może zawierać tylko litery, cyfry, myślniki, podkreślenia i ukośniki',
        'sku_in_use': 'SKU {sku} należy już do innego produktu',
        'custom_field_required': 'Pole „{field}” jest wymagane',
        'field_multi_select_shape': 'Pole „{field}” musi być listą opcji',
        'field_option_not_allowed': 'Wartość „{value}” nie należy do opcji pola „{field}”: {options}',
        'field_money_shape': 'Pole „{field}” musi zawierać kwotę i walutę, nic więcej',
        'field_money_amount': 'Kwota w polu „{field}” musi być liczbą',
        'field_money_currency': 'Waluta w polu „{field}” musi być 3-literowym kodem ISO 4217, na przykład EUR',
        'field_select_shape': 'Pole „{field}” musi mieć jedną opcję',
        'item_limit_reached': 'Ta organizacja osiągnęła limit produktów. Przejdź na Inventari Cloud.',
        'item_archived': 'Produkt jest w archiwum i można go stamtąd przywrócić',
        'announcement_type_invalid': 'Nieprawidłowy typ ogłoszenia. Dozwolone: {allowed}',
        'ai_provider_invalid': 'Nieprawidłowy dostawca. Dozwoleni: {allowed}',
        'field_options_required': 'Pole typu {type} wymaga niepustej listy opcji',
        'member_role_exactly_one': 'Podaj dokładnie jedno z pól: role lub role_id',
        'reason_blank': 'Powód nie może być pusty',
        'discrepancy_reason_required': 'Powód rozbieżności jest wymagany',
        'invalid_uuid': 'Nieprawidłowy format UUID',
        'sheet_unreadable': 'Nie udało się odczytać tego pliku jako arkusza. Sprawdź, czy to poprawny plik .xlsx lub .csv, i spróbuj ponownie.',
        'pasted_text_unreadable': 'Nie udało się odczytać wklejonego tekstu jako tabeli. Wklej wiersze skopiowane z arkusza, z taką samą liczbą kolumn w każdym.',
        'webhook_url_malformed': 'To nie jest poprawny adres internetowy. Podaj pełny adres, na przykład https://example.com/hook.',
        'recipe_extraction_failed': 'Nie udało się wydobyć przepisu z tej strony. Spróbuj ponownie lub wpisz przepis ręcznie.',
        'invalid_date': 'Nieprawidłowy format daty',
        'value_must_be_positive': 'Wartość musi być dodatnia',
        'value_must_be_greater_than_zero': 'Wartość musi być większa od zera',
        'insufficient_quantity': 'Niewystarczająca ilość produktu',
        'file_type_not_allowed': 'Niedozwolony typ pliku',
        'file_signature_mismatch': 'Sygnatura pliku nie zgadza się z zadeklarowanym typem',
        'file_too_large': 'Plik przekracza dozwolony rozmiar (10 MB)',
        'file_type_not_allowed_list': 'Niedozwolony typ pliku. Dozwolone: {allowed}',
        'file_content_type_missing': 'Plik nie podaje swojego typu (brak nagłówka Content-Type).',
        'file_empty': 'Plik jest pusty.',
        'file_not_webp': 'Ten plik nie jest poprawnym obrazem WebP.',
        'import_too_many_rows': 'Plik ma {count} wierszy, a limit to {limit}. Podziel go na mniejsze pliki.',
        'storage_location_ambiguous': '„{text}” pasuje do {count} miejsc ({shown}). Podaj pełną ścieżkę, na przykład „{example}”.',
        'pagination_cursor_invalid': 'Nieprawidłowy lub wygasły kursor stronicowania',
        'webhook_url_scheme': 'Dla webhooków dozwolone są tylko adresy {schemes}.',
        'webhook_url_no_hostname': 'Adres webhooka musi zawierać nazwę hosta, na przykład https://example.com/hook.',
        'picking_already_picked': '{name} już zebrano',
        'picking_unit_mismatch': (
            'Nie da się porównać jednostek dla: {name} — przepis i stan '
            'używają różnych miar. Zapisz, ile waży lub mieści jedna sztuka '
            'na stanie, i zeskanuj ponownie.'
        ),
        'picking_picked': '{name} ✓ — odejmuję {quantity}',
        'invalid_mapping_json': 'Nieprawidłowy JSON mapowania',
        'extra_cost_not_a_receipt': 'Koszty dodatkowe dotyczą przyjęcia: tylko towar przychodzący może nieść koszt dostarczenia go tutaj.',
        'extra_cost_document_posted': (
            'To przyjęcie jest już zaksięgowane, więc nie da się dopisać do niego kosztu: towar mógł już zejść i nie ma czego obciążyć. Wystaw korektę przyjęcia w otwartym okresie.'
        ),
        'extra_cost_currency_mismatch': (
            'Koszt dodatkowy jest w innej walucie niż dokument. Podaj go w walucie dokumentu — przeliczenie po kursie, którego nikt nie zapisał, wstawiłoby do wartości zapasu liczbę bez historii.'
        ),
        'document_shipment_dispatch_only': 'Wysyłkę zapisuje się tylko przy wydaniu: przewoźnik zabiera towar opuszczający magazyn.',
        'document_tracking_template_invalid': 'Link do śledzenia dla „{carrier}” musi być adresem strony zaczynającym się od https:// lub http:// i zawierać {{tracking_number}} w miejscu numeru.',
        'packing_not_a_dispatch': 'Pakuje się tylko wydanie: paczki zawierają towar opuszczający magazyn.',
        'packing_document_not_open': 'Paczki można zmieniać tylko, gdy wydanie jest zatwierdzone i jeszcze niezakończone. Zakończone wydanie zachowuje paczki takie, jakie wysłano.',
        'packing_exceeds_picked': '{name}: zebrano i nie zapakowano jeszcze tylko {remaining}. Paczka mieści to, co zebrano, i nic, co jest już w innej paczce.',
        'packing_exceeds_done': '{name}: paczki zawierają {packed}, a wydanie wysyła {done}. Najpierw wyjmij różnicę z paczek albo zakończ z ilością, którą zawierają.',
        'packing_nothing_to_pack': 'Wszystko, co zebrano, jest już zapakowane, więc nie ma czego włożyć do nowej paczki.',
        'packing_no_packages': 'To wydanie nie ma jeszcze paczek, więc nie ma listu pakowego do wydruku. Najpierw je zapakuj.',
        'package_not_found': 'Nie znaleziono paczki',
        'packing_scan_unrecognized': 'Żaden produkt nie ma kodu {code}. Zeskanuj kod kreskowy samego produktu albo dotknij jego pozycji, aby go zapakować.',
        'packing_scan_not_in_document': '{name} nie jest pozycją tego wydania, więc nie trafia do jego paczek.',
        'invalid_image_extension': 'Nieprawidłowe rozszerzenie obrazu',
        'invalid_role': 'Nieprawidłowa rola. Dozwolone: {roles}',
        'role_not_in_organization': 'Rola nie należy do tej organizacji',
        'failed_to_read_file': 'Nie udało się odczytać pliku: {error}',
        'only_image_files_allowed': 'Dozwolone są tylko pliki graficzne (jpg, png, gif, webp)',
        'image_unreadable': 'Nie udało się odczytać tego pliku jako obrazu',
        'image_too_large': 'Obraz jest zbyt duży (maks. {limit})',
        'demo_upload_file_limit': 'Demo przyjmuje pliki do {limit}',
        'demo_upload_total_limit': 'Demo osiągnęło limit wgranych plików ({limit}). Wgrywanie wróci po najbliższym resecie',
        'demo_sandbox_cap_reached': 'Demo rozdało już na dziś wszystkie kopie. Zajrzyj jutro',
        'demo_sandbox_pool_empty': 'Wszystkie kopie demo są teraz zajęte, a nowe właśnie się przygotowują. Spróbuj za minutę',
        'barcode_or_sku_required': 'Wymagany jest parametr barcode lub sku',
        'barcode_names_one_record': 'Jeden kod kreskowy nie może oznaczać {count} rekordów: {barcode}',
        'storage_no_short_code': 'Miejsce nie ma krótkiego kodu. Wygeneruj go najpierw.',
        'refresh_token_expired_grace': 'Token odświeżania wygasł poza okresem karencji',
        'refresh_token_revoked': 'Token odświeżania został unieważniony',
        'cannot_remove_yourself': 'Nie możesz usunąć samego siebie',
        'cannot_change_own_role': 'Nie możesz zmienić własnej roli',
        'label_in_use_by_product': 'Nie można usunąć etykiety przypisanej do aktywnego produktu. Najpierw usuń produkt.',
        'label_already_assigned': 'Etykieta jest już przypisana',
        'no_labels_available': 'Brak dostępnych etykiet do druku',
        'unauthorized': 'Wymagane uwierzytelnienie',
        'forbidden': 'Odmowa dostępu',
        'organization_required': 'Organizacja jest wymagana',
        'not_found': 'Zasób nie został znaleziony',
        'conflict': 'Konflikt zasobów',
        'internal_error': 'Wystąpił błąd wewnętrzny',
        'rate_limit_exceeded': 'Zbyt wiele żądań. Spróbuj ponownie później.',
        'service_unavailable': 'Usługa tymczasowo niedostępna',
        'stock_take_edit_completed': 'Nie można edytować zakończonej lub anulowanej inwentaryzacji',
        'stock_take_delete_completed': 'Można usunąć tylko wersje robocze lub aktywne inwentaryzacje',
        'stock_take_not_active': 'Inwentaryzacja nie jest aktywna',
        'stock_take_surplus_item_id_required': 'Wybierz produkt, którego dotyczy ta pozycja nadwyżki.',
        'stock_take_surplus_quantity_required': 'Wpisz policzoną ilość tej pozycji nadwyżki.',
        'stock_lot_not_found': 'Partia towaru nie została znaleziona',
        'stock_moves_export_too_many': 'Pasuje {total} ruchów — więcej niż {limit}, które mieści jeden arkusz. Zawęź daty, miejsce lub produkt i wyeksportuj ponownie.',
        'stock_take_close_requires_finalize': 'Inwentaryzację zamyka finalizacja (POST /stock-takes/{id}/complete), a nie zmiana statusu',
        'period_already_closed': 'Okres {period} jest już zamknięty.',
        'period_closed_for_date': 'Okres {period} jest zamknięty, więc nic nie może mieć w nim daty. Zmień datę dokumentu albo poproś osobę, która może ponownie otworzyć okres.',
        'period_closed_for_stock_change': 'Okres {period} jest zamknięty, więc nie można w nim zapisać żadnego ruchu towaru. Poproś osobę, która może ponownie otworzyć okres.',
        'transfer_more_than_the_record_holds': 'Rekord „{item_name}” ma {available}, a linia przenosi {requested}. Zmniejsz ilość w linii albo przenieś resztę z innego rekordu.',
        'transfer_cannot_split_serialized_record': 'Przesunięcie nie może podzielić rekordu seryjnego {serial_number}; przenieś cały rekord.',
        'use_partially_more_than_left': 'Rekord „{item_name}” ma w tym opakowaniu {available}, a podano, że zostało {requested}. Wpisz, ile zostało — nie może być więcej, niż jest.',
        'use_partially_serialized': 'Rekordu seryjnego {serial_number} nie można otworzyć i podzielić; zużyj go w całości.',
        'use_partially_needs_counted_unit': '„{item_name}” jest prowadzony w jednostce miary, więc nie ma opakowania do otwarcia. Odejmij zużytą ilość od stanu.',
        'use_partially_pack_has_no_measure': '„{item_name}” jest liczony w opakowaniach, a produkt nie mówi, ile mieści jedno, więc można zapisać tylko „otwarte” albo „skończone”.',
        'use_by_needs_open_package': 'Rekord „{item_name}” jest zamknięty, więc nie ma daty „zużyć do”. Najpierw go otwórz; do tego czasu liczy się data partii.',
        'period_not_closed': 'Okres {period} nie jest zamknięty.',
        'wms_session_now_held_by': 'Tę sesję prowadzi teraz: {owner}; stąd skany nie są już przyjmowane.',
        'wms_session_held_by_other_user': 'Ten dokument ma aktywną sesję innego użytkownika (otworzył ją: {owner}).',
        'wms_pick_document_not_found': 'Nie znaleziono dokumentu {document} w tej organizacji, więc sesja kompletacji nie została rozpoczęta.',
        'wms_pick_document_not_confirmed': 'Dokument {number} nie jest zatwierdzony, więc sesja kompletacji nie została rozpoczęta. Kompletować można tylko dokumenty zatwierdzone.',
        'wms_pick_document_not_dispatch': 'Dokument {number} nie jest wydaniem, więc sesja kompletacji nie została rozpoczęta. Razem można kompletować tylko wydania.',
        'wms_pick_document_in_session': 'Dokument {number} jest już kompletowany w innej sesji (otworzył ją: {owner}), więc sesja kompletacji nie została rozpoczęta.',
        'wms_line_document_closed': 'Dokument {number} ma status {status}, więc jego linii w tej sesji nie można już zmieniać.',
        'wms_short_below_scanned': 'Ilość końcowa nie może być mniejsza niż zeskanowana ilość ({scanned}); aby zapisać mniej, zaznacz, że liczba zastępuje skany.',
        'wms_short_pick_needs_outcome': 'Linia zebrana z niedoborem wymaga powodu: „Brak ilości” zostawia resztę na zaległość, każdy inny powód zamyka różnicę.',
        'wms_session_not_found': 'Nie znaleziono aktywnej sesji. Być może została już zakończona albo anulowana.',
        'wms_line_not_found': 'Nie znaleziono linii sesji.',
        'wms_line_not_pending': 'Nie znaleziono linii sesji albo nie jest już oczekująca.',
        'wms_quantity_cannot_be_negative': 'Ilość nie może być ujemna.',
        'wms_quantity_above_expected': 'Ilość nie może przekraczać ilości oczekiwanej.',
        'wms_cannot_complete_no_lines': 'Nie można zakończyć sesji: nie ma w niej żadnych linii.',
        'wms_cannot_complete_lines_pending': 'Nie można zakończyć sesji — oczekujących pozycji: {count}.',
        'wms_cannot_complete_destination_not_scanned': 'Nie można zakończyć sesji — nie zeskanowano jeszcze miejsca docelowego.',
        'wms_document_not_confirmed': 'Nie znaleziono dokumentu albo nie jest zatwierdzony.',
        'wms_document_type_not_supported': 'Ta sesja nie obsługuje dokumentów typu {document_type}.',
        'wms_nothing_to_undo': 'Ta linia nie ma nic zapisanego do cofnięcia.',
        'wms_undo_line_is_packed': '{name}: paczka zawiera już {packed} z tego, co zebrano. Najpierw wyjmij to z paczki, potem cofnij zbiórkę.',
        'wms_skip_line_is_packed': '{name}: paczka zawiera już {packed} z tego, co zebrano. Najpierw wyjmij to z paczki, potem pomiń pozycję.',
        'wms_cancel_session_is_packed': '{name}: paczka zawiera już {packed} z tego, co zebrano. Najpierw wyjmij to z paczki, potem anuluj sesję.',
        'wms_barcode_required': 'Najpierw zeskanuj kod kreskowy.',
        'document_execution_line_foreign': 'Ta pozycja wykonania nie należy do tego dokumentu.',
        'document_execution_line_repeated': 'Każdą linię dokumentu można wykonać tylko raz.',
        'document_done_quantity_negative': 'Wykonana ilość nie może być ujemna: {quantity}.',
        'document_done_quantity_above_expected': 'Wykonana ilość {quantity} przekracza ilość oczekiwaną (maks. {expected}).',
        'document_held_quantity_negative': 'Ilość wstrzymana nie może być ujemna: {quantity}.',
        'document_held_quantity_above_received': 'Ilość wstrzymana {quantity} przekracza ilość przyjętą ({received}).',
        'document_held_quantity_needs_receipt': 'Tylko przyjęcie może wstrzymać towar.',
        'document_held_quantity_needs_code': 'Wstrzymana ilość wymaga kodu Uszkodzenie lub Wstrzymane jakościowo.',
        'document_partial_needs_discrepancy_code': 'Częściowe wykonanie wymaga kodu niezgodności.',
        'document_correction_above_expected': 'Korekta {quantity} przekracza ilość oczekiwaną {expected} w wartościach bezwzględnych.',
        'document_correction_sign_mismatch': 'Korekta musi zachować znak oczekiwanej różnicy: {quantity} wobec {expected}.',
        'document_correction_missing_original': 'Ta korekta nie wskazuje dokumentu, który koryguje.',
        'document_correction_original_not_found': 'Nie znaleziono korygowanego dokumentu {document}.',
        'document_correction_would_go_negative': 'Korekta wprowadziłaby {item} poniżej zera: obecnie {current}, zmiana {delta}, wynik {result}.',
        'document_adjustment_would_go_negative': 'Korekta stanu wprowadziłaby {item} poniżej zera: obecnie {current}, zmiana {delta}, wynik {result}.',
        'document_line_needs_identity': 'Linia dokumentu musi wskazywać rekord, produkt albo nazwę.',
        'document_rework_wrong_status': 'Dokumentu o statusie {status} nie można przywrócić do wersji roboczej; można to zrobić tylko z zatwierdzonego albo oczekującego na zatwierdzenie.',
        'stock_record_not_found': 'Nie znaleziono rekordu {item}.',
        'stock_product_not_found': 'Nie znaleziono produktu {product}.',
        'stock_insufficient_record': 'Za mało stanu dla „{item}”: dostępne {available}, żądane {requested}.',
        'receipt_needs_target_location': 'Dokument przyjęcia nie ma miejsca docelowego.',
        'receipt_needs_quarantine_location': 'Przyjęcie zawiera towar uszkodzony lub wstrzymany jakościowo, a profil dokumentów nie wskazuje miejsca kwarantanny. Wskaż je w ustawieniach dokumentów.',
        'transfer_needs_target_location': 'Dokument przesunięcia nie ma miejsca docelowego.',
        'receiving_mode_needs_a_warehouse': 'Sposób przyjmowania wybiera tylko miejsce najwyższego poziomu.',
        'putaway_needs_another_location': 'Towar już tu stoi: wybierz miejsce, na które trafia.',
        'replenishment_nothing_to_move': 'Nie ma czego przenieść z rezerwy: półka nie ma już towaru albo półka zbiorcza go nie potrzebuje.',
        'replenishment_shelf_scan_required': 'Zeskanuj miejsce rezerwy, z którego bierzesz towar.',
        'replenishment_shelf_scan_mismatch': 'Ten kod wskazuje inną półkę: zeskanuj miejsce rezerwy, z którego bierzesz towar.',
        'putaway_shelf_scan_required': 'Zeskanuj etykietę półki, zanim odłożysz towar.',
        'home_shelf_receiving': 'Strefa przyjęć nie może być stałym miejscem produktu: towar tylko tam czeka.',
        'home_shelf_quarantine': 'Miejsce kwarantanny nie może być stałym miejscem produktu: wstrzymany towar nie jest tam trzymany.',
        'home_shelf_not_stock': 'To miejsce nie przyjmuje towaru, więc nie może być stałym miejscem produktu.',
        'stock_take_status_unchangeable': 'Nie można zmienić statusu z {current} na {new}.',
        'api_keys_limit_reached': 'Organizacja ma już {count} aktywnych kluczy API, czyli maksimum. Aby utworzyć nowy, odwołaj jeden z istniejących.',
        'document_pdf_requires_confirmed': 'PDF powstaje z dokumentu zatwierdzonego albo zakończonego. Ten ma status {status}.',
        'documents_pdf_require_confirmed': 'Wspólny PDF powstaje tylko z dokumentów zatwierdzonych albo zakończonych. Nie do wydruku: {numbers}.',
        'stock_take_item_not_found': 'Pozycja inwentaryzacji nie została znaleziona',
        'stock_take_item_already_exists': 'Produkt został już dodany do tej inwentaryzacji',
        'stock_take_item_outside_location': 'Ten produkt leży poza miejscem objętym spisem; policzenie go tutaj nadpisałoby stan, który ma tam',
        'stock_take_shelf_outside_location': 'To miejsce nie należy do spisu miejsca {location}',
        'stock_take_uncounted_items': 'Pozostało {count} niepoliczonych pozycji',
        'stock_none_at_location': 'W miejscu {location} nie ma produktu {product}.',
        'stock_all_batches_held': 'Każda partia produktu {product} w miejscu {location} jest w kwarantannie albo wstrzymana, więc nie da się jej użyć.',
        'stock_not_enough': 'W miejscu {location} jest dostępne {available} produktu {product}, a poproszono o {requested}.',
        'stock_take_over_cap': 'W {count} pozycjach policzona ilość znacznie przekracza stan systemowy. Sprawdź je i potwierdź, aby zapisać policzone liczby.',
        'stock_take_over_tolerance': 'W {count} pozycjach policzona ilość różni się od stanu systemowego bardziej, niż dopuszcza tolerancja tego spisu. Zanim zostaną zaksięgowane, musi je przyjąć ktoś, kto ma do tego uprawnienie.',
        'stock_take_tolerance_reason_missing': 'W {count} pozycjach różnica przekracza tolerancję i nie ma podanego powodu. Podaj powód przy każdej z nich, a potem zakończ spis.',
        'stock_take_tolerance_not_allowed': 'Przyjęcie różnicy ponad tolerancję wymaga uprawnienia do akceptacji spisów.',
        'stock_take_awaiting_recount': 'W {count} pozycjach poproszono o ponowne policzenie. Policz je jeszcze raz, a potem zakończ spis.',
        'stock_take_stock_moved': 'W {count} pozycjach stan zmienił się po policzeniu. Zostały odesłane do ponownego policzenia.',
        'document_not_found': 'Dokument nie został znaleziony',
        'work_item_not_found': 'Zadanie nie zostało znalezione',
        'work_item_taken': 'Ktoś inny właśnie przejął to zadanie.',
        'pdf_generation_failed': 'Generowanie PDF nie powiodło się',
        'import_only_draft': 'Można importować linie tylko do dokumentów w wersji ROBOCZEJ',
        'paste_empty': 'Brak linii do importu — wklej co najmniej wiersz nagłówka i jeden wiersz danych',
        'import_asset_name_missing': 'Brak nazwy zasobu',
        'import_line_name_missing': 'Brak nazwy produktu',
        'import_location_unresolved': 'Nie udało się rozpoznać miejsca',
        'import_location_not_found': 'Nie ma miejsca o nazwie „{value}”',
        'import_price_invalid': 'Kolumna „{column}”: „{value}” nie jest ceną',
        'import_date_invalid': 'Kolumna „{column}”: „{value}” nie jest datą',
        'import_job_failed': 'Import zatrzymał się z powodu nieoczekiwanego błędu.',
        'import_job_interrupted': 'Import został przerwany, zanim się zakończył.',
        'import_column_not_a_number': 'Kolumna „{column}”: „{value}” nie jest liczbą',
        'import_quantity_not_positive': 'Kolumna „{column}”: ilość musi być większa od zera, a „{value}” nie jest',
        'import_column_location_not_found': 'Kolumna „{column}”: nie ma miejsca „{value}”',
        'import_column_category_not_found': 'Kolumna „{column}”: nie ma kategorii „{value}”',
        'import_unknown_unit': 'Kolumna „{column}”: nieznana jednostka „{value}”. Znane jednostki: {units}',
        'import_column_not_yes_no': 'Kolumna „{column}”: „{value}” nie jest wartością tak ani nie',
        'import_column_not_in_options': 'Kolumna „{column}”: „{value}” nie jest jedną z możliwości: {options}',
        'import_column_quantity_blank': 'Kolumna „{column}”: ilość jest pusta. Wpisz ją albo wyczyść mapowanie ilości, żeby każdy wiersz wszedł jako 1',
        'import_column_field_shape': 'Kolumna „{column}”: wartość nie pasuje do pola, do którego przypisano kolumnę',
        'import_field_required_unreadable': 'Pole „{field}” jest wymagane i nie da się go odczytać z komórki',
        'import_field_required_no_column': 'Pole „{field}” jest wymagane, a plik nie ma dla niego kolumny',
        'import_column_field_required': 'Kolumna „{column}”: to pole jest wymagane',
        'import_column_reason': 'Kolumna „{column}”: {reason}',
        'import_row_failed': 'Nie udało się zaimportować wiersza',
        'document_lines_quantity_not_positive': 'Linie {lines} mają ilość mniejszą lub równą zero. Popraw je przed potwierdzeniem.',
        'document_delivery_lines_reference_items': 'Wiersze dokumentu wydania (WZ) muszą wskazywać istniejące produkty',
        'document_scrap_lines_reference_items': 'Wiersze dokumentu złomowania muszą wskazywać istniejące produkty',
        'document_reason_scrap_only': 'Powód złomowania może mieć tylko dokument złomowania',
        'document_scrap_reason_required': 'Dokument złomowania mówi, dlaczego towar jest odpisany: wybierz powód, a przy „Inny” wpisz go w uwagach',
        'document_transfer_lines_reference_items': 'Wiersze dokumentu przesunięcia (MM) muszą wskazywać istniejące produkty',
        'document_correction_lines_reference_items': 'Wiersze dokumentu korekty muszą wskazywać istniejące produkty',
        'document_adjustment_lines_reference_items': 'Wiersze dokumentu korekty stanu muszą wskazywać istniejące produkty',
        'recipe_collection_name_taken': 'Kolekcja przepisów o nazwie „{name}” już istnieje w tej organizacji.',
        'recipe_name_taken': 'Receptura o tej nazwie już istnieje dla tego produktu.',
        'recipe_not_found': 'Przepis nie został znaleziony',
        'picking_active_recipe_locked': 'Nie można edytować składników, gdy sesja zbierania jest aktywna. Najpierw anuluj lub zakończ sesję.',
        'meal_plan_dates_exclude_entries': 'Najpierw usuń wpisy z wykluczonych dni.',
        'meal_plan_position_taken': 'Nie udało się znaleźć wolnego miejsca w tym posiłku.',
        'meal_plan_entry_date_out_of_range': 'Data wpisu wykracza poza zakres dat planu.',
        'meal_plan_slot_not_enabled': 'Ten posiłek nie jest włączony w tym planie.',
        'shopping_exclusion_exists': 'To wykluczenie już istnieje.',
        'shopping_item_already_purchased': 'Ta pozycja jest już oznaczona jako kupiona.',
        'shopping_item_already_purchased_reset': 'Ta pozycja jest już oznaczona jako kupiona. Aby ją zmienić, najpierw oznacz ją jako niekupioną.',
        'shopping_list_not_editable': 'Nie można edytować ukończonej ani zarchiwizowanej listy zakupów.',
        'shopping_lists_module_disabled': 'Moduł list zakupów nie jest włączony dla tej organizacji.',
        # maker's own word is "receptura" (the recipes module owns "przepis")
        'maker_recipe_not_found': 'Receptura nie została znaleziona',
        'uom_quantity_non_negative': 'Ilość nie może być ujemna',
        'uom_conversion_unavailable': (
            'Ilości w jednostce {unit} nie da się przeliczyć na jednostkę '
            'magazynową {stock_unit}'
        ),
        'webhook_not_found': 'Webhook nie został znaleziony',
        'putaway_rule_not_found': 'Reguła odłożenia nie została znaleziona',
        'document_line_not_found': 'Nie znaleziono linii dokumentu',
        'putaway_unknown_context_tag': 'Nieznana grupa kategorii „{value}” — wybierz jedną z tych zdefiniowanych na istniejących kategoriach',
        'putaway_unknown_storage_type': 'Nieznany typ magazynu „{value}” — wybierz jeden z typów zdefiniowanych w organizacji',
        'location_not_internal': '„{name}” to miejsce wirtualne — towar można odkładać tylko w zwykłych miejscach magazynowych',
        'location_archived': '„{name}” jest zarchiwizowane — przywróć je najpierw albo wybierz miejsce, które wciąż widnieje na listach',
        'line_target_receipt_only': 'Miejsce można wskazać tylko na liniach przyjęcia — linie wydań i przesunięć biorą cele z dokumentu',
        'line_target_already_received': 'Ta linia została już przyjęta w otwartej sesji przyjęcia; towar zostaje w miejscu, do którego go przyjęto',
        'exclusion_not_found': 'Wykluczenie nie zostało znalezione',
        'tag_not_found': "Tag '{tag}' nie został znaleziony w żadnym przepisie",
        'meal_plan_not_found': 'Plan posiłków nie został znaleziony',
        'meal_plan_entry_not_found': 'Wpis planu posiłków nie został znaleziony',
        'meal_plan_slot_conflict': 'W wyłączanych slotach są wpisy: {slots}',
        'attachment_not_found': 'Załącznik nie został znaleziony',
        'api_key_not_found': 'Klucz API nie został znaleziony',
        'invalid_api_key': 'Nieprawidłowy lub wygasły klucz API',
        'api_key_unknown': 'Żaden klucz API nie pasuje do tej wartości — sprawdź, czy nie ma literówki',
        'api_key_expired': 'Ten klucz API wygasł — wydaj nowy',
        'api_key_revoked': 'Ten klucz API został odebrany — wydaj nowy',
        'api_key_owner_inactive': 'Konto, do którego należy ten klucz API, jest nieaktywne.',
        'unit_conversion_already_exists': 'Przelicznik z jednostki {unit} dla „{ingredient}” już istnieje w tej organizacji. Edytuj go zamiast dodawać nowy.',
        'conversion_not_found': 'Przelicznik nie został znaleziony',
        'conversion_not_found_or_system': 'Przelicznik nie został znaleziony lub jest domyślny systemowy',
        'template_not_found': 'Szablon nie został znaleziony',
        'template_import_not_json': 'Pliku nie udało się odczytać jako eksportu szablonu — to nie jest poprawny JSON.',
        'template_import_wrong_kind': 'Ten plik nie jest wyeksportowanym szablonem dokumentu.',
        'template_import_wrong_version': 'Plik został wyeksportowany w wersji formatu {version}; ta instalacja obsługuje wersję {supported}.',
        'template_import_invalid_field': 'Pole „{field}” jest nieobecne lub nieprawidłowe.',
        'template_import_unknown_placeholders': 'Szablon odwołuje się do pól, które nie istnieją: {placeholders}.',
        'template_import_not_renderable': 'Szablonu nie udało się wyrenderować: {detail}',
        'model_not_found': 'Model sprzętu nie został znaleziony',
        'widget_not_found': 'Widget nie został znaleziony',
        'bom_line_not_found': 'Pozycja BOM nie została znaleziona',
        'bom_line_already_exists': (
            'Ta receptura ma już ten składnik — linia między tymi produktami '
            'już istnieje.'
        ),
        'bom_depth_exceeded': (
            'Ta receptura jest zagnieżdżona głębiej niż {max_depth} poziomów — '
            'nie da się jej rozwinąć.'
        ),
        'cost_line_not_found': 'Pozycja kosztowa nie została znaleziona',
        'production_order_not_found': 'Zlecenie produkcyjne nie zostało znalezione',
        'production_no_recipe': (
            'Brak receptury dla tego produktu — najpierw utwórz recepturę'
        ),
        'production_recipe_not_found': (
            'Receptura {recipe_id} nie istnieje w tej organizacji'
        ),
        'production_recipe_product_mismatch': ('Receptura nie należy do tego produktu'),
        'production_complete_not_draft': (
            'To zlecenie produkcyjne ma już status {status} — zakończyć można '
            'tylko wersję roboczą.'
        ),
        'production_reverse_not_completed': (
            'Ten przebieg produkcji ma status {status}, więc nie ma czego cofać — cofnąć można tylko zakończony przebieg.'
        ),
        'production_reverse_output_used': (
            'Tego przebiegu nie można cofnąć: część tego, co wyprodukował, zeszła już z półki. Zamiast tego zapisz korektę stanu tego, co zostało.'
        ),
        'production_cancel_not_draft': (
            'To zlecenie produkcyjne ma już status {status} — anulować można '
            'tylko wersję roboczą.'
        ),
        'production_update_not_draft': (
            'To zlecenie produkcyjne ma już status {status} — edytować można '
            'tylko wersję roboczą.'
        ),
        'production_actual_qty_must_be_positive': (
            'Ilość wyprodukowana musi być większa od zera.'
        ),
        'production_overproduction_disabled': (
            'Nadprodukcja jest wyłączona w ustawieniach — to zlecenie nie może '
            'wyprodukować więcej niż zaplanowano.'
        ),
        'production_ingredient_unmeasurable': (
            'Jednostki składnika nie da się porównać z jego stanem, więc nie wiadomo, '
            'ile zdjąć z półki — najpierw popraw jednostkę w wierszu receptury.'
        ),
        'production_short_of_stock': 'Na stanie jest za mało składników na to zlecenie produkcyjne.',
        'output_template_not_found': 'Szablon produktu wyjściowego nie został znaleziony',
        'purchase_order_not_found': 'Zamówienie zakupu nie zostało znalezione',
        'reorder_rule_not_found': 'Reguła uzupełniania nie została znaleziona',
        'pricelist_entry_not_found': 'Pozycja cennika nie została znaleziona',
        'reorder_max_below_min': 'max_quantity ({max_quantity}) musi być >= min_quantity ({min_quantity})',
        'reorder_safety_stock_negative': 'safety_stock musi być >= 0, otrzymano {safety_stock}',
        'reorder_min_quantity_negative': 'min_quantity musi być >= 0, otrzymano {min_quantity}',
        'pricelist_unit_price_not_positive': 'unit_price musi być > 0, otrzymano {unit_price}',
        'pricelist_min_quantity_not_positive': 'min_quantity musi być > 0, otrzymano {min_quantity}',
        'pricelist_valid_to_before_valid_from': 'valid_to ({valid_to}) musi być >= valid_from ({valid_from})',
        'pricelist_duplicate': (
            'Ten dostawca ma już cenę tego produktu na te same daty i przy tej '
            'samej minimalnej ilości. Popraw tamtą pozycję, zamiast dodawać '
            'drugą.'
        ),
        'tax_rate_not_found': 'Stawka podatku nie została znaleziona',
        'announcement_not_found': 'Ogłoszenie nie zostało znalezione',
        'cycle_count_schedule_not_found': 'Harmonogram inwentaryzacji cyklicznej nie został znaleziony',
        'document_type_config_not_found': 'Konfiguracja typu dokumentu nie została znaleziona',
        'history_entry_not_found': 'Wpis historii nie został znaleziony',
        'ingredient_not_found': 'Składnik nie został znaleziony',
        'label_not_found': 'Etykieta nie została znaleziona',
        'scan_unrecognized': 'Kod nie został rozpoznany — nie pasuje do żadnego produktu, etykiety, miejsca ani dokumentu',
        'member_not_found': 'Członek nie został znaleziony',
        'module_not_found': 'Moduł nie został znaleziony',
        'notification_not_found': 'Powiadomienie nie zostało znalezione',
        'partner_not_found': 'Kontrahent nie został znaleziony',
        'partner_name_exists': 'Kontrahent o nazwie "{name}" i typie "{partner_type}" już istnieje.',
        'partner_code_exists': 'Kontrahent o kodzie "{code}" już istnieje.',
        'partner_delete_open_purchase_orders': 'Nie można usunąć kontrahenta: {count} otwartych zamówień zakupowych odwołuje się do tego kontrahenta',
        'partner_import_name_missing': 'Brak nazwy kontrahenta',
        'partner_import_duplicate': 'Duplikat kontrahenta: "{twin}" ma już tę nazwę lub ten numer identyfikacji podatkowej',
        'product_not_found': 'Produkt nie został znaleziony',
        'product_template_not_found': 'Szablon produktu nie został znaleziony',
        'profile_not_found': 'Profil nie został znaleziony',
        'receiving_session_not_found': 'Sesja przyjęcia nie została znaleziona',
        'request_not_found': 'Wniosek nie został znaleziony',
        'workflow_not_found': 'Przepływ nie został znaleziony',
        'campaign_not_found': 'Kampania nie została znaleziona',
        'attestation_no_active_assignments': 'W wybranym zakresie nie ma aktywnych wydań sprzętu',
        'attestation_not_draft': 'Ta atestacja jest już {status} — uruchomić można tylko szkic',
        'attestation_reminders_not_active': 'Przypomnienia można wysłać tylko dla trwającej atestacji',
        'campaign_deadline_past': 'Termin kampanii musi być dzisiejszy lub późniejszy',
        'attestation_complete_not_allowed': 'Atestacji w stanie {status} nie można zakończyć',
        'attestation_scope_exceeds_limit': 'Zakres obejmuje ponad {limit} produktów. Zawęź go albo podziel atestację na mniejsze.',
        'assignment_not_found': 'Przypisanie nie zostało znalezione',
        'maintenance_log_not_found': 'Dziennik konserwacji nie został znaleziony',
        'equipment_cannot_checkout_retired': 'Nie można wydać wycofanego zasobu',
        'equipment_cannot_checkout_in_maintenance': 'Nie można wydać zasobu, który jest w serwisie; najpierw ustaw status Dostępny',
        'equipment_assignment_needs_person_or_location': 'Podaj osobę, która odbiera sprzęt, albo miejsce, w którym staje, ale nie oba',
        'equipment_bulk_scope_too_large': 'Filtrom odpowiada {matched} zasobów; jedna akcja obejmuje najwyżej {limit}. Zawęź filtry.',
        'equipment_assignment_already_active': 'Przedmiot jest już wydany',
        'equipment_assignment_already_checked_in': 'Przypisanie zostało już zwrócone',
        'api_key_cannot_manage': 'Klucze API nie mogą zarządzać innymi kluczami API',
        'api_key_cannot_create': 'Klucze API nie mogą tworzyć innych kluczy API',
        'api_key_cannot_revoke': 'Klucze API nie mogą unieważniać innych kluczy API',
        'api_key_scope_refused': 'Ten klucz API jest ograniczony do zakresu {scope} i nie może być tu użyty',
        'api_key_scope_unknown': 'Nie ma zakresu kluczy API o nazwie „{scope}”',
        'api_key_permission_not_grantable': 'Klucz API nie może dostać uprawnienia {permission}: nie masz go albo żaden klucz go nie nosi',
        'api_key_permission_outside_scope': 'Uprawnienie {permission} nie należy do zakresów wybranych dla tego klucza',
        'print_no_agent': 'Żadna drukarka nie jest podłączona. Uruchom Inventari Print Agent przy drukarce.',
        'print_choose_agent': 'Podłączonych jest kilka drukarek. Wybierz, na której drukować.',
        'print_agent_protocol_missing': 'Ten agent nie podaje, jakiego protokołu druku używa: jest starszy niż protokół z wersją. Zaktualizuj agenta druku.',
        'print_agent_protocol_unsupported': 'Ten agent używa protokołu druku w wersji {agent}; ten serwer używa protokołu druku w wersji {server}. Zaktualizuj to, co starsze.',
        'print_agent_not_found': 'Nie znaleziono drukarki',
        'print_job_not_found': 'Nie znaleziono zlecenia wydruku',
        'print_job_nothing_to_print': 'Nie ma czego drukować: nie znaleziono żadnej z wybranych etykiet',
        'product_label_no_code': 'Nie ma czego drukować: żaden z wybranych produktów nie ma kodu. Wygeneruj go w formularzu produktu',
        'product_label_too_narrow': 'Kod {code} nie mieści się na etykiecie szerokiej na {width} mm: jego kreski potrzebują co najmniej {needed} mm. Wybierz szerszą etykietę',
        'product_label_too_short': 'Etykieta wysoka na {height} mm jest za niska: po nazwie i tekście kreskom kodu {code} zostaje za mało wysokości, by skaner je odczytał. Wybierz wyższą etykietę',
        'storage_code_template_invalid': 'Szablonu kodów „{template}” nie da się użyć. Wpisz pola takie jak {{zone}}-{{rack:02}}-{{level:02}}, z separatorem między nimi, albo prefiks z najwyżej pięciu liter i cyfr, np. LOC',
        'storage_code_template_not_tree': 'Ten magazyn losuje kody: zanim ponumerujesz jego miejsca, nadaj mu szablon z polami, np. {zone}-{rack:02}-{level:02}',
        'storage_code_parent_not_numbered': 'Tego miejsca nie da się ponumerować osobno: miejsca nad nim nie mają jeszcze kodów z szablonu albo leży głębiej, niż sięga szablon. Najpierw ponumeruj poziom wyżej',
        'storage_code_number_not_here': 'Ponumerować można tylko zwykłe miejsce, nie zarchiwizowane ani wirtualne',
        'storage_code_template_not_warehouse': 'Szablon kodów należy do magazynu, czyli miejsca na szczycie drzewa',
        'print_job_not_claimed': 'To zlecenie wydruku nie jest drukowane przez tę drukarkę',
        'print_job_not_retryable': 'Ponownie można wysłać tylko zlecenie zakończone błędem',
        'print_job_one_target': 'Wyślij jeden rodzaj etykiet: etykiety z puli po identyfikatorze, etykiety z puli po kodzie albo miejsca.',
        'webhook_admin_only': 'Tylko administratorzy mogą zarządzać webhookami',
        'approvals_manage_admin_only': 'Tylko administratorzy i menedżerowie mogą modyfikować procesy zatwierdzania',
        'approvals_action_admin_only': 'Nie masz uprawnień do zatwierdzania ani odrzucania wniosków',
        'approvals_read_forbidden': 'Nie masz uprawnień do przeglądania wniosków o akceptację',
        'approvals_write_forbidden': 'Nie masz uprawnień do składania wniosków o akceptację',
        'documents_approve_requires_grant': 'Nie masz uprawnień do zatwierdzania ani odrzucania dokumentów',
        'po_approval_workflow_missing': 'To zamówienie wymaga akceptacji, ale nikt nie został jeszcze wyznaczony do jej udzielania. Poproś administratora o ustawienie tego.',
        'po_supplier_required': 'Zamówienia zakupu nie można potwierdzić bez dostawcy',
        'document_type_requires_partner': 'Ten typ dokumentu wymaga kontrahenta.',
        'partner_has_no_email': 'Kontrahent nie ma adresu e-mail.',
        'po_has_no_partner': 'To zamówienie nie ma dostawcy, do którego można je wysłać.',
        'approval_no_active_workflow': 'Dla tej czynności nie skonfigurowano aktywnego przepływu akceptacji.',
        'approval_request_not_found': 'Wniosek o zatwierdzenie nie został znaleziony',
        'po_no_pending_approval_request': 'Dla tego zamówienia zakupowego nie ma oczekującego wniosku o akceptację.',
        'po_request_approval_invalid_status': 'Tego zamówienia zakupowego nie można już skierować do akceptacji.',
        'po_approve_invalid_status': 'Zatwierdzić można tylko zamówienie zakupowe oczekujące na akceptację.',
        'approval_cannot_approve_own_request': 'Nie możesz zatwierdzić własnego wniosku.',
        'approval_cannot_reject_own_request': 'Nie możesz odrzucić własnego wniosku.',
        'approval_approve_invalid_status': 'Zatwierdzić można tylko wniosek oczekujący na decyzję.',
        'approval_reject_invalid_status': 'Odrzucić można tylko wniosek oczekujący na decyzję.',
        'approval_cancel_invalid_status': 'Wycofać można tylko otwarty wniosek.',
        'approval_decision_already_taken': 'Ktoś inny już rozstrzygnął ten wniosek.',
        'approval_not_stage_approver': 'Nie jesteś osobą akceptującą na tym etapie.',
        'approval_only_requester_can_cancel': 'Wniosek może wycofać tylko osoba, która go złożyła.',
        'approval_workflow_inactive': 'Przepływ akceptacji, na którym oparto ten wniosek, nie jest już aktywny.',
        'approval_target_not_found': 'Ten rekord nie istnieje, więc nie można dla niego poprosić o akceptację.',
        'approval_request_already_open': 'Dla tego rekordu jest już otwarty wniosek o akceptację.',
        'approval_workflow_no_stages': 'Ten przepływ akceptacji nie ma skonfigurowanych etapów.',
        'approval_workflow_needs_stage': 'Przepływ akceptacji musi mieć co najmniej jeden etap.',
        'approval_workflow_modify_blocked': 'Tego przepływu nie można zmienić, dopóki czekają na niego wnioski ({count}: {documents}). Osoba, która złożyła wniosek, może go wycofać, a akceptant — rozstrzygnąć; najpierw zamknij te sprawy.',
        'approval_workflow_delete_blocked': 'Tego przepływu nie można usunąć, dopóki czekają na niego wnioski ({count}: {documents}). Osoba, która złożyła wniosek, może go wycofać, a akceptant — rozstrzygnąć; najpierw zamknij te sprawy.',
        'approval_workflow_archived': 'Ten przepływ został usunięty i jest w archiwum: jego wnioski nadal pokazują etapy, przez które przeszły, więc nie można go zmienić ani ponownie włączyć. Utwórz w jego miejsce nowy przepływ.',
        'approval_unknown_approvers': 'Część wybranych osób akceptujących nie należy do tej organizacji.',
        'approval_unknown_requesters': 'Część wybranych osób lub ról nie należy do tej organizacji.',
        'approval_requester_scope_everyone_with_names': 'Przepływ obejmujący wszystkich nie wskazuje osób ani ról.',
        'approval_requester_scope_names_nobody': 'Wybierz co najmniej jedną osobę lub rolę albo wszystkich.',
        'approval_stage_unsolvable': 'Etap „{label}" nie może być nigdy rozstrzygnięty: żaden z wskazanych akceptantów nie ma dostępu do akceptacji. Dodaj przynajmniej jedną osobę z dostępem do akceptacji.',
        'approval_scope_changed': 'To, co ten przepływ zatrzyma, zmieniło się od otwarcia tego okna — przeczytaj jeszcze raz i włącz przepływ, jeśli nadal tego chcesz.',
        'approval_scope_required': 'Włączenie przepływu wymaga zakresu, który zostanie objęty, tak jak pokazało go okno włączania — wyślij „expected_scope”, inaczej przepływ zostaje wyłączony.',
        'approval_stage_open_unsolvable': 'Etap „{label}" czeka na osobę z uprawnieniem akceptacji, a nikt w tej organizacji go nie ma — żaden wniosek nie zostałby nigdy rozstrzygnięty. Przyznaj je komuś albo wskaż akceptanta.',
        'approval_required_first': 'Ta czynność wymaga wcześniejszej akceptacji. Najpierw złóż wniosek.',
        'approval_workflow_required_but_missing': 'To wymaga akceptacji, ale nie ma dla niej aktywnego przepływu. Utwórz przepływ albo znieś wymóg.',
        'approval_required_after_rejection': 'Wniosek o akceptację tej czynności został odrzucony. Złóż nowy, zanim przejdziesz dalej.',
        'approval_granted_for_another_holder': 'Akceptacja dotyczy wydania dla: {holder}. Złóż wniosek o to wydanie.',
        'document_no_pending_approval_request': 'Dla tego dokumentu nie ma oczekującego wniosku o akceptację.',
        'document_request_approval_invalid_status': 'Do akceptacji można skierować tylko potwierdzony dokument.',
        'po_confirm_invalid_status': 'Tego zamówienia zakupowego nie można potwierdzić w bieżącym stanie.',
        'po_email_invalid_status': 'Nie można wysłać e-maila dla zamówienia zakupowego w stanie {status}. Dozwolone są tylko stany CONFIRMED lub COMPLETED.',
        'po_email_invalid_address': 'Nieprawidłowy adres e-mail kontrahenta: {email}',
        'po_partner_inactive': 'Nie można potwierdzić zamówienia zakupowego: kontrahent "{name}" jest nieaktywny',
        'po_partner_not_supplier': 'Nie można potwierdzić zamówienia zakupowego: kontrahent "{name}" ma typ "{partner_type}", który nie jest typem dostawcy',
        'po_approval_race_condition': 'Nie udało się utworzyć wniosku o akceptację — możliwe, że obsłużyła go inna operacja. Spróbuj ponownie.',
        'po_already_cancelled': 'To zamówienie zakupowe jest już anulowane',
        'po_cancel_completed': 'Nie można anulować zakończonego zamówienia zakupowego',
        'po_cancel_received_quantities': 'Nie można anulować tego zamówienia zakupowego, bo przyjęto już ilości — najpierw anuluj powiązane przyjęcia',
        'po_cancel_open_receipts': 'Nie można anulować tego zamówienia zakupowego, dopóki przyjęcia są otwarte — najpierw je zakończ lub anuluj: {numbers}',
        'po_receipt_requires_confirmed': 'Przyjęcie można utworzyć tylko dla potwierdzonego zamówienia zakupowego',
        'po_line_not_found': 'Nie znaleziono pozycji zamówienia zakupowego {po_line_id}',
        'po_receive_quantity_exceeds': 'Ilość {quantity} przekracza pozostałą ilość {remaining} dla pozycji {line}',
        'po_line_product_template_not_found': 'Szablon produktu {template_id} nie został znaleziony',
        'po_update_not_draft': 'Można aktualizować tylko zamówienia zakupowe w wersji roboczej',
        'po_lines_received': (
            'Nie można zaktualizować pozycji: część towaru została już przyjęta. '
            'Najpierw anuluj powiązane dokumenty przyjęcia.'
        ),
        'po_import_not_draft': 'Można importować linie tylko do zamówienia zakupowego w wersji ROBOCZEJ',
        'document_insufficient_stock': 'Za mało zapasu, aby potwierdzić dokument: nie udało się zarezerwować {quantity} z {needed}',
        'document_zone_split_needs_stock_unit': 'Pozycja „{item_name}” jest zapisana w innej jednostce niż jednostka zapasu produktu i nie da się jej rozdzielić na kilka półek — zapisz ją w jednostce zapasu albo pobierz z jednej półki',
        'document_record_stands_elsewhere': 'Rekord „{item_name}” stoi na półce „{record_shelf}”, a dokument zdejmuje z „{document_shelf}” — skieruj dokument na półkę, na której stoi rekord, albo przenieś rekord',
        'document_insufficient_stock_record_elsewhere': 'Za mało zapasu, aby potwierdzić dokument: nie udało się zarezerwować {quantity} z {needed} na półce „{document_shelf}”; rekord „{item_name}” stoi na półce „{record_shelf}” — skieruj dokument na tę półkę albo przenieś rekord',
        'stock_would_go_negative': 'To zeszłoby ze stanem poniżej zera. W międzyczasie ktoś ruszył ten towar — odśwież i spróbuj ponownie.',
        'stock_reserved_over_quantity': 'To zablokowałoby więcej towaru, niż leży na półce. Zwolnij rezerwację albo policz półkę ponownie.',
        'document_exceeds_order_line': 'Przyjęcie {quantity} przekracza pozycję zamówienia, na której zostało {remaining} — powyżej tolerancji nadwyżki {tolerance}% potrzebna jest osoba z uprawnieniem do przyjmowania ponad tolerancję',
        'over_receipt_needs_permission': 'Przyjęcie {quantity} przekracza tolerancję nadwyżki {tolerance}% — potrzebna jest osoba z uprawnieniem do przyjmowania ponad tolerancję',
        'over_receipt_confirm_surplus': '{product}: przyjęcie {quantity} to o {surplus} więcej niż oczekiwane {basis}. Przyjąć nadwyżkę?',
        'over_receipt_confirm_order_surplus': '{product}: przyjęcie {quantity} to o {surplus} więcej niż {basis} pozostałe w zamówieniu {order}, pozycja {line}. Przyjąć nadwyżkę?',
        'over_receipt_past_ceiling': 'Przyjęcie {quantity} wobec {basis} przekracza górny limit nadwyżki {ceiling}% — nikt nie może przyjąć tyle',
        'document_update_status': 'Można aktualizować tylko dokumenty w wersji roboczej',
        'document_correction_locked': 'Dokumenty korekty są zablokowane — można zmieniać tylko notatki. Próbowano zmienić: {fields}. Jeśli dane są błędne, anuluj korektę i utwórz nową.',
        'field_cannot_be_cleared': 'Tych pól nie można wyczyścić: {fields}.',
        'ingredient_defaults_unreadable_file': 'Nie udało się odczytać pliku. Import przyjmuje plik .json lub .csv z jednym wierszem na składnik.',
        'onboarding_modules_not_offered': 'Profil „{profile}” nie oferuje tych modułów: {modules}',
        'location_chain_step_incomplete': 'Każdy krok łańcucha miejsc wymaga identyfikatora lub nazwy.',
        'current_password_incorrect': 'Obecne hasło jest nieprawidłowe',
        'storage_own_parent': 'Miejsce nie może być własnym miejscem nadrzędnym.',
        'storage_short_code_in_use': 'Krótki kod „{short_code}” jest już używany przez inne miejsce.',
        'storage_would_cycle': 'Miejsca nie można przenieść pod jego własne miejsce podrzędne — powstałby cykl w hierarchii miejsc.',
        'template_not_builtin_copy': 'Ten szablon nie został skopiowany z wbudowanego układu',
        'smtp_config_invalid': 'Ustawienia serwera poczty są nieprawidłowe: {reason}',
        'module_needs_newer_platform': 'Moduł „{module}” wymaga Inventari {required} lub nowszego; to jest wersja {current}.',
        'document_delete_status': 'Można usuwać tylko dokumenty w wersji roboczej',
        'document_wms_picking_active': 'Nie można zakończyć ani anulować tego dokumentu, dopóki trwa {sessions} aktywnych sesji kompletacji. Najpierw je zakończ lub anuluj.',
        'document_wms_picking_active_one': 'Nie można zakończyć ani anulować tego dokumentu, dopóki trwa {sessions} aktywna sesja kompletacji. Najpierw ją zakończ lub anuluj.',
        'document_wms_picking_active_few': 'Nie można zakończyć ani anulować tego dokumentu, dopóki trwają {sessions} aktywne sesje kompletacji. Najpierw je zakończ lub anuluj.',
        'document_wms_receiving_active': 'Nie można zakończyć ani anulować tego dokumentu, dopóki trwa {sessions} aktywnych sesji przyjęcia. Najpierw je zakończ lub anuluj.',
        'document_wms_receiving_active_one': 'Nie można zakończyć ani anulować tego dokumentu, dopóki trwa {sessions} aktywna sesja przyjęcia. Najpierw ją zakończ lub anuluj.',
        'document_wms_receiving_active_few': 'Nie można zakończyć ani anulować tego dokumentu, dopóki trwają {sessions} aktywne sesje przyjęcia. Najpierw je zakończ lub anuluj.',
        'document_confirm_invalid_status': 'Nie można potwierdzić dokumentu w stanie {status}',
        'document_lines_need_stock_row': 'Dokument typu {type} zdejmuje towar z półki, więc każda pozycja musi wskazać stan, z którego schodzi — pozycje {lines} wskazują sam produkt',
        'document_lines_need_stock_row_one': 'Dokument typu {type} zdejmuje towar z półki, więc każda pozycja musi wskazać stan, z którego schodzi — pozycja {lines} wskazuje sam produkt',
        'document_lines_need_stock_row_few': 'Dokument typu {type} zdejmuje towar z półki, więc każda pozycja musi wskazać stan, z którego schodzi — pozycje {lines} wskazują sam produkt',
        'document_receipt_lines_need_product': 'Pozycje {lines} nie wskazują produktu z Twojej listy, a przyjęcie wprowadza na stan tylko produkty — wybierz każdą z listy albo dodaj ją jako nowy produkt',
        'document_receipt_lines_need_product_one': 'Pozycja {lines} nie wskazuje produktu z Twojej listy, a przyjęcie wprowadza na stan tylko produkty — wybierz ją z listy albo dodaj jako nowy produkt',
        'document_receipt_lines_need_product_few': 'Pozycje {lines} nie wskazują produktu z Twojej listy, a przyjęcie wprowadza na stan tylko produkty — wybierz każdą z listy albo dodaj ją jako nowy produkt',
        'document_partner_tax_id_required': 'Kontrahent „{name}” nie ma NIP-u, a dokumenty tej organizacji wymagają go do potwierdzenia. Dopisz mu NIP, zaznacz u niego „Osoba prywatna (konsument)” albo wyłącz „Wymagaj NIP partnera” w Ustawieniach dokumentów.',
        'document_complete_invalid_status': 'Nie można zakończyć dokumentu w stanie {status}',
        'document_complete_unanswered_lines': 'Zakończenie bez odpowiedzi dla każdej pozycji zaksięgowałoby pozycje bez odpowiedzi jako w pełni zrealizowane. Pozycje bez odpowiedzi: {lines}. Prześlij ich ilości albo ustaw complete_as_planned=true, by zaksięgować je zgodnie z planem',
        'document_complete_skipped_lines': 'Zakończenie zaksięgowałoby pominięte pozycje jako w pełni zebrane lub przyjęte, choć nikt nie powiedział, co się z nimi stało. Pominięte pozycje: {lines}. Przed zakończeniem przywróć każdą na listę albo odpowiedz, że jest niepełna, z powodem — complete_as_planned ich nie obejmuje',
        'document_receipt_lines_need_expiry': 'Produktu schodzącego z półki według najwcześniejszego terminu nie można przyjąć bez daty ważności — trafiłby za każdy datowany zapas. Pozycje: {lines}. Prześlij partię i termin razem z zakończeniem albo wpisz datę na pozycji',
        'picking_lot_no_longer_available': 'Nie można zamknąć kompletacji: partia {lot} nie może już wydać zebranych z niej {quantity} szt.',
        'document_active_approval_request': 'Dla tego dokumentu istnieje aktywny wniosek o akceptację',
        'document_cancel_invalid_status': 'Można anulować tylko dokumenty w wersji roboczej, oczekujące na akceptację lub potwierdzone',
        'document_fields_closed': 'Pól zakończonego lub anulowanego dokumentu nie można już zmienić',
        'approval_workflow_not_found': 'Nie znaleziono przepływu akceptacji',
        'po_pdf_invalid_status': 'PDF można wygenerować tylko dla potwierdzonego lub zakończonego zamówienia zakupowego. Bieżący stan: {status}',
        'po_pdf_generation_failed': 'Nie udało się wygenerować pliku PDF',
        'email_delivery_failed': 'Nie udało się wysłać e-maila — serwer SMTP może nie być skonfigurowany',
        'invalid_partner_type': 'Ten typ kontrahenta nie jest rozpoznawany.',
        'invalid_country_code': 'Kraj musi być dwuliterowym kodem ISO 3166-1 alpha-2 (np. PL).',
        'invalid_print_page_size': 'Rozmiar papieru musi być A4 lub Letter.',
        'invalid_timezone': 'Strefa czasowa musi być poprawną nazwą strefy IANA (np. Europe/Warsaw).',
        'invalid_currency_code': 'Waluta musi być poprawnym kodem ISO 4217 (np. PLN).',
        'admin_permissions_required': 'Ta akcja wymaga uprawnień administratora',
        'invalid_url_missing_host': 'Nieprawidłowy URL: brak hosta',
        'url_must_be_public': 'URL musi wskazywać na publiczny host',
        'invalid_url_scheme': 'Nieprawidłowy URL: musi zaczynać się od http:// lub https://',
        'rating_must_be_1_to_5': 'Ocena musi być od 1 do 5',
        'no_missing_ingredients': 'Brak brakujących składników do dodania',
        'picking_session_not_found': 'Sesja zbierania nie została znaleziona',
        'barcode_or_item_id_required': 'Wymagany jest barcode lub item_id',
        'ingredient_not_found_or_not_picked': 'Składnik nie znaleziony lub jeszcze nie zebrany',
        'no_valid_images': 'Nie podano prawidłowych obrazów',
        'file_must_be_image': 'Plik musi być obrazem',
        'vision_file_too_large': 'Plik jest za duży',
        'vision_unsupported_image_type': 'Plik „{filename}” nie ma akceptowanego typu obrazu ({content_type}). Akceptowane: {accepted}.',
        'llm_provider_unreachable': (
            'Nie udało się połączyć z dostawcą AI stojącym za połączeniem '
            '"{name}" (model "{model}"). Sprawdź adres i dostępność usługi '
            'w Ustawieniach → Połączenia AI.'
        ),
        'llm_provider_unreachable_generic': (
            'Nie udało się połączyć z dostawcą AI. Sprawdź adres połączenia '
            'i dostępność usługi w Ustawieniach → Połączenia AI.'
        ),
        'llm_provider_timeout': (
            'Połączenie "{name}" (model "{model}") nie odpowiedziało na czas. '
            'Dostawca był osiągalny — model działający na Twoim sprzęcie może '
            'potrzebować więcej czasu (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) albo '
            'mniejszego okna kontekstu.'
        ),
        'llm_provider_timeout_generic': (
            'Dostawca AI nie odpowiedział na czas. Był osiągalny — model '
            'działający na Twoim sprzęcie może potrzebować więcej czasu '
            '(LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) albo mniejszego okna '
            'kontekstu.'
        ),
        'llm_provider_key_rejected': (
            'Dostawca AI stojący za połączeniem "{name}" (model "{model}") '
            'odrzucił klucz API. Sprawdź klucz w Ustawieniach → Połączenia AI.'
        ),
        'llm_provider_key_rejected_generic': (
            'Dostawca AI odrzucił klucz API. Sprawdź klucz w Ustawieniach → '
            'Połączenia AI.'
        ),
        'llm_provider_limit': (
            'Połączenie "{name}" (model "{model}") zostało odrzucone przez '
            'dostawcę AI: limit planu lub saldo konta są wyczerpane. Sprawdź plan '
            'albo spróbuj później.'
        ),
        'llm_provider_limit_generic': (
            'Dostawca AI odmówił: limit planu lub saldo konta są wyczerpane. '
            'Sprawdź plan albo spróbuj później.'
        ),
        'llm_provider_model_unknown': (
            'Dostawca AI stojący za połączeniem "{name}" nie zna modelu '
            '"{model}". Sprawdź nazwę modelu w Ustawieniach → Połączenia AI.'
        ),
        'llm_provider_model_unknown_generic': (
            'Dostawca AI nie zna skonfigurowanego modelu. Sprawdź nazwę modelu w '
            'Ustawieniach → Połączenia AI.'
        ),
        'llm_purpose_unbound': (
            'Dla tej funkcji nie wybrano jeszcze połączenia AI. Wybierz je '
            'w Ustawieniach → Połączenia AI.'
        ),
        'llm_connection_test_failed': (
            'Nie udało się przeprowadzić testu połączenia. Sprawdź adres '
            'i spróbuj ponownie.'
        ),
        'llm_base_url_unresolved': (
            'Nie udało się rozwiązać nazwy hosta "{host}" adresu połączenia '
            'AI — sprawdź pisownię; literówka wygląda tu jak niedostępny '
            'dostawca. Jeśli adres jest wpisany poprawnie, zapytaj '
            'administratora tego serwera, czy nazwa jest opublikowana w DNS.'
        ),
        'llm_base_url_loopback': 'Adres połączenia AI wskazuje na nazwę loopback ({host}). Tylko zewnętrzne adresy — poproś osobę, która prowadzi tę instalację, o dopuszczenie lokalnego serwera modelu (ustawienie LLM_ALLOW_PRIVATE_NETWORKS).',
        'llm_base_url_private': 'Adres połączenia AI wskazuje na prywatny lub wewnętrzny adres ({host}). Tylko zewnętrzne adresy — poproś osobę, która prowadzi tę instalację, o dopuszczenie lokalnego serwera modelu (ustawienie LLM_ALLOW_PRIVATE_NETWORKS).',
        'llm_base_url_scheme': 'Adres połączenia AI musi używać http albo https.',
        'llm_base_url_required_for_http_provider': (
            'Ten dostawca działa przez HTTP, więc adres bazowy jest wymagany '
            '— na przykład https://openrouter.ai/api/v1'
        ),
        'llm_base_url_no_hostname': ('Adres połączenia AI musi zawierać nazwę hosta.'),
        'llm_base_url_refused': (
            'Adres połączenia AI został odrzucony. Tylko zewnętrzne adresy — '
            'ustaw LLM_ALLOW_PRIVATE_NETWORKS=true w instalacjach self-hosted, '
            'aby zezwolić na lokalny serwer modelu.'
        ),
        'vision_model_returned_nothing': (
            'Połączenie "{name}" (model "{model}") nie zwróciło żadnej treści. '
            'Sprawdź, czy model obsługuje obrazy i czy ma dość tokenów — '
            'zdjęcie nie jest tu problemem.'
        ),
        'vision_model_returned_nothing_generic': (
            'Model nie zwrócił żadnej treści. Sprawdź w Ustawieniach → '
            'Połączenia AI, czy w ogóle obsługuje obrazy.'
        ),
        'vision_label_not_understood': (
            'AI nie odczytało tej etykiety przy użyciu połączenia "{name}" '
            '(model "{model}"). Spróbuj wyraźniejszego zdjęcia albo wybierz '
            'inne połączenie w Ustawieniach → Połączenia AI.'
        ),
        'vision_nutrition_not_understood': (
            'AI nie odczytało tej tabeli wartości odżywczych przy użyciu '
            'połączenia "{name}" (model "{model}"). Spróbuj wyraźniejszego '
            'zdjęcia albo wybierz inne połączenie w Ustawieniach → Połączenia AI.'
        ),
        'vision_label_not_understood_generic': (
            'AI nie odczytało tej etykiety. Spróbuj wyraźniejszego zdjęcia albo innego modelu w Połączeniach AI.'
        ),
        'vision_nutrition_not_understood_generic': (
            'AI nie odczytało tej tabeli wartości odżywczych. Spróbuj wyraźniejszego zdjęcia albo innego modelu w Połączeniach AI.'
        ),
        'vision_ai_not_configured': (
            'Do rozpoznawania obrazu nie wybrano jeszcze połączenia AI. Wybierz je w Ustawieniach → Połączenia AI.'
        ),
        'invalid_organization_id': 'Nieprawidłowy identyfikator organizacji',
        'user_has_no_organization': 'Użytkownik nie ma organizacji',
        'unsupported_import_format': 'Nieobsługiwany format importu: {format}',
        'unsupported_export_format': 'Nieobsługiwany format eksportu: {format}',
        'equipment_default_checkout_template': 'Protokół wydania (domyślny)',
        'equipment_default_checkin_template': 'Protokół zwrotu (domyślny)',
        'purchase_order_standard_template': 'Standardowe zamówienie zakupowe',
        'attestation_not_found': 'Link do atestacji nie został znaleziony',
        'attestation_expired': 'Link do atestacji wygasł',
        'attestation_refused': 'Ten link atestacji nie może przyjąć tej czynności. Poproś organizację, która go wysłała, o nowy link.',
        'campaign_closed': 'Ta kampania atestacji została zamknięta — Twoje potwierdzenie nie może być już zapisane. Jeśli nadal masz ten sprzęt, skontaktuj się ze swoją organizacją.',
        'assignment_already_returned': 'Ten sprzęt został już potwierdzony jako zwrócony — kolejne potwierdzenie nie jest potrzebne.',
        'equipment_bulk_item_failed': ('Tego zasobu nie udało się zmienić.'),
        'unknown_bulk_action': 'Nieznana akcja zbiorcza: {action}',
        'item_unit_change_blocked_by_stock': 'Ta pozycja ma {quantity} {current_unit}. Zmiana jednostki na {new_unit} przekleiłaby etykietę na tej liczbie, nie zmieniając tego, co stoi na półce. Najpierw zużyj albo odpisz stan, albo załóż osobną pozycję w nowej jednostce.',
        'item_unit_differs_from_template_confirmation_required': 'Produkt {product} jest prowadzony w {template_unit}, a ta ilość jest podana w {chosen_unit}. Przy zapisie zostanie przeliczona na {template_unit}, więc potwierdź, że chodziło o {chosen_unit}, albo wpisz ilość w {template_unit}.',
        'item_unit_not_convertible_to_card': 'Produkt {product} jest prowadzony w {template_unit}, a ilości w {chosen_unit} nie da się na nie przeliczyć. Wpisz ilość w {template_unit} albo — dla sztuk — zapisz przy produkcie, ile waży lub mieści jedna sztuka.',
        'bom_line_unit_not_convertible': 'Ten składnik prowadzony jest w {stock_unit}, a {line_unit} nie da się '
        'przeliczyć na {stock_unit}. Podaj jednostkę tego samego rodzaju albo '
        'zapisz przy produkcie, ile waży lub mieści jeden {stock_unit}.',
        'bom_line_self_reference': (
            'Linia receptury nie może odwoływać się do samego produktu — '
            'produkt stałby się składnikiem własnej receptury.'
        ),
        'bom_line_cycle': (
            'Ta linia domknęłaby cykl: produkt stałby się składnikiem '
            'własnej receptury.'
        ),
        'uom_quantity_requires_whole_number': (
            'Jednostka {unit} przyjmuje tylko liczby całkowite, więc '
            '{quantity} nie da się zapisać. Zaokrąglij ilość do liczby '
            'całkowitej.'
        ),
        'uom_quantity_too_many_decimal_places': (
            'Jednostka {unit} przyjmuje liczby z dokładnością do {places} '
            'miejsc po przecinku, więc {quantity} nie da się zapisać. '
            'Zaokrąglij ilość do tej dokładności.'
        ),
        'item_unit_cannot_be_removed': (
            'Jednostki {unit} nie da się usunąć: ilość bez jednostki nic nie '
            'mówi. Wybierz zamiast niej inną jednostkę.'
        ),
        'removal_strategy_of_shared_product': (
            'Ten produkt pochodzi ze wspólnego katalogu, więc kolejność '
            'wydawania jego zapasu należy do katalogu i nie da się jej '
            'zmienić dla jednej organizacji.'
        ),
        'piece_unit_missing_from_catalogue': (
            'Katalog jednostek tej instalacji nie ma jednostki sztuki, więc '
            '"ilość czego" nie ma odpowiedzi. Wskaż jednostkę wprost albo '
            'przywróć standardowy katalog jednostek.'
        ),
        'equipment_still_assigned': (
            'Zasób jest nadal wydany osobie. Najpierw go przyjmij.'
        ),
        'stock_as_of_no_history': (
            'Ta organizacja nie zapisuje żadnych ruchów magazynowych, więc '
            'nie ma historii do raportowania. Jedyna dostępna odpowiedź to '
            'dzisiejsze stany magazynu.'
        ),
        'stock_as_of_before_ledger': (
            'Rejestr ruchów zaczyna się {starts_at}. O wcześniejszym czasie '
            'nie wiadomo nic — nie zero — więc raport na dzień {as_of} '
            'byłby zgadywaniem.'
        ),
        'stock_as_of_pdf_too_many': (
            'Pozycji w raporcie: {total} — wydruk mieści najwyżej {limit}. '
            'Wyeksportuj raport jako arkusz albo wybierz jedno miejsce, aby '
            'go zawęzić.'
        ),
        'equipment_deploy_requires_checkout': (
            'Zasób staje się wydany przez wydanie go osobie. '
            'Zamiast ustawiać status, wydaj zasób.'
        ),
        'equipment_status_invalid': 'Nieprawidłowy status: {status}',
        'equipment_status_transition_denied': 'Nie można zmienić statusu z {old} na {new}',
        'equipment_status_transition_from_retired': 'Nie można zmienić statusu z {old} na {new}. Wycofane zasoby muszą być najpierw jawnie przywrócone.',
        'attestation_assignment_required': 'Wybierz zasób, którego dotyczy zgłoszenie problemu',
        'meta_data_spelled_twice': (
            "'meta_data' i 'metadata' to jedno pole zapisane dwoma nazwami. "
            'Wyślij jedno z nich.'
        ),
        'ai_connection_not_found': 'Połączenie AI nie zostało znalezione',
        'ai_connection_still_bound': 'To połączenie jest przypisane do celu. Najpierw je odepnij.',
        'ai_connection_name_taken': 'Połączenie o nazwie „{name}” już istnieje w tej organizacji.',
        'ai_connection_target_required': 'Wybierz zapisane połączenie albo dostawcę do przetestowania.',
        'ai_usage_limit_exceeded_requests': 'Organizacja wykorzystała {used} z {limit} zapytań AI przysługujących na okres {period}. Skontaktuj się z administratorem, aby podnieść limit.',
        'ai_usage_limit_exceeded_scans': 'Organizacja wykorzystała {used} z {limit} skanów etykiet przysługujących na okres {period}. Skontaktuj się z administratorem, aby podnieść limit.',
        'invalid_reset_token': 'Nieprawidłowy lub wygasły token resetujący',
        'modules_no_organization': 'Użytkownik nie jest przypisany do żadnej organizacji',
        'modules_not_enabled': "Moduł '{module_name}' nie jest włączony dla tej organizacji",
        'invalid_template_module': 'Moduł musi być "{module}"',
        'purge_blocked_by_audit_links': (
            'Pozycja jest powiązana z rekordami audytowymi i nie może zostać '
            'trwale usunięta.'
        ),
        'permanent_delete_disabled': (
            'Trwałe usuwanie jest wyłączone dla tej organizacji.'
        ),
        'documents_approval_workflow_missing': 'Ten dokument wymaga akceptacji, ale nikt nie został jeszcze wyznaczony do jej udzielania. Poproś administratora o ustawienie tego.',
        'category_delete_blocked_by_items': (
            'Nie można usunąć kategorii — jest w użyciu ({count}). Przenieś jej produkty do innej kategorii.'
        ),
        'category_system_field_label_locked': (
            'Nazwa pola "{field}" należy do katalogu produktu i nie może być zmieniona.'
        ),
        'storage_delete_blocked_by_movements': (
            'Nie można usunąć miejsca: odwołuje się do niego {count} ruchów magazynowych. Historia ruchów jest niezmienna — zarchiwizuj to miejsce zamiast go usuwać.'
        ),
        'storage_delete_blocked_by_stock': (
            'Nie można usunąć miejsca: rejestr stanu wciąż ma tu zapas, na którym nie stoi żaden rekord. Zarchiwizuj to miejsce albo najpierw przypisz ten zapas do rekordu.'
        ),
        # Built-in pydantic validation errors (RequestValidationError) —
        # chosen by the error's `type`, filled from its `ctx`, by
        # app.i18n._validation.translate_validation_error.
        'validation_missing': 'To pole jest wymagane',
        'validation_string_too_long': 'Może mieć najwyżej {max_length} znaków',
        'validation_string_too_short': 'Musi mieć co najmniej {min_length} znaków',
        'validation_string_too_long_one': 'Może mieć najwyżej {max_length} znak',
        'validation_string_too_long_few': 'Może mieć najwyżej {max_length} znaki',
        'validation_string_too_short_one': 'Musi mieć co najmniej {min_length} znak',
        'validation_string_too_short_few': 'Musi mieć co najmniej {min_length} znaki',
        'validation_pattern': 'Nie ma oczekiwanego formatu',
        'validation_greater_than_equal': 'Musi być większe lub równe {ge}',
        'validation_greater_than': 'Musi być większe niż {gt}',
        'validation_less_than_equal': 'Musi być mniejsze lub równe {le}',
        'validation_less_than': 'Musi być mniejsze niż {lt}',
        'validation_enum': 'Dozwolone wartości: {expected}',
        'validation_int': 'Musi być liczbą całkowitą',
        'validation_number': 'Musi być liczbą',
        'validation_boolean': 'Musi być prawdą albo fałszem',
        'validation_identifier': 'Musi być poprawnym identyfikatorem',
        'validation_date': 'Musi być poprawną datą',
        'storage_name_collision': (
            'Miejsce o nazwie „{name}" już istnieje na tym poziomie.'
        ),
        'document_return_requires_completed': 'Zwrot można utworzyć tylko do zakończonego dokumentu',
        'document_return_type_not_eligible': 'Zwrot można utworzyć tylko do przyjęcia, wydania lub przesunięcia',
        'document_return_no_lines': 'Zwrot musi mieć co najmniej jeden wiersz',
        'document_original_line_missing': 'Wiersz {line} nie istnieje w dokumencie {number}',
        'document_return_quantity_not_positive': 'Ilość zwracana w wierszu {line} musi być większa od zera',
        'document_return_quantity_exceeds_left': 'Zwrot {quantity} przekracza to, co zostało w wierszu {line} ({left} z {done})',
        'document_correction_requires_completed': 'Korygować można tylko zakończony dokument',
        'document_correction_no_lines': 'Korekta musi mieć co najmniej jeden wiersz',
        'document_correction_below_zero': 'Korekta o {delta} zeszłaby w wierszu {line} poniżej zera — do skorygowania zostało {left} z {done}',
        'document_correction_type_not_correctable': 'Dokumentów tego typu nie można korygować',
        'document_undo_type_not_supported': 'Cofnąć można tylko przyjęcie, wydanie lub przeniesienie',
        'document_undo_requires_completed': 'Cofnąć można tylko zaksięgowany dokument',
        'document_undo_nothing_left': 'Wszystko, co zaksięgował ten dokument, zostało już odwrócone',
        'document_undo_blocked': 'Nie można tego cofnąć: {reason} Wybierz „Popraw”, aby zmienić to, co zostało.',
        'document_undo_stock_used': 'Nie można tego cofnąć: późniejsze ruchy zużyły zaksięgowany stan. Wybierz „Popraw”, aby zmienić to, co zostało.',
        'document_post_already_posted': 'Ten dokument został już zaksięgowany — po raz drugi nic nie zaksięgowano.',
        'document_post_cancelled': 'Ten dokument został anulowany, więc nie można go zaksięgować.',
        'document_filter_unknown': 'Ten filtr jest niedostępny: żaden włączony moduł go nie oferuje ({name}).',
        'document_post_waiting_for_approval': 'Ten dokument już czeka na zatwierdzenie; stan zmieni się po jego zatwierdzeniu.',
        'document_type_requires_target_location': 'Ten typ dokumentu wymaga miejsca docelowego',
        'document_type_requires_source_location': 'Ten typ dokumentu wymaga miejsca źródłowego',
        'document_partner_must_be_supplier_or_manufacturer': 'Kontrahentem przyjęcia musi być dostawca, producent albo klient',
        'document_partner_must_be_customer_or_supplier': 'Kontrahentem wydania musi być klient lub dostawca',
        'document_unit_price_required': 'Każdy wiersz wymaga ceny jednostkowej — brakuje jej w wierszach {lines}',
        'document_preset_unknown': 'Nie ma szablonu o nazwie {name}. Dostępne: {available}',
        'putaway_capacity_exists': 'To miejsce ma już pojemność dla tego produktu — zmień istniejący wpis.',
        'putaway_capacity_not_found': 'Nie znaleziono wpisu pojemności',
        'no_fields_to_update': 'Brak pól do zmiany',
        'putaway_rule_needs_location': 'Reguła rozmieszczania musi wskazywać co najmniej jedno miejsce.',
        'putaway_rule_needs_match_key': 'Reguła rozmieszczania musi mieć co najmniej jeden warunek — produkt, kategorię, tag kontekstu lub typ miejsca.',
        'document_template_wrong_module': 'Szablon dokumentu należy do modułu dokumentów',
        'search_query_empty': 'Wpisz, czego szukasz',
        'document_type_invalid': 'Nie ma typu dokumentu {type}',
        'settings_payload_not_object': 'Ustawienia muszą być przesłane jako obiekt JSON',
        'settings_field_required': 'Ustawienie „{field}” jest wymagane',
        'settings_field_unknown': 'Nieznane ustawienie „{field}”',
        'settings_value_not_string': 'Ustawienie „{path}” musi być tekstem',
        'settings_value_not_integer': 'Ustawienie „{path}” musi być liczbą całkowitą',
        'settings_value_not_number': 'Ustawienie „{path}” musi być liczbą',
        'settings_value_not_boolean': 'Ustawienie „{path}” musi mieć wartość prawda albo fałsz',
        'settings_value_not_object': 'Ustawienie „{path}” musi być obiektem',
        'settings_value_not_array': 'Ustawienie „{path}” musi być listą',
        'settings_text_too_short': 'Ustawienie „{path}” musi mieć co najmniej {limit} znaków',
        'settings_text_too_long': 'Ustawienie „{path}” może mieć najwyżej {limit} znaków',
        'settings_number_too_small': 'Ustawienie „{path}” musi wynosić co najmniej {limit}, podano {value}',
        'settings_number_too_large': 'Ustawienie „{path}” może wynosić najwyżej {limit}, podano {value}',
        'settings_value_not_allowed': 'Ustawienie „{path}” musi mieć jedną z wartości: {allowed} (podano {value})',
        'ai_purpose_unknown': 'Nieznane przeznaczenie AI „{purpose}”',
        'attachment_file_type_invalid': 'Nieprawidłowy typ pliku: {file_type}',
        'not_an_equipment_model': 'To nie jest model sprzętu',
        'bom_line_parent_mismatch': 'Produkt nadrzędny linii nie zgadza się z produktem, który wytwarza ta receptura',
        'bom_cycle_detected': 'Wykryto cykl w recepturze przy {template_id}',
        'margin_negative': 'Marża nie może być ujemna',
        'margin_too_high': 'Marża musi być niższa niż 100%, aby cena była skończona',
        'label_size_invalid': 'Wysokość i szerokość etykiety muszą być większe od zera.',
        'recipe_collection_not_found': 'Kolekcja nie została znaleziona',
        'recipe_collection_parent_not_found': 'Kolekcja nadrzędna nie została znaleziona',
        'recipe_collection_own_parent': 'Kolekcja nie może być własną kolekcją nadrzędną',
        'recipe_collection_under_descendant': 'Kolekcji nie można przenieść pod jej własną podkolekcję',
        'recipe_scrape_failed': 'Nie udało się pobrać przepisu z adresu URL',
        'register_date_from_after_date_to': 'Data początkowa nie może być późniejsza niż data końcowa',
        'meal_plan_end_before_start': 'Data końca nie może być wcześniejsza niż data początku',
        'meal_plan_too_long': 'Plan nie może trwać dłużej niż {days} dni',
        'meal_plan_no_slots': 'Włącz co najmniej jeden posiłek w planie',
        'meal_plan_start_in_past': 'Data początku nie może być w przeszłości',
        'meal_plan_empty': 'Nie można utworzyć listy zakupów z pustego planu',
        'picking_terminate_reason_invalid': 'Nieprawidłowy powód zakończenia: {reason}',
        'recipe_import_name_required': 'Dane importu muszą zawierać nazwę przepisu',
        'recipe_import_data_required': 'Import JSON wymaga danych',
        'recipe_import_unit_unknown': 'Składnik „{ingredient}” używa jednostki „{unit}”, której ta instancja nie zna',
        'recipe_import_unit_missing': 'Składnik „{ingredient}” ma ilość, ale nie ma jednostki',
        'recipe_import_url_required': 'Import z adresu URL wymaga adresu',
        'recipe_scrape_fetch_failed': 'Nie udało się pobrać strony {url} przez Jina Reader: {error}',
        'recipe_scrape_encoding_unsupported': 'Jina Reader zwrócił skompresowaną treść, której nie można bezpiecznie odczytać. Spróbuj innego sposobu importu.',
        'recipe_scrape_empty': 'Jina Reader zwrócił pustą treść dla {url}',
        'recipe_scrape_no_ingredients': 'AI nie znalazła żadnych składników — strona może nie być przepisem',
        'hex_color_invalid': 'Nieprawidłowy kolor szesnastkowy: {color}. Użyj formatu #RGB lub #RRGGBB',
        'shopping_list_nothing_to_convert': 'Brak pozycji do przekształcenia (żadna nie ma szablonu produktu)',
        'stock_take_bulk_item_id_required': 'Zbiorcze liczenie wymaga wskazania produktu (item_id)',
        'cycle_count_scope_location_required': 'Zakres inwentaryzacji cyklicznej musi wskazywać miejsce przechowywania (storage_location_id)',
        'cycle_count_no_matching_items': 'Żaden produkt nie spełnia kryteriów harmonogramu',
        'stock_take_active_for_location': 'Dla tego miejsca przechowywania trwa już inwentaryzacja',
        'category_name_taken': 'Kategoria o tej nazwie już istnieje',
        'invitation_code_invalid': 'Nieprawidłowy lub wygasły kod zaproszenia',
        'invitation_other_address': 'To zaproszenie wystawiono na inny adres e-mail',
        'role_not_found': 'Rola nie została znaleziona',
        'role_other_organization': 'Rola należy do innej organizacji',
        'user_not_in_organization': 'Użytkownik nie należy do tej organizacji',
        'template_other_organization': 'Szablon należy do innej organizacji',
        'template_in_use_by_items': 'Nie można usunąć szablonu: używa go {count} produktów',
        'barcode_already_exists': 'Kod kreskowy {barcode} już istnieje',
        'stock_insufficient_for_template': 'Za mało towaru dla szablonu {template_id}: żądano {requested}, dostępne {available}',
        'stock_lot_not_consumable': 'Partia {lot} ma status {status} i nie można jej zużyć ani zarezerwować',
        'barcode_in_use': 'Kod kreskowy jest już używany: {barcode}',
        'serial_number_exists': 'Numer seryjny już istnieje: {serial_number}',
        'item_currency_mismatch': 'Waluta produktu ({item_currency}) musi być taka sama jak waluta organizacji ({organization_currency})',
        'organization_currency_missing': 'Waluta organizacji nie jest skonfigurowana',
        'item_already_deleted': 'Produkt jest już usunięty',
        'item_not_deleted': 'Produkt nie jest usunięty',
        'item_restore_quantity_unknown': 'Nie można przywrócić produktu: nie znamy jego pierwotnej ilości, bo historia usunięcia jej nie zawiera',
        'item_purge_requires_archived': 'Trwale usunąć można tylko zarchiwizowane produkty',
        'item_purge_reason_required': 'Trwałe usunięcie w środowisku produkcyjnym wymaga podania powodu',
        'relocation_destination_foreign': 'Nie można przenieść produktu: miejsce docelowe nie należy do tej organizacji.',
        'relocation_blocked_by_reservations': 'Nie można przenieść produktu: towar w miejscu źródłowym ma otwarte rezerwacje. Najpierw je zwolnij lub zrealizuj.',
        'short_code_invalid_format': 'Nieprawidłowy format kodu',
        'short_code_duplicate_in_request': 'Powtórzony kod krótki w żądaniu: {short_code}',
        'short_codes_taken': 'Te kody krótkie są już używane w organizacji: {codes}',
        'onboarding_profile_unknown': "Nieznany profil: '{profile}'",
        'storage_vanished_during_batch': 'Miejsce przechowywania {location} zniknęło w trakcie operacji zbiorczej.',
        'storage_archive_blocked_by_items': 'Nie można zarchiwizować: nadal przechowywanych jest tu {count} produktów. Najpierw je przenieś albo zarchiwizuj, wskazując miejsce docelowe.',
        'storage_archive_target_is_self': 'Nie można przenieść produktów do miejsca, które jest właśnie archiwizowane.',
        'storage_archive_target_is_descendant': 'Nie można przenieść produktów do miejsca podrzędnego wobec archiwizowanego.',
        'storage_archive_target_archived': 'Nie można przenieść produktów do zarchiwizowanego miejsca.',
        'storage_restore_parent_archived': 'Nie można przywrócić do zarchiwizowanego miejsca nadrzędnego. Najpierw przywróć miejsce nadrzędne.',
        'storage_delete_blocked_by_references': 'Nie można usunąć miejsca przechowywania: nadal odwołują się do niego inne rekordy (ograniczenie „{constraint}”). Zarchiwizuj je zamiast usuwać.',
        'storage_delete_concurrent_movements': 'Nie można usunąć miejsca: równoległa operacja utworzyła ruchy magazynowe, które się do niego odwołują. Spróbuj ponownie, aby odświeżyć liczbę. Oryginalny błąd: {error}',
        'sole_administrator_cannot_leave': 'Nie możesz opuścić organizacji jako jedyny administrator. Najpierw wyznacz innego administratora.',
        'sole_administrator_role_locked': 'Nie można zmienić roli jedynego administratora. Najpierw awansuj innego członka.',
        'organization_member_limit': 'Osiągnięto limit członków organizacji. Przejdź na Inventari Cloud, aby mieć więcej miejsc.',
        'registration_failed': 'Nie udało się dokończyć rejestracji. Spróbuj ponownie lub skontaktuj się z pomocą.',
        'superuser_required': 'Ta czynność wymaga uprawnień superużytkownika',
        'onboarding_already_completed': 'Wdrożenie jest już ukończone — użyj /switch-profile',
        'module_dependency_cycle': 'Wykryto zależność cykliczną z udziałem modułu „{module}”',
        'module_dependency_cycle_among': 'Wykryto zależność cykliczną między modułami: {modules}',
        'profile_switch_unknown_modules': 'Profil odwołuje się do niezarejestrowanych modułów: {unknown_modules}',
        'profile_switch_modules_not_allowed': 'Moduły niedozwolone dla tej organizacji: {not_allowed_modules}',
        'profile_switch_dependency_unregistered': 'Moduł „{module}” wymaga modułu „{missing_dependency}”, który nie jest zarejestrowany.',
        'focus_mode_module_always_on': 'Moduł „{module}” jest zawsze włączony i nie może być jedynym skupieniem.',
        'focus_mode_module_unregistered': 'Moduł „{module}” nie jest zarejestrowany.',
        'focus_mode_module_not_enabled': 'Moduł „{module}” nie jest włączony dla tej organizacji.',
        'focus_mode_already_active': 'Organizacja jest już skupiona na module „{module}”.',
        'focus_mode_not_active': 'Organizacja nie jest w trybie skupienia na jednym module.',
    },
}
