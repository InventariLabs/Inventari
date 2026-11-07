from app.i18n._types import ErrorMessages

ERRORS_DE: ErrorMessages = {
    'invalid_credentials': 'Ungültige E-Mail oder Passwort',
    'invalid_input': 'Ungültige Eingabe',
    'not_authenticated': 'Nicht authentifiziert',
    'user_already_exists': 'Ein Benutzer mit dieser E-Mail existiert bereits',
    'user_already_in_organization': 'Benutzer gehört bereits einer Organisation an',
    'token_expired': 'Authentifizierungstoken ist abgelaufen',
    'token_invalid': 'Ungültiges Authentifizierungstoken',
    'insufficient_permissions': 'Sie haben keine Berechtigung für diese Aktion',
    'import_create_forbidden': 'Dieses Konto hat die Berechtigungen {permissions} nicht, daher darf der Import keine fehlenden Orte oder Kategorien anlegen. Deaktivieren Sie die entsprechenden Schalter im Importdialog oder fordern Sie die Berechtigung an',
    'import_create_forbidden_one': 'Dieses Konto hat die Berechtigung {permissions} nicht, daher darf der Import keine fehlenden Orte oder Kategorien anlegen. Deaktivieren Sie die entsprechenden Schalter im Importdialog oder fordern Sie die Berechtigung an',
    'import_stubs_forbidden': 'Dieses Konto hat die Berechtigung {permissions} nicht, daher darf der Import keine vorübergehenden Produkte für nicht übereinstimmende Strichcodes anlegen. Deaktivieren Sie das Kontrollkästchen „Stub-Produkte für nicht zugeordnete Barcodes erstellen“ im Importdialog oder fordern Sie die Berechtigung an',
    'user_blocked': 'Ihr Konto wurde gesperrt. Grund: {reason}',
    'user_blocked_no_reason': 'nicht angegeben',
    'uom_not_found': 'Maßeinheit nicht gefunden',
    'import_job_not_found': 'Import nicht gefunden',
    'user_not_found': 'Benutzer nicht gefunden',
    'user_email_required': 'Dieses Konto hat keine E-Mail-Adresse und daher keine zugeordneten Assets.',
    'user_inactive': 'Ihr Konto wartet auf die Freigabe durch einen Administrator.',
    'item_not_found': 'Artikel nicht gefunden',
    'item_quantity_above_ceiling': 'Die Menge {quantity} übersteigt die Kapazität der Spalte — der größte speicherbare Wert ist {ceiling}',
    'item_quantity_raise_in_virtual_location': 'Dieses Produkt steht in {location}, wo der Bestand nicht gezählt wird — erst zurück in ein Regal verschieben, dann die Menge erhöhen',
    'counted_quantity_above_ceiling': 'Die gezählte Menge {quantity} übersteigt die Kapazität der Spalte — der größte speicherbare Wert ist {ceiling}',
    'unknown_bulk_action': 'Unbekannte Sammelaktion: {action}',
    'item_unit_change_blocked_by_stock': 'Dieser Datensatz führt {quantity} {current_unit}. Die Einheit auf {new_unit} zu ändern würde diese Zahl nur neu beschriften, ohne den Bestand im Regal zu ändern. Verbrauchen oder abschreiben Sie ihn zuerst, oder legen Sie einen eigenen Datensatz in der neuen Einheit an.',
    'item_unit_differs_from_template_confirmation_required': '{product} wird in {template_unit} geführt, und diese Menge ist in {chosen_unit} angegeben. Beim Speichern wird sie in {template_unit} umgerechnet — bestätigen Sie also, dass {chosen_unit} gemeint war, oder geben Sie die Menge in {template_unit} ein.',
    'item_unit_not_convertible_to_card': '{product} wird in {template_unit} geführt, und eine Menge in {chosen_unit} lässt sich nicht darin umrechnen. Geben Sie die Menge in {template_unit} ein — oder hinterlegen Sie bei Stück am Produkt, wie viel ein Stück wiegt oder fasst.',
    'bom_line_unit_not_convertible': 'Diese Zutat wird in {stock_unit} geführt, und {line_unit} lässt sich '
    'nicht in {stock_unit} umrechnen. Verwenden Sie eine Einheit derselben '
    'Art, oder hinterlegen Sie am Produkt, wie viel ein {stock_unit} wiegt '
    'oder fasst.',
    'bom_line_self_reference': (
        'Eine Formelposition darf nicht auf das Produkt selbst verweisen — '
        'das Produkt würde damit zur Zutat der eigenen Formel.'
    ),
    'bom_line_cycle': (
        'Diese Zeile würde einen Zyklus schließen: das Produkt würde damit '
        'zur Zutat der eigenen Formel.'
    ),
    'uom_quantity_requires_whole_number': (
        'Die Einheit {unit} nimmt nur ganze Zahlen an, deshalb lässt sich '
        '{quantity} nicht speichern. Runden Sie die Menge auf eine ganze Zahl.'
    ),
    'uom_quantity_too_many_decimal_places': (
        'Die Einheit {unit} nimmt höchstens {places} Nachkommastellen an, '
        'deshalb lässt sich {quantity} nicht speichern. Runden Sie die Menge '
        'auf diese Genauigkeit.'
    ),
    'item_unit_cannot_be_removed': (
        'Die Einheit {unit} lässt sich nicht entfernen: Eine Menge ohne '
        'Einheit sagt nichts. Wählen Sie stattdessen eine andere Einheit.'
    ),
    'removal_strategy_of_shared_product': (
        'Dieses Produkt stammt aus dem gemeinsamen Katalog, daher '
        'gehört die Reihenfolge, in der sein Bestand ausgegeben wird, '
        'dem Katalog und lässt sich nicht für eine einzelne '
        'Organisation ändern.'
    ),
    'piece_unit_missing_from_catalogue': (
        'Der Einheitenkatalog dieser Installation enthält keine Stückeinheit, '
        'also gibt es keine Antwort auf „eine Menge wovon“. Geben Sie die '
        'Einheit ausdrücklich an, oder stellen Sie den Standard-'
        'Einheitenkatalog wieder her.'
    ),
    'equipment_bulk_item_failed': ('Dieses Objekt konnte nicht geändert werden.'),
    'stock_as_of_no_history': (
        'Diese Organisation erfasst keine Lagerbewegungen und hat daher '
        'keine Historie für einen Bericht. Die einzige verfügbare '
        'Antwort sind die heutigen Bestände.'
    ),
    'stock_as_of_before_ledger': (
        'Das Bewegungsjournal beginnt am {starts_at}. Über frühere '
        'Zeiträume ist nichts bekannt — nicht null —, ein Bericht für '
        '{as_of} wäre eine Schätzung.'
    ),
    'stock_as_of_pdf_too_many': (
        'Der Bericht umfasst {total} Produkte — mehr als die {limit} Zeilen, '
        'die ein Ausdruck fasst. Exportieren Sie ihn als Tabelle oder wählen '
        'Sie einen Lagerort, um ihn einzugrenzen.'
    ),
    'item_create_failed': 'Artikel konnte nicht erstellt werden',
    'item_update_failed': 'Artikel konnte nicht aktualisiert werden',
    'item_delete_failed': 'Artikel konnte nicht gelöscht werden',
    'storage_not_found': 'Lagerort nicht gefunden',
    'storage_create_failed': 'Lagerort konnte nicht erstellt werden',
    'storage_update_failed': 'Lagerort konnte nicht aktualisiert werden',
    'storage_delete_failed': 'Lagerort konnte nicht gelöscht werden',
    'storage_delete_failed_items': 'Ein Lagerort mit Artikeln kann nicht gelöscht werden. Verschieben oder löschen Sie die Artikel zuerst.',
    'storage_delete_blocked_by_production_orders': 'Lagerort kann nicht gelöscht werden: Er wird von Produktionsaufträgen verwendet.',
    'storage_type_not_found': 'Lagerorttyp nicht gefunden',
    'storage_type_create_failed': 'Lagerorttyp konnte nicht erstellt werden',
    'storage_type_update_failed': 'Lagerorttyp konnte nicht aktualisiert werden',
    'storage_type_delete_failed': 'Lagerorttyp konnte nicht gelöscht werden',
    'storage_type_exists': 'Ein Lagerorttyp mit diesem Code existiert bereits',
    'storage_type_no_access': 'Sie haben keinen Zugriff auf diesen Lagerorttyp',
    'storage_type_in_use': 'Lagerorttyp wird von {count} Orten verwendet',
    'storage_usage_immutable': 'Der Zweck eines Lagerorts wird vom System festgelegt und kann nicht geändert werden.',
    'storage_type_system_modify': 'System-Lagerorttypen können nicht geändert werden',
    'storage_type_system_delete': 'System-Lagerorttypen können nicht gelöscht werden',
    'category_not_found': 'Kategorie nicht gefunden',
    'category_create_failed': 'Kategorie konnte nicht erstellt werden',
    'category_update_failed': 'Kategorie konnte nicht aktualisiert werden',
    'category_delete_failed': 'Kategorie konnte nicht gelöscht werden',
    'storage_archived': 'Dieser Lagerort ist archiviert. Stellen Sie ihn wieder her, bevor Sie hier Produkte einlagern.',
    'stock_take_not_found': 'Inventur nicht gefunden',
    'stock_take_already_completed': 'Inventur wurde bereits abgeschlossen',
    'stock_take_not_in_progress': 'Inventur ist nicht in Bearbeitung',
    'stock_take_create_failed': 'Inventur konnte nicht erstellt werden',
    'stock_take_update_failed': 'Inventur konnte nicht aktualisiert werden',
    'shopping_list_not_found': 'Einkaufsliste nicht gefunden',
    'shopping_list_create_failed': 'Einkaufsliste konnte nicht erstellt werden',
    'shopping_list_update_failed': 'Einkaufsliste konnte nicht aktualisiert werden',
    'shopping_list_not_writable': 'Diese Einkaufsliste ist {status} und kann nicht geändert werden. Aktivieren Sie sie zuerst wieder.',
    'shopping_list_delete_failed': 'Einkaufsliste konnte nicht gelöscht werden',
    'shopping_list_item_not_found': 'Einkaufslisten-Element nicht gefunden',
    'shopping_list_item_quantity_rounds_to_zero': 'Die Menge {quantity} rundet auf der Speichergenauigkeit zu null — der kleinste speicherbare Wert ist {smallest}',
    'shopping_list_item_quantity_above_ceiling': 'Die Menge {quantity} übersteigt die Kapazität der Spalte — der größte speicherbare Wert ist {ceiling}',
    'shopping_list_item_uom_unknown': 'Unbekannte Maßeinheit (uom_id: {uom_id}) — die Einheit existiert nicht',
    'shopping_list_item_item_unknown': 'Unbekanntes Produkt (item_id: {item_id}) — das Produkt existiert nicht',
    'shopping_list_item_category_unknown': 'Unbekannte Kategorie (category_id: {category_id}) — die Kategorie existiert nicht',
    'shopping_list_item_template_unknown': 'Unbekannte Produktvorlage (template_id: {template_id}) — die Vorlage existiert nicht',
    'organization_not_found': 'Organisation nicht gefunden',
    'organization_create_failed': 'Organisation konnte nicht erstellt werden',
    'organization_update_failed': 'Organisation konnte nicht aktualisiert werden',
    'organization_delete_failed': 'Organisation konnte nicht gelöscht werden',
    'smtp_not_configured': 'Für diese Organisation ist kein E-Mail-Versand eingerichtet',
    'demo_smtp_settings_locked': 'Dies ist die öffentliche Demo, daher ist der Mailserver fest eingestellt: Jede Nachricht, die die App senden würde, wird im Demo-Posteingang aufgefangen. E-Mail-Einstellungen können hier nicht geändert werden.',
    'demo_credentials_locked': 'Dies ist die öffentliche Demo, in der jede E-Mail in einem öffentlichen Postfach landet. Passwörter können hier nicht geändert oder zurückgesetzt werden, und Besucher brauchen kein Konto.',
    'demo_registration_locked': 'Dies ist die öffentliche Demo, in der Besucher kein Konto brauchen. „Zugang anfordern“ gibt es hier nicht — nutzen Sie „Demo ausprobieren“.',
    'role_in_use': 'Diese Rolle ist noch jemandem zugewiesen. Ändern Sie zuerst deren Rolle, dann löschen Sie sie.',
    'role_name_taken': 'Eine Rolle mit dem Namen "{name}" existiert in dieser Organisation bereits.',
    'invitation_not_found': 'Einladung nicht gefunden',
    'organization_invite_invalid': 'Diese Einladung kann nicht verwendet werden. Prüfen Sie, ob Sie sich mit der E-Mail-Adresse registrieren, an die sie gesendet wurde, oder fordern Sie eine neue an.',
    'organization_invite_expired': 'Organisationseinladung ist abgelaufen',
    'email_test_failed': 'Test-E-Mail konnte nicht gesendet werden',
    'module_org_required': 'Um Module zu verwalten, müssen Sie zu einer Organisation gehören. Melden Sie sich erneut an oder wenden Sie sich an den Support.',
    'module_premium_locked': 'Modul „{module}“ ist eine kostenpflichtige Funktion. Wenden Sie sich an die Systemadministration, um es für Ihre Organisation freizuschalten.',
    'module_always_on': 'Modul „{module}“ ist immer aktiv und kann nicht abgeschaltet werden.',
    'module_requires_other': 'Modul „{required}“ muss zuerst aktiviert werden.',
    'module_blocks_dependent': 'Modul „{dependent}“ hängt von „{module}“ ab und ist derzeit aktiv. Deaktivieren Sie zuerst „{dependent}“.',
    'webhook_url_loopback': 'Diese Adresse zeigt auf den Server selbst ({host}); der Aufruf würde die Maschine nie verlassen. Verwenden Sie eine aus dem Internet erreichbare Adresse oder bitten Sie die Person, die diese Installation betreibt, lokale Adressen zuzulassen (Einstellung WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'webhook_url_private': 'Diese Adresse ({host}) ist nicht öffentlich routbar oder für Protokollinfrastruktur reserviert; solche Aufrufe verweigert der Server. Verwenden Sie eine aus dem Internet erreichbare Adresse oder bitten Sie die Person, die diese Installation betreibt, lokale Adressen zuzulassen (Einstellung WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'webhook_url_unresolved': 'Der Hostname „{host}“ ließ sich nicht auflösen, die Adresse ist also nicht prüfbar. Verwenden Sie einen öffentlich auflösbaren Namen oder bitten Sie die Person, die diese Installation betreibt, lokale Adressen zuzulassen (Einstellung WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'webhook_url_rebinding': 'Der Hostname „{host}“ löst auf eine Adresse auf, die nicht öffentlich routbar oder für Protokollinfrastruktur reserviert ist ({resolved}). Verwenden Sie eine aus dem Internet erreichbare Adresse oder bitten Sie die Person, die diese Installation betreibt, lokale Adressen zuzulassen (Einstellung WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'reg_request_new_title': 'Neue Zugriffsanfrage',
    'reg_request_new_content': 'Benutzer {name} beantragt Zugriff auf das System.',
    'reg_request_approved_title': 'Anfrage genehmigt',
    'reg_request_approved_content': 'Zugriff für {email} wurde von {admin} genehmigt.',
    'reg_link_undelivered_title': 'Registrierungslink nicht zugestellt',
    'reg_link_undelivered_content': 'Die E-Mail mit dem Registrierungslink an {email} konnte nicht zugestellt werden. Geben Sie ihm diesen Link selbst weiter: {link}',
    'reg_request_rejected_title': 'Anfrage abgelehnt',
    'reg_request_rejected_content': 'Zugriff für {email} wurde von {admin} abgelehnt.',
    'reconciliation_drift_title': 'Bestandsabweichung erkannt',
    'reconciliation_drift_content': (
        'Der geplante Bestandsabgleich hat Zahlen gefunden, die nicht '
        'übereinstimmen — {pairs}. Siehe: Statistiken → Abgleich.'
    ),
    'reconciliation_drift_standing_title': 'Bestandsabweichung besteht weiter',
    'reconciliation_drift_standing_content': (
        'Die früher gemeldete Abweichung hat sich nicht geändert und '
        'besteht weiter — {pairs}. Siehe: Statistiken → Abgleich.'
    ),
    'reconciliation_pair_quant_ledger': 'Regal vs. Bewegungsjournal: {count}',
    'reconciliation_pair_layer_quant': 'Kostenhistorie vs. Regal: {count}',
    'event_delivery_dead_title': 'Eine Hintergrundaufgabe schlägt wiederholt fehl',
    'event_delivery_dead_content': (
        'Der Handler {handler} für das Ereignis {event} ist {attempts}-mal fehlgeschlagen und wurde angehalten. Letzter Fehler: {error}. Das Ereignis bleibt zur Prüfung in event_deliveries erhalten.'
    ),
    'field_required': 'Dieses Feld ist erforderlich',
    'invalid_email': 'Ungültiges E-Mail-Format',
    'password_too_short': 'Passwort muss mindestens 8 Zeichen lang sein',
    'password_invalid': 'Passwort muss mindestens einen Großbuchstaben, einen Kleinbuchstaben und eine Ziffer enthalten',
    'password_too_long': 'Das Passwort darf höchstens {max_bytes} Bytes lang sein',
    'password_needs_lowercase': 'Das Passwort muss mindestens einen Kleinbuchstaben enthalten',
    'password_needs_uppercase': 'Das Passwort muss mindestens einen Großbuchstaben enthalten',
    'password_needs_digit': 'Das Passwort muss mindestens eine Ziffer enthalten',
    'sku_format_invalid': 'Die SKU darf nur Buchstaben, Ziffern, Bindestriche, Unterstriche und Schrägstriche enthalten',
    'sku_in_use': 'Die SKU {sku} gehört schon zu einem anderen Produkt',
    'custom_field_required': 'Das Feld „{field}“ ist erforderlich',
    'field_multi_select_shape': 'Das Feld „{field}“ muss eine Liste von Optionen sein',
    'field_option_not_allowed': 'Der Wert „{value}“ gehört nicht zu den Optionen des Felds „{field}“: {options}',
    'field_money_shape': 'Das Feld „{field}“ muss einen Betrag und eine Währung enthalten, sonst nichts',
    'field_money_amount': 'Der Betrag im Feld „{field}“ muss eine Zahl sein',
    'field_money_currency': 'Die Währung im Feld „{field}“ muss ein dreibuchstabiger ISO-4217-Code sein, z. B. EUR',
    'field_select_shape': 'Das Feld „{field}“ muss genau eine Option enthalten',
    'item_limit_reached': 'Diese Organisation hat das Artikellimit erreicht. Wechseln Sie zu Inventari Cloud.',
    'item_archived': 'Der Artikel ist archiviert und kann aus dem Archiv wiederhergestellt werden',
    'announcement_type_invalid': 'Ungültiger Ankündigungstyp. Erlaubt: {allowed}',
    'ai_provider_invalid': 'Ungültiger Anbieter. Erlaubt: {allowed}',
    'field_options_required': 'Ein Feld vom Typ {type} braucht eine nicht leere Liste von Optionen',
    'member_role_exactly_one': 'Geben Sie genau eines von role oder role_id an',
    'reason_blank': 'Der Grund darf nicht leer sein',
    'discrepancy_reason_required': 'Ein Grund für die Abweichung ist erforderlich',
    'invalid_uuid': 'Ungültiges UUID-Format',
    'sheet_unreadable': 'Diese Datei konnte nicht als Tabelle gelesen werden. Prüfen Sie, ob es eine gültige .xlsx- oder .csv-Datei ist, und versuchen Sie es erneut.',
    'pasted_text_unreadable': 'Der eingefügte Text konnte nicht als Tabelle gelesen werden. Fügen Sie aus einer Tabelle kopierte Zeilen mit jeweils gleich vielen Spalten ein.',
    'webhook_url_malformed': 'Das ist keine gültige Webadresse. Geben Sie eine vollständige Adresse ein, z. B. https://example.com/hook.',
    'recipe_extraction_failed': 'Das Rezept konnte von dieser Seite nicht extrahiert werden. Versuchen Sie es erneut oder geben Sie das Rezept von Hand ein.',
    'invalid_date': 'Ungültiges Datumsformat',
    'value_must_be_positive': 'Wert muss positiv sein',
    'value_must_be_greater_than_zero': 'Wert muss größer als Null sein',
    'insufficient_quantity': 'Nicht genügend Bestand für diese Aktion',
    'file_type_not_allowed': 'Dateityp nicht erlaubt',
    'file_signature_mismatch': 'Dateisignatur stimmt nicht mit dem deklarierten Dateityp überein',
    'file_too_large': 'Datei überschreitet die maximal erlaubte Größe (10 MB)',
    'file_type_not_allowed_list': 'Dateityp nicht erlaubt. Erlaubt: {allowed}',
    'file_content_type_missing': 'Die Datei gibt ihren Typ nicht an (der Content-Type-Header fehlt).',
    'file_empty': 'Die Datei ist leer.',
    'file_not_webp': 'Diese Datei ist kein gültiges WebP-Bild.',
    'import_too_many_rows': 'Die Datei hat {count} Zeilen; das Limit liegt bei {limit}. Teilen Sie sie in kleinere Dateien auf.',
    'storage_location_ambiguous': '„{text}“ passt zu {count} Lagerorten ({shown}). Geben Sie stattdessen den Pfad an, z. B. „{example}“.',
    'pagination_cursor_invalid': 'Ungültiger oder abgelaufener Paginierungs-Cursor',
    'webhook_url_scheme': 'Für Webhooks sind nur {schemes}-Adressen erlaubt.',
    'webhook_url_no_hostname': 'Die Webhook-Adresse muss einen Hostnamen enthalten, z. B. https://example.com/hook.',
    'picking_already_picked': '{name} wurde bereits gepickt',
    'picking_unit_mismatch': (
        'Einheiten für {name} sind nicht vergleichbar — Rezept und Bestand '
        'verwenden unterschiedliche Maße. Hinterlegen Sie, wie viel eine '
        'Bestandseinheit wiegt oder fasst, und scannen Sie erneut.'
    ),
    'picking_picked': '{name} ✓ — {quantity} werden abgezogen',
    'invalid_mapping_json': 'Ungültiges Mapping-JSON',
    'extra_cost_not_a_receipt': 'Nebenkosten gehören zu einem Wareneingang: nur eingehende Ware kann die Kosten ihrer Anlieferung tragen.',
    'extra_cost_document_posted': (
        'Dieser Wareneingang ist bereits gebucht, daher können keine Nebenkosten mehr hinzugefügt werden: die Ware kann das Lager verlassen haben und es gibt nichts mehr zu belasten. Erstellen Sie stattdessen eine Korrektur im offenen Zeitraum.'
    ),
    'extra_cost_currency_mismatch': (
        'Die Nebenkosten lauten auf eine andere Währung als das Dokument. Geben Sie sie in der Dokumentwährung an — eine Umrechnung zu einem nicht erfassten Kurs setzt eine Zahl ohne Historie in den Lagerwert.'
    ),
    'document_shipment_dispatch_only': 'Ein Versand wird nur bei einem Warenausgang erfasst: Der Spediteur übernimmt Ware, die das Lager verlässt.',
    'document_tracking_template_invalid': 'Der Sendungsverfolgungslink für „{carrier}“ muss eine Webadresse sein, die mit https:// oder http:// beginnt und {{tracking_number}} an der Stelle der Nummer enthält.',
    'packing_not_a_dispatch': 'Gepackt wird nur ein Warenausgang: Pakete enthalten Ware, die das Lager verlässt.',
    'packing_document_not_open': 'Pakete können nur geändert werden, solange der Warenausgang bestätigt und noch nicht abgeschlossen ist. Ein abgeschlossener Warenausgang behält seine Pakete so, wie sie versandt wurden.',
    'packing_exceeds_picked': '{name}: nur {remaining} kommissioniert und noch nicht verpackt. Ein Paket enthält, was kommissioniert wurde, und nichts, was schon in einem anderen Paket liegt.',
    'packing_exceeds_done': '{name}: Die Pakete enthalten {packed}, mehr als die {done}, die dieser Warenausgang versendet. Nehmen Sie die Differenz zuerst aus den Paketen oder schließen Sie mit der Menge ab, die sie enthalten.',
    'packing_nothing_to_pack': 'Alles Kommissionierte ist bereits verpackt, für ein neues Paket bleibt nichts übrig.',
    'packing_no_packages': 'Dieser Warenausgang hat noch keine Pakete, daher gibt es keine Packliste zu drucken. Packen Sie ihn zuerst.',
    'package_not_found': 'Paket nicht gefunden',
    'packing_scan_unrecognized': 'Kein Produkt trägt den Code {code}. Scannen Sie den Barcode des Produkts selbst oder tippen Sie auf seine Position, um es zu verpacken.',
    'packing_scan_not_in_document': '{name} gehört nicht zu diesem Warenausgang und kommt daher in keines seiner Pakete.',
    'invalid_image_extension': 'Ungültige Bild-Erweiterung',
    'invalid_role': 'Ungültige Rolle. Erlaubt: {roles}',
    'role_not_in_organization': 'Rolle gehört nicht zu dieser Organisation',
    'failed_to_read_file': 'Datei konnte nicht gelesen werden: {error}',
    'only_image_files_allowed': 'Nur Bilddateien sind erlaubt (jpg, png, gif, webp)',
    'image_unreadable': 'Diese Datei konnte nicht als Bild gelesen werden',
    'image_too_large': 'Bild zu groß (max. {limit})',
    'demo_upload_file_limit': 'Die Demo nimmt Dateien bis {limit} an',
    'demo_upload_total_limit': 'Die Demo hat ihr Upload-Limit erreicht ({limit}). Nach dem nächsten Reset sind Uploads wieder möglich',
    'demo_sandbox_cap_reached': 'Die Demo hat für heute alle Kopien vergeben. Bitte kommen Sie morgen wieder',
    'demo_sandbox_pool_empty': 'Alle Demo-Kopien sind gerade vergeben, neue werden vorbereitet. Versuchen Sie es in einer Minute erneut',
    'barcode_or_sku_required': 'Entweder barcode- oder sku-Parameter ist erforderlich',
    'barcode_names_one_record': 'Ein Barcode kann nicht {count} Datensätze benennen: {barcode}',
    'storage_no_short_code': 'Lagerort hat keinen Kurzcode. Generieren Sie zuerst einen.',
    'refresh_token_expired_grace': 'Refresh-Token außerhalb der Kulanzzeit abgelaufen',
    'refresh_token_revoked': 'Refresh-Token wurde widerrufen',
    'cannot_remove_yourself': 'Sie können sich nicht selbst entfernen',
    'cannot_change_own_role': 'Sie können Ihre eigene Rolle nicht ändern',
    'label_in_use_by_product': 'Ein Etikett, das einem aktiven Produkt zugewiesen ist, kann nicht gelöscht werden. Löschen Sie zuerst das Produkt.',
    'label_already_assigned': 'Etikett ist bereits zugewiesen',
    'no_labels_available': 'Keine Etiketten zum Drucken verfügbar',
    'unauthorized': 'Authentifizierung erforderlich',
    'forbidden': 'Zugriff verweigert',
    'organization_required': 'Organisation erforderlich',
    'not_found': 'Ressource nicht gefunden',
    'conflict': 'Ressourcenkonflikt',
    'internal_error': 'Ein interner Fehler ist aufgetreten',
    'rate_limit_exceeded': 'Zu viele Anfragen. Versuchen Sie es später erneut.',
    'service_unavailable': 'Dienst vorübergehend nicht verfügbar',
    'stock_take_edit_completed': 'Eine abgeschlossene oder stornierte Inventur kann nicht bearbeitet werden',
    'stock_take_delete_completed': 'Nur Entwürfe oder aktive Inventuren können gelöscht werden',
    'stock_take_not_active': 'Inventur ist nicht aktiv',
    'stock_take_surplus_item_id_required': 'Wählen Sie das Produkt, zu dem dieser Überschussposten gehört.',
    'stock_take_surplus_quantity_required': 'Geben Sie die gezählte Menge für diesen Überschussposten ein.',
    'stock_lot_not_found': 'Charge nicht gefunden',
    'stock_moves_export_too_many': '{total} Bewegungen passen — mehr, als ein Tabellenblatt mit {limit} fasst. Grenzen Sie Zeitraum, Ort oder Produkt weiter ein und exportieren Sie erneut.',
    'stock_take_close_requires_finalize': 'Eine Inventur wird durch den Abschluss beendet (POST /stock-takes/{id}/complete), nicht durch eine Statusänderung',
    'period_already_closed': 'Die Periode {period} ist bereits geschlossen.',
    'period_closed_for_date': 'Die Periode {period} ist geschlossen, daher kann nichts darin datiert werden. Ändern Sie das Belegdatum oder bitten Sie jemanden, der die Periode wieder öffnen darf.',
    'period_closed_for_stock_change': 'Die Periode {period} ist geschlossen, daher kann darin kein Bestand gebucht werden. Bitten Sie jemanden, der die Periode wieder öffnen darf.',
    'transfer_more_than_the_record_holds': 'Der Datensatz „{item_name}“ enthält {available}, die Zeile verschiebt {requested}. Verringern Sie die Menge der Zeile oder verschieben Sie den Rest aus einem anderen Datensatz.',
    'transfer_cannot_split_serialized_record': 'Die Verschiebung kann den serialisierten Datensatz {serial_number} nicht teilen; verschieben Sie den ganzen Datensatz.',
    'use_partially_more_than_left': 'Der Datensatz „{item_name}“ enthält {available} dieser Packung, angegeben wurde ein Rest von {requested}. Geben Sie an, wie viel übrig ist – mehr als vorhanden ist nicht möglich.',
    'use_partially_serialized': 'Der serialisierte Datensatz {serial_number} kann nicht geöffnet und geteilt werden; verbrauchen Sie ihn ganz.',
    'use_partially_needs_counted_unit': '„{item_name}“ wird in einer Maßeinheit geführt, es gibt also keine Packung zu öffnen. Ziehen Sie die verbrauchte Menge vom Bestand ab.',
    'use_partially_pack_has_no_measure': '„{item_name}“ wird in Packungen gezählt und das Produkt gibt nicht an, wie viel eine enthält; erfassen lässt sich nur „geöffnet“ oder „aufgebraucht“.',
    'use_by_needs_open_package': 'Der Datensatz „{item_name}“ ist verschlossen und hat daher kein Verbrauchsdatum. Öffnen Sie ihn zuerst; bis dahin gilt das Datum der Charge.',
    'period_not_closed': 'Die Periode {period} ist nicht geschlossen.',
    'wms_session_now_held_by': 'Diese Sitzung liegt jetzt bei {owner}; von hier aus werden keine Scans mehr angenommen.',
    'wms_session_held_by_other_user': 'Eine aktive Sitzung eines anderen Benutzers liegt für dieses Dokument vor (eröffnet von {owner}).',
    'wms_pick_document_not_found': 'Das Dokument {document} wurde in dieser Organisation nicht gefunden, daher wurde die Kommissioniersitzung nicht gestartet.',
    'wms_pick_document_not_confirmed': 'Das Dokument {number} ist nicht bestätigt, daher wurde die Kommissioniersitzung nicht gestartet. Nur bestätigte Dokumente können kommissioniert werden.',
    'wms_pick_document_not_dispatch': 'Das Dokument {number} ist kein Warenausgang, daher wurde die Kommissioniersitzung nicht gestartet. Nur Warenausgänge können gemeinsam kommissioniert werden.',
    'wms_pick_document_in_session': 'Das Dokument {number} wird bereits in einer anderen Sitzung kommissioniert (eröffnet von {owner}), daher wurde die Kommissioniersitzung nicht gestartet.',
    'wms_line_document_closed': 'Das Dokument {number} ist {status}, daher können seine Zeilen in dieser Sitzung nicht mehr geändert werden.',
    'wms_short_below_scanned': 'Die endgültige Menge darf nicht unter der gescannten Menge ({scanned}) liegen; um weniger zu erfassen, muss sie die Scans ersetzen.',
    'wms_short_pick_needs_outcome': 'Eine zu wenig entnommene Zeile braucht einen Grund: „Fehlmenge“ lässt den Rest als Nachlieferung offen, jeder andere Grund schließt die Differenz.',
    'wms_session_not_found': 'Die aktive Sitzung wurde nicht gefunden. Vielleicht wurde sie bereits abgeschlossen oder abgebrochen.',
    'wms_line_not_found': 'Die Sitzungszeile wurde nicht gefunden.',
    'wms_line_not_pending': 'Die Sitzungszeile wurde nicht gefunden oder ist nicht mehr offen.',
    'wms_quantity_cannot_be_negative': 'Die Menge darf nicht negativ sein.',
    'wms_quantity_above_expected': 'Die Menge darf die erwartete Menge nicht überschreiten.',
    'wms_cannot_complete_no_lines': 'Die Sitzung kann nicht abgeschlossen werden: Sie hat keine Zeilen.',
    'wms_cannot_complete_lines_pending': 'Die Sitzung kann nicht abgeschlossen werden: {count} Zeile(n) sind noch offen.',
    'wms_cannot_complete_destination_not_scanned': 'Die Sitzung kann nicht abgeschlossen werden: Das Zielregal wurde noch nicht gescannt.',
    'wms_document_not_confirmed': 'Das Dokument wurde nicht gefunden oder ist nicht bestätigt.',
    'wms_document_type_not_supported': 'Diese Sitzung verarbeitet keine Dokumente vom Typ {document_type}.',
    'wms_nothing_to_undo': 'Für diese Zeile ist nichts zum Rückgängigmachen erfasst.',
    'wms_undo_line_is_packed': '{name}: Ein Paket enthält bereits {packed} der kommissionierten Ware. Nehmen Sie sie zuerst aus dem Paket, machen Sie dann die Kommissionierung rückgängig.',
    'wms_skip_line_is_packed': '{name}: Ein Paket enthält bereits {packed} der kommissionierten Ware. Nehmen Sie sie zuerst aus dem Paket, überspringen Sie dann die Position.',
    'wms_cancel_session_is_packed': '{name}: Ein Paket enthält bereits {packed} der kommissionierten Ware. Nehmen Sie sie zuerst aus dem Paket, brechen Sie dann die Sitzung ab.',
    'wms_barcode_required': 'Scannen Sie zuerst einen Barcode.',
    'document_execution_line_foreign': 'Diese Ausführungszeile gehört nicht zu diesem Dokument.',
    'document_execution_line_repeated': 'Jede Dokumentzeile kann nur einmal ausgeführt werden.',
    'document_done_quantity_negative': 'Die ausgeführte Menge darf nicht negativ sein: {quantity}.',
    'document_done_quantity_above_expected': 'Die ausgeführte Menge {quantity} überschreitet die erwartete Menge (max. {expected}).',
    'document_held_quantity_negative': 'Die zurückgehaltene Menge darf nicht negativ sein: {quantity}.',
    'document_held_quantity_above_received': 'Die zurückgehaltene Menge {quantity} überschreitet die erhaltene Menge ({received}).',
    'document_held_quantity_needs_receipt': 'Nur ein Wareneingang kann Ware zurückhalten.',
    'document_held_quantity_needs_code': 'Eine zurückgehaltene Menge braucht den Code Beschädigung oder Qualitätssperre.',
    'document_partial_needs_discrepancy_code': 'Eine teilweise Ausführung braucht einen Abweichungscode.',
    'document_correction_above_expected': 'Eine Korrektur von {quantity} überschreitet die erwartete Menge {expected} in absoluten Werten.',
    'document_correction_sign_mismatch': 'Eine Korrektur muss das Vorzeichen der erwarteten Differenz behalten: {quantity} gegenüber {expected}.',
    'document_correction_missing_original': 'Diese Korrektur nennt nicht das Dokument, das sie korrigiert.',
    'document_correction_original_not_found': 'Das korrigierte Dokument {document} wurde nicht gefunden.',
    'document_correction_would_go_negative': 'Die Korrektur würde {item} unter null bringen: aktuell {current}, Änderung {delta}, Ergebnis {result}.',
    'document_adjustment_would_go_negative': 'Die Bestandskorrektur würde {item} unter null bringen: aktuell {current}, Änderung {delta}, Ergebnis {result}.',
    'document_line_needs_identity': 'Die Dokumentzeile muss einen Datensatz, ein Produkt oder einen Namen nennen.',
    'document_rework_wrong_status': 'Ein Dokument im Status {status} kann nicht in den Entwurf zurückgeführt werden; nur ein bestätigtes oder ein zur Freigabe anstehendes Dokument kann das.',
    'stock_record_not_found': 'Der Datensatz {item} wurde nicht gefunden.',
    'stock_product_not_found': 'Das Produkt {product} wurde nicht gefunden.',
    'stock_insufficient_record': 'Nicht genug Bestand für „{item}“: verfügbar {available}, angefordert {requested}.',
    'receipt_needs_target_location': 'Der Wareneingangsbeleg hat keinen Zielort.',
    'receipt_needs_quarantine_location': 'Der Wareneingang enthält beschädigte oder qualitätsgesperrte Ware, aber im Belegprofil ist kein Quarantäneort festgelegt. Legen Sie ihn in den Belegeinstellungen fest.',
    'transfer_needs_target_location': 'Der Umlagerungsbeleg hat keinen Zielort.',
    'receiving_mode_needs_a_warehouse': 'Nur ein Lagerort der obersten Ebene wählt, wie er Ware annimmt.',
    'putaway_needs_another_location': 'Die Ware steht bereits hier: wähle den Lagerort, an den sie kommt.',
    'replenishment_nothing_to_move': 'Es gibt nichts aus der Reserve zu holen: Die Ware ist dort nicht mehr, oder das Regal braucht sie nicht mehr.',
    'replenishment_shelf_scan_required': 'Scannen Sie den Reserve-Lagerort, dem Sie die Ware entnehmen.',
    'replenishment_shelf_scan_mismatch': 'Der Code nennt einen anderen Lagerort: Scannen Sie den Reserve-Lagerort, dem die Ware entnommen wird.',
    'putaway_shelf_scan_required': 'Scanne vor dem Einlagern das Etikett des Lagerorts.',
    'home_shelf_receiving': 'Ein Wareneingangsbereich kann kein Stammplatz sein: Ware wartet dort nur.',
    'home_shelf_quarantine': 'Ein Quarantäne-Lagerort kann kein Stammplatz sein: Zurückgehaltene Ware wird dort nicht aufbewahrt.',
    'home_shelf_not_stock': 'Dieser Lagerort nimmt keinen Bestand auf und kann deshalb kein Stammplatz sein.',
    'stock_take_status_unchangeable': 'Statuswechsel von {current} zu {new} ist nicht möglich.',
    'api_keys_limit_reached': 'Die Organisation hat bereits {count} aktive API-Schlüssel, das ist das Maximum. Widerrufen Sie einen, um einen neuen zu erstellen.',
    'document_pdf_requires_confirmed': 'Ein PDF entsteht aus einem bestätigten oder abgeschlossenen Beleg. Dieser hat den Status {status}.',
    'documents_pdf_require_confirmed': 'Ein gemeinsames PDF entsteht nur aus bestätigten oder abgeschlossenen Belegen. Nicht druckbar: {numbers}.',
    'stock_take_item_not_found': 'Inventurposition nicht gefunden',
    'stock_take_item_already_exists': 'Artikel wurde dieser Inventur bereits hinzugefügt',
    'stock_take_item_outside_location': 'Dieser Artikel liegt außerhalb des inventierten Lagerorts; ihn hier zu zählen würde den dortigen Bestand überschreiben',
    'stock_take_shelf_outside_location': 'Dieser Lagerort gehört nicht zur Inventur von {location}',
    'stock_take_uncounted_items': '{count} ungezählte Positionen verbleiben',
    'stock_none_at_location': 'Am Ort {location} gibt es kein {product}.',
    'stock_all_batches_held': 'Jede Charge von {product} am Ort {location} ist in Quarantäne oder gesperrt, also lässt sich nichts davon verwenden.',
    'stock_not_enough': 'Am Ort {location} sind {available} von {product} verfügbar, angefragt wurden {requested}.',
    'stock_take_over_cap': 'Bei {count} Position(en) liegt die gezählte Menge weit über dem Systembestand. Prüfen Sie sie und bestätigen Sie, um die gezählten Mengen zu speichern.',
    'stock_take_over_tolerance': 'Bei {count} Position(en) weicht die gezählte Menge stärker vom Systembestand ab, als die Toleranz dieser Inventur zulässt. Vor dem Buchen muss jemand mit der entsprechenden Berechtigung sie annehmen.',
    'stock_take_tolerance_reason_missing': 'Bei {count} Position(en) liegt die Abweichung über der Toleranz und es fehlt der Grund. Geben Sie für jede einen Grund an und schließen Sie die Inventur dann ab.',
    'stock_take_tolerance_not_allowed': 'Eine Abweichung über der Toleranz anzunehmen erfordert die Berechtigung zur Inventurfreigabe.',
    'stock_take_awaiting_recount': 'Bei {count} Position(en) wurde eine erneute Zählung angefordert. Zählen Sie sie noch einmal und schließen Sie die Inventur dann ab.',
    'stock_take_stock_moved': '{count} Position(en) wurden gegen einen Bestand gezählt, den das Lager nicht mehr hat. Sie wurden zur erneuten Zählung zurückgeschickt.',
    'document_not_found': 'Dokument nicht gefunden',
    'work_item_not_found': 'Aufgabe nicht gefunden',
    'work_item_taken': 'Jemand anderes hat diese Aufgabe gerade übernommen.',
    'pdf_generation_failed': 'PDF-Generierung fehlgeschlagen',
    'import_only_draft': 'Zeilen können nur in ENTWURFS-Dokumente importiert werden',
    'paste_empty': 'Keine Zeilen zu importieren — fügen Sie mindestens eine Kopfzeile und eine Datenzeile ein',
    'import_asset_name_missing': 'Fehlender Objektname',
    'import_line_name_missing': 'Fehlender Produktname',
    'import_location_unresolved': 'Lagerort konnte nicht zugeordnet werden',
    'import_location_not_found': 'Kein Ort heißt „{value}“',
    'import_price_invalid': 'Spalte „{column}“: „{value}“ ist kein Preis',
    'import_date_invalid': 'Spalte „{column}“: „{value}“ ist kein Datum',
    'import_job_failed': 'Der Import wurde wegen eines unerwarteten Fehlers abgebrochen.',
    'import_job_interrupted': 'Der Import wurde unterbrochen, bevor er fertig war.',
    'import_column_not_a_number': 'Spalte „{column}“: „{value}“ ist keine Zahl',
    'import_quantity_not_positive': 'Spalte „{column}“: Die Menge muss größer als null sein, „{value}“ ist es nicht',
    'import_column_location_not_found': 'Spalte „{column}“: Lagerort „{value}“ nicht gefunden',
    'import_column_category_not_found': 'Spalte „{column}“: Kategorie „{value}“ nicht gefunden',
    'import_unknown_unit': 'Spalte „{column}“: unbekannte Einheit „{value}“. Bekannte Einheiten: {units}',
    'import_column_not_yes_no': 'Spalte „{column}“: „{value}“ ist weder Ja noch Nein',
    'import_column_not_in_options': 'Spalte „{column}“: „{value}“ ist keine der Auswahlmöglichkeiten: {options}',
    'import_column_quantity_blank': 'Spalte „{column}“: Die Menge ist leer. Tragen Sie sie ein oder entfernen Sie die Mengenzuordnung, damit jede Zeile als 1 importiert wird',
    'import_column_field_shape': 'Spalte „{column}“: Der Wert passt nicht zum Feld, dem die Spalte zugeordnet ist',
    'import_field_required_unreadable': 'Das Feld „{field}“ ist erforderlich und kann nicht aus einer Zelle gelesen werden',
    'import_field_required_no_column': 'Das Feld „{field}“ ist erforderlich und die Datei hat keine Spalte dafür',
    'import_column_field_required': 'Spalte „{column}“: Das Feld ist erforderlich',
    'import_column_reason': 'Spalte „{column}“: {reason}',
    'import_row_failed': 'Die Zeile konnte nicht importiert werden',
    'document_lines_quantity_not_positive': 'Die Zeilen {lines} haben eine Menge von null oder weniger. Korrigieren Sie sie vor der Bestätigung.',
    'document_delivery_lines_reference_items': 'Positionen eines Auslieferungsbelegs müssen sich auf vorhandene Produkte beziehen',
    'document_scrap_lines_reference_items': 'Positionen eines Ausschussbelegs müssen sich auf vorhandene Produkte beziehen',
    'document_reason_scrap_only': 'Nur ein Ausschussbeleg kann einen Verschrottungsgrund tragen',
    'document_scrap_reason_required': 'Ein Ausschussbeleg sagt, warum die Ware ausgebucht wird: Wählen Sie einen Grund, und bei „Sonstiges“ schreiben Sie ihn in die Anmerkungen',
    'document_transfer_lines_reference_items': 'Positionen eines Umlagerungsbelegs müssen sich auf vorhandene Produkte beziehen',
    'document_correction_lines_reference_items': 'Positionen eines Korrekturbelegs müssen sich auf vorhandene Produkte beziehen',
    'document_adjustment_lines_reference_items': 'Positionen eines Bestandskorrekturbelegs müssen sich auf vorhandene Produkte beziehen',
    'recipe_collection_name_taken': 'Eine Rezeptsammlung mit dem Namen „{name}“ existiert in dieser Organisation bereits.',
    'recipe_name_taken': 'Eine Formel mit diesem Namen existiert für dieses Produkt bereits.',
    'recipe_not_found': 'Rezept nicht gefunden',
    'picking_active_recipe_locked': 'Zutaten können nicht bearbeitet werden, solange eine Kommissionierungssitzung aktiv ist. Brechen Sie die Sitzung zuerst ab oder schließen Sie sie ab.',
    'meal_plan_dates_exclude_entries': 'Entfernen Sie zuerst die Einträge an den ausgeschlossenen Tagen.',
    'meal_plan_position_taken': 'In dieser Mahlzeit konnte keine freie Position gefunden werden.',
    'meal_plan_entry_date_out_of_range': 'Das Datum des Eintrags liegt außerhalb des Zeitraums des Plans.',
    'meal_plan_slot_not_enabled': 'Diese Mahlzeit ist für diesen Plan nicht aktiviert.',
    'shopping_exclusion_exists': 'Dieser Ausschluss existiert bereits.',
    'shopping_item_already_purchased': 'Dieser Artikel ist bereits als gekauft markiert.',
    'shopping_item_already_purchased_reset': 'Dieser Artikel ist bereits als gekauft markiert. Markieren Sie ihn zuerst als nicht gekauft, um ihn zu ändern.',
    'shopping_list_not_editable': 'Eine abgeschlossene oder archivierte Einkaufsliste kann nicht bearbeitet werden.',
    'shopping_lists_module_disabled': 'Das Modul Einkaufslisten ist für diese Organisation nicht aktiviert.',
    'maker_recipe_not_found': 'Formel nicht gefunden',
    'uom_quantity_non_negative': 'Die Menge darf nicht negativ sein',
    'uom_conversion_unavailable': (
        'Die Menge in der Einheit {unit} lässt sich nicht in die '
        'Lagereinheit {stock_unit} umrechnen'
    ),
    'webhook_not_found': 'Webhook nicht gefunden',
    'putaway_rule_not_found': 'Einlagerungsregel nicht gefunden',
    'document_line_not_found': 'Dokumentenposition nicht gefunden',
    'putaway_unknown_context_tag': 'Unbekannte Kategoriegruppe „{value}“ — wählen Sie eine, die eine bestehende Kategorie definiert',
    'putaway_unknown_storage_type': 'Unbekannter Lagertyp „{value}“ — wählen Sie einen der Lagertypen der Organisation',
    'location_not_internal': '„{name}“ ist ein virtueller Lagerort — Ware kann nur in echte Lagerorte eingelagert werden',
    'location_archived': '„{name}“ ist archiviert — stellen Sie es zuerst wieder her oder wählen Sie einen Lagerort, den die Listen noch zeigen',
    'line_target_receipt_only': 'Ein Ziel kann nur auf Wareneingangspositionen benannt werden — Warenausgangs- und Umlagerungspositionen übernehmen ihr Lagerort aus dem Dokument',
    'line_target_already_received': 'Diese Position wurde in der offenen Annahmesitzung bereits angenommen; die Ware bleibt an dem Lagerort, an dem sie angenommen wurde',
    'exclusion_not_found': 'Ausschluss nicht gefunden',
    'tag_not_found': "Tag '{tag}' in keinem Rezept gefunden",
    'meal_plan_not_found': 'Essensplan nicht gefunden',
    'meal_plan_slot_conflict': 'Einträge existieren in deaktivierten Slots: {slots}',
    'meal_plan_entry_not_found': 'Essensplaneintrag nicht gefunden',
    'attachment_not_found': 'Anhang nicht gefunden',
    'api_key_not_found': 'API-Schlüssel nicht gefunden',
    'invalid_api_key': 'Ungültiger oder abgelaufener API-Schlüssel',
    'api_key_owner_inactive': 'Das Konto, zu dem dieser API-Schlüssel gehört, ist inaktiv.',
    'unit_conversion_already_exists': 'Eine Umrechnung von {unit} für „{ingredient}“ existiert in dieser Organisation bereits. Bearbeiten Sie sie stattdessen.',
    'conversion_not_found': 'Umrechnung nicht gefunden',
    'conversion_not_found_or_system': 'Umrechnung nicht gefunden oder Systemstandard',
    'template_not_found': 'Vorlage nicht gefunden',
    'template_import_not_json': 'Die Datei konnte nicht als Vorlagenexport gelesen werden — sie ist kein gültiges JSON.',
    'template_import_wrong_kind': 'Diese Datei ist keine exportierte Dokumentvorlage.',
    'template_import_wrong_version': 'Die Datei wurde im Format Version {version} exportiert; diese Installation liest Version {supported}.',
    'template_import_invalid_field': 'Das Feld „{field}“ fehlt oder ist ungültig.',
    'template_import_unknown_placeholders': 'Die Vorlage verweist auf Felder, die nicht existieren: {placeholders}.',
    'template_import_not_renderable': 'Die Vorlage konnte nicht gerendert werden: {detail}',
    'model_not_found': 'Gerätemodell nicht gefunden',
    'widget_not_found': 'Widget nicht gefunden',
    'bom_line_not_found': 'Stücklistenposition nicht gefunden',
    'bom_line_already_exists': (
        'Diese Formel enthält diese Zutat bereits — zwischen den beiden '
        'Produkten besteht schon eine Stücklistenposition.'
    ),
    'bom_depth_exceeded': (
        'Diese Stückliste ist tiefer als {max_depth} Ebenen verschachtelt — '
        'zu tief, um sie aufzulösen.'
    ),
    'cost_line_not_found': 'Kostenposition nicht gefunden',
    'production_order_not_found': 'Produktionsauftrag nicht gefunden',
    'production_no_recipe': (
        'Keine Formel für dieses Produkt — legen Sie zuerst eine Formel an'
    ),
    'production_recipe_not_found': (
        'Formel {recipe_id} wurde in dieser Organisation nicht gefunden'
    ),
    'production_recipe_product_mismatch': ('Die Formel gehört nicht zu diesem Produkt'),
    'production_complete_not_draft': (
        'Dieser Produktionsauftrag hat bereits den Status {status} — nur ein '
        'Entwurf kann abgeschlossen werden.'
    ),
    'production_reverse_not_completed': (
        'Dieser Produktionslauf hat den Status {status}, es gibt also nichts zurückzunehmen — nur ein abgeschlossener Lauf kann rückgängig gemacht werden.'
    ),
    'production_reverse_output_used': (
        'Dieser Lauf kann nicht rückgängig gemacht werden: Ein Teil seiner Erzeugnisse hat den Lagerplatz bereits verlassen. Erfassen Sie stattdessen eine Bestandskorrektur für den Rest.'
    ),
    'production_cancel_not_draft': (
        'Dieser Produktionsauftrag hat bereits den Status {status} — nur ein '
        'Entwurf kann storniert werden.'
    ),
    'production_update_not_draft': (
        'Dieser Produktionsauftrag hat bereits den Status {status} — nur ein '
        'Entwurf kann bearbeitet werden.'
    ),
    'production_actual_qty_must_be_positive': (
        'Die produzierte Menge muss größer als null sein.'
    ),
    'production_overproduction_disabled': (
        'Überproduktion ist in den Einstellungen deaktiviert — dieser Auftrag '
        'kann nicht mehr als geplant produzieren.'
    ),
    'production_ingredient_unmeasurable': (
        'Die Einheit einer Zutat lässt sich nicht mit ihrem Bestand vergleichen, daher ist '
        'unklar, wie viel aus dem Regal zu nehmen ist — korrigieren Sie zuerst die Einheit der Formelzeile.'
    ),
    'production_short_of_stock': 'Für diesen Produktionsauftrag sind nicht genügend Zutaten auf Lager.',
    'output_template_not_found': 'Ausgabevorlage nicht gefunden',
    'purchase_order_not_found': 'Bestellung nicht gefunden',
    'reorder_rule_not_found': 'Nachbestellregel nicht gefunden',
    'pricelist_entry_not_found': 'Preislisteneintrag nicht gefunden',
    'reorder_max_below_min': 'max_quantity ({max_quantity}) muss >= min_quantity ({min_quantity}) sein',
    'reorder_safety_stock_negative': 'safety_stock muss >= 0 sein, erhalten {safety_stock}',
    'reorder_min_quantity_negative': 'min_quantity muss >= 0 sein, erhalten {min_quantity}',
    'pricelist_unit_price_not_positive': 'unit_price muss > 0 sein, erhalten {unit_price}',
    'pricelist_min_quantity_not_positive': 'min_quantity muss > 0 sein, erhalten {min_quantity}',
    'pricelist_valid_to_before_valid_from': 'valid_to ({valid_to}) muss >= valid_from ({valid_from}) sein',
    'pricelist_duplicate': (
        'Dieser Lieferant hat für dieses Produkt bereits einen Preis über '
        'denselben Zeitraum und dieselbe Mindestmenge. Bearbeiten Sie diesen '
        'Eintrag, statt einen zweiten anzulegen.'
    ),
    'tax_rate_not_found': 'Steuersatz nicht gefunden',
    'announcement_not_found': 'Ankündigung nicht gefunden',
    'approval_request_not_found': 'Genehmigungsantrag nicht gefunden',
    'cycle_count_schedule_not_found': 'Zyklische Inventurplanung nicht gefunden',
    'document_type_config_not_found': 'Dokumenttyp-Konfiguration nicht gefunden',
    'history_entry_not_found': 'Verlaufseintrag nicht gefunden',
    'ingredient_not_found': 'Zutat nicht gefunden',
    'label_not_found': 'Etikett nicht gefunden',
    'scan_unrecognized': 'Code nicht erkannt — kein Produkt, Etikett, Ort oder Dokument passt dazu',
    'member_not_found': 'Mitglied nicht gefunden',
    'module_not_found': 'Modul nicht gefunden',
    'notification_not_found': 'Benachrichtigung nicht gefunden',
    'partner_not_found': 'Partner nicht gefunden',
    'partner_name_exists': 'Ein Partner mit dem Namen "{name}" und dem Typ "{partner_type}" existiert bereits.',
    'partner_code_exists': 'Ein Partner mit dem Code "{code}" existiert bereits.',
    'partner_delete_open_purchase_orders': 'Der Partner kann nicht gelöscht werden: {count} offene Bestellungen verweisen auf ihn',
    'partner_import_name_missing': 'Partnername fehlt',
    'partner_import_duplicate': 'Doppelter Partner: "{twin}" hat diesen Namen oder diese Steuer-ID bereits',
    'product_not_found': 'Produkt nicht gefunden',
    'product_template_not_found': 'Produktvorlage nicht gefunden',
    'profile_not_found': 'Profil nicht gefunden',
    'receiving_session_not_found': 'Wareneingangssitzung nicht gefunden',
    'request_not_found': 'Anfrage nicht gefunden',
    'workflow_not_found': 'Workflow nicht gefunden',
    'campaign_not_found': 'Kampagne nicht gefunden',
    'attestation_no_active_assignments': 'Im gewählten Umfang gibt es keine aktiven Zuweisungen',
    'attestation_not_draft': 'Diese Kampagne ist bereits {status} — nur ein Entwurf lässt sich starten',
    'attestation_reminders_not_active': 'Erinnerungen lassen sich nur für eine laufende Kampagne senden',
    'campaign_deadline_past': 'Der Kampagnen-Endtermin muss heute oder später liegen',
    'attestation_complete_not_allowed': 'Eine Kampagne im Status {status} lässt sich nicht abschließen',
    'attestation_scope_exceeds_limit': 'Der Umfang umfasst mehr als {limit} Artikel. Grenzen Sie ihn ein oder teilen Sie die Bestätigung auf.',
    'assignment_not_found': 'Zuweisung nicht gefunden',
    'maintenance_log_not_found': 'Wartungsprotokoll nicht gefunden',
    'equipment_cannot_checkout_retired': 'Ausgemusterte Ressource kann nicht ausgeliehen werden',
    'equipment_cannot_checkout_in_maintenance': 'Eine Ressource in Wartung kann nicht ausgeliehen werden; setzen Sie sie zuerst auf Verfügbar',
    'equipment_assignment_needs_person_or_location': 'Nennen Sie entweder die Person oder den Lagerort, nicht beides',
    'equipment_bulk_scope_too_large': '{matched} Ressourcen entsprechen den Filtern; eine Aktion umfasst höchstens {limit}. Filter eingrenzen.',
    'equipment_assignment_already_active': 'Artikel hat bereits eine aktive Zuweisung',
    'equipment_assignment_already_checked_in': 'Zuweisung wurde bereits zurückgegeben',
    'api_key_cannot_manage': 'API-Schlüssel können andere API-Schlüssel nicht verwalten',
    'api_key_cannot_create': 'API-Schlüssel können keine anderen API-Schlüssel erstellen',
    'api_key_cannot_revoke': 'API-Schlüssel können andere API-Schlüssel nicht widerrufen',
    'api_key_scope_refused': 'Dieser API-Schlüssel ist auf {scope} beschränkt und kann hier nicht verwendet werden',
    'api_key_scope_unknown': 'Es gibt keinen API-Schlüssel-Bereich namens „{scope}“',
    'api_key_permission_not_grantable': 'Ein API-Schlüssel kann die Berechtigung {permission} nicht erhalten: Sie besitzen sie nicht, oder kein Schlüssel trägt sie',
    'api_key_permission_outside_scope': 'Die Berechtigung {permission} gehört zu keinem der für diesen Schlüssel gewählten Bereiche',
    'print_no_agent': 'Kein Drucker verbunden. Starten Sie den Inventari Print Agent am Drucker.',
    'print_choose_agent': 'Mehrere Drucker sind verbunden. Wählen Sie den Drucker aus.',
    'print_agent_protocol_missing': 'Dieser Agent sagt nichts über das Druckprotokoll, das er spricht: Er ist älter als das versionierte Protokoll. Aktualisieren Sie den Print-Agent.',
    'print_agent_protocol_unsupported': 'Dieser Agent spricht Druckprotokoll {agent}; dieser Server spricht Druckprotokoll {server}. Aktualisieren Sie das Ältere von beiden.',
    'print_agent_not_found': 'Drucker nicht gefunden',
    'print_job_not_found': 'Druckauftrag nicht gefunden',
    'print_job_nothing_to_print': 'Nichts zu drucken: keines der gewählten Etiketten wurde gefunden',
    'product_label_no_code': 'Nichts zu drucken: keines der gewählten Produkte hat einen Code. Erzeugen Sie einen im Produktformular',
    'product_label_too_narrow': 'Der Code {code} passt nicht auf ein {width} mm breites Etikett: seine Striche brauchen mindestens {needed} mm. Wählen Sie ein breiteres Etikett',
    'product_label_too_short': 'Das {height} mm hohe Etikett ist zu niedrig: nach Name und Text bleibt den Strichen des Codes {code} zu wenig Höhe für einen Scanner. Wählen Sie ein höheres Etikett',
    'storage_code_template_invalid': 'Die Codevorlage „{template}“ ist nicht verwendbar. Schreiben Sie Platzhalter wie {{zone}}-{{rack:02}}-{{level:02}} mit einem Trennzeichen dazwischen oder ein Präfix aus höchstens fünf Buchstaben und Ziffern wie LOC',
    'storage_code_template_not_tree': 'Dieses Lager vergibt zufällige Codes: Geben Sie ihm eine Vorlage mit Platzhaltern wie {zone}-{rack:02}-{level:02}, bevor Sie seine Lagerorte nummerieren',
    'storage_code_parent_not_numbered': 'Dieser Lagerort lässt sich nicht für sich nummerieren: Die Plätze darüber tragen noch keine Codes der Vorlage, oder er liegt tiefer, als die Vorlage reicht. Nummerieren Sie zuerst die Ebene darüber',
    'storage_code_number_not_here': 'Nur ein gewöhnlicher Lagerort lässt sich nummerieren, kein archivierter oder virtueller',
    'storage_code_template_not_warehouse': 'Eine Codevorlage gehört zu einem Lager, einem Lagerort an der Spitze des Baums',
    'print_job_not_claimed': 'Dieser Druckauftrag wird nicht von diesem Drucker gedruckt',
    'print_job_not_retryable': 'Nur ein fehlgeschlagener Druckauftrag kann erneut gesendet werden',
    'print_job_one_target': 'Senden Sie genau eine Art von Etiketten: Pool-Etiketten nach ID, Pool-Etiketten nach Code oder Lagerorte.',
    'webhook_admin_only': 'Nur Administratoren können Webhooks verwalten',
    'approvals_manage_admin_only': 'Nur Administratoren und Manager können Genehmigungsworkflows ändern',
    'approvals_action_admin_only': 'Sie haben keine Berechtigung, Anträge zu genehmigen oder abzulehnen',
    'approvals_read_forbidden': 'Sie haben keine Berechtigung, Genehmigungsanträge einzusehen',
    'approvals_write_forbidden': 'Sie haben keine Berechtigung, Genehmigungsanträge zu stellen',
    'documents_approve_requires_grant': 'Sie haben keine Berechtigung, Dokumente zu genehmigen oder abzulehnen',
    'po_approval_workflow_missing': 'Diese Bestellung braucht eine Freigabe, aber noch ist niemand dafür eingerichtet. Bitten Sie Ihren Administrator, das einzurichten.',
    'po_supplier_required': 'Eine Bestellung kann ohne Lieferanten nicht bestätigt werden',
    'document_type_requires_partner': 'Dieser Dokumenttyp erfordert einen Partner.',
    'partner_has_no_email': 'Der Partner hat keine E-Mail-Adresse.',
    'po_has_no_partner': 'Diese Bestellung hat keinen Lieferanten, an den sie gesendet werden kann.',
    'approval_no_active_workflow': 'Für diese Aktion ist kein aktiver Genehmigungsworkflow konfiguriert.',
    'po_no_pending_approval_request': 'Für diese Bestellung liegt keine ausstehende Genehmigungsanfrage vor.',
    'po_request_approval_invalid_status': 'Diese Bestellung kann nicht mehr zur Genehmigung eingereicht werden.',
    'po_approve_invalid_status': 'Nur eine auf Genehmigung wartende Bestellung kann genehmigt werden.',
    'approval_cannot_approve_own_request': 'Sie können Ihre eigene Anfrage nicht genehmigen.',
    'approval_cannot_reject_own_request': 'Sie können Ihre eigene Anfrage nicht ablehnen.',
    'approval_approve_invalid_status': 'Nur eine Anfrage, die auf eine Entscheidung wartet, kann genehmigt werden.',
    'approval_reject_invalid_status': 'Nur eine Anfrage, die auf eine Entscheidung wartet, kann abgelehnt werden.',
    'approval_cancel_invalid_status': 'Nur eine offene Anfrage kann zurückgezogen werden.',
    'approval_decision_already_taken': 'Jemand anderes hat über diese Anfrage bereits entschieden.',
    'approval_not_stage_approver': 'Sie sind für diese Stufe nicht als genehmigende Person eingetragen.',
    'approval_only_requester_can_cancel': 'Nur die Person, die die Anfrage gestellt hat, kann sie zurückziehen.',
    'approval_workflow_inactive': 'Der Genehmigungsworkflow hinter dieser Anfrage ist nicht mehr aktiv.',
    'approval_request_already_open': 'Für diesen Datensatz ist bereits eine Genehmigungsanfrage offen.',
    'approval_workflow_no_stages': 'Für diesen Genehmigungsworkflow sind keine Stufen konfiguriert.',
    'approval_workflow_needs_stage': 'Ein Genehmigungsworkflow benötigt mindestens eine Stufe.',
    'approval_workflow_modify_blocked': 'Dieser Workflow kann nicht geändert werden, solange Anfragen auf ihn warten ({count}: {documents}). Wer eine Anfrage gestellt hat, kann sie zurückziehen, und ein Genehmiger kann sie entscheiden — erledigen Sie diese zuerst.',
    'approval_workflow_delete_blocked': 'Dieser Workflow kann nicht gelöscht werden, solange Anfragen auf ihn warten ({count}: {documents}). Wer eine Anfrage gestellt hat, kann sie zurückziehen, und ein Genehmiger kann sie entscheiden — erledigen Sie diese zuerst.',
    'approval_workflow_archived': 'Dieser Workflow wurde gelöscht und ist archiviert: Seine Anfragen zeigen weiterhin die Stufen, die sie durchlaufen haben, daher kann er weder geändert noch wieder aktiviert werden. Legen Sie an seiner Stelle einen neuen Workflow an.',
    'approval_unknown_approvers': 'Einige der ausgewählten genehmigenden Personen gehören nicht zu dieser Organisation.',
    'approval_unknown_requesters': 'Einige der ausgewählten Personen oder Rollen gehören nicht zu dieser Organisation.',
    'approval_requester_scope_everyone_with_names': 'Ein Workflow, der für alle gilt, nennt keine Personen oder Rollen.',
    'approval_requester_scope_names_nobody': 'Wählen Sie mindestens eine Person oder Rolle oder alle.',
    'approval_stage_unsolvable': 'Die Stufe „{label}" kann nie entschieden werden: Keine der namentlich genannten Personen hat Zugriff auf Genehmigungen. Fügen Sie mindestens eine Person mit Zugriff hinzu.',
    'approval_scope_changed': 'Was dieser Workflow anhalten würde, hat sich seit dem Öffnen geändert — lesen Sie es erneut und schalten Sie ihn ein, wenn es noch Ihrem Willen entspricht.',
    'approval_scope_required': 'Zum Einschalten gehört der Geltungsbereich, den Sie gesehen haben — senden Sie „expected_scope“ mit, sonst bleibt der Workflow aus.',
    'approval_stage_open_unsolvable': 'Die Stufe „{label}" wartet auf Personen mit dem Genehmigungsrecht, und niemand in dieser Organisation hat es — keine Anfrage würde je entschieden. Vergeben Sie es oder benennen Sie eine genehmigende Person.',
    'approval_required_first': 'Für diese Aktion ist zuerst eine Genehmigung erforderlich. Stellen Sie zunächst eine Anfrage.',
    'approval_workflow_required_but_missing': 'Dies erfordert eine Genehmigung, aber es gibt dafür keinen aktiven Genehmigungsworkflow. Legen Sie einen an oder heben Sie die Anforderung auf.',
    'approval_required_after_rejection': 'Die Genehmigung für diese Aktion wurde abgelehnt. Stellen Sie eine neue Anfrage, bevor Sie fortfahren.',
    'approval_granted_for_another_holder': 'Die Genehmigung gilt für eine Ausgabe an {holder}. Fragen Sie eine Genehmigung für diese Ausgabe an.',
    'document_no_pending_approval_request': 'Für dieses Dokument liegt keine ausstehende Genehmigungsanfrage vor.',
    'document_request_approval_invalid_status': 'Nur ein bestätigtes Dokument kann zur Genehmigung eingereicht werden.',
    'po_confirm_invalid_status': 'Diese Bestellung kann im aktuellen Zustand nicht bestätigt werden.',
    'po_email_invalid_status': 'Für eine Bestellung im Status {status} kann keine E-Mail gesendet werden. Nur CONFIRMED oder COMPLETED sind zulässig.',
    'po_email_invalid_address': 'Ungültige E-Mail-Adresse des Partners: {email}',
    'po_partner_inactive': 'Die Bestellung kann nicht bestätigt werden: Partner "{name}" ist inaktiv',
    'po_partner_not_supplier': 'Die Bestellung kann nicht bestätigt werden: Partner "{name}" hat den Typ "{partner_type}", der kein Lieferantentyp ist',
    'po_approval_race_condition': 'Der Genehmigungsantrag konnte nicht erstellt werden — möglicherweise wurde er von einer anderen Aktion bearbeitet. Bitte erneut versuchen.',
    'po_already_cancelled': 'Diese Bestellung ist bereits storniert',
    'po_cancel_completed': 'Eine abgeschlossene Bestellung kann nicht storniert werden',
    'po_cancel_received_quantities': 'Diese Bestellung kann nicht storniert werden, da bereits Mengen eingegangen sind — stornieren Sie zuerst die verknüpften Wareneingänge',
    'po_cancel_open_receipts': 'Diese Bestellung kann nicht storniert werden, solange Wareneingänge offen sind — schließen oder stornieren Sie sie zuerst: {numbers}',
    'po_receipt_requires_confirmed': 'Nur bestätigte Bestellungen können einen Wareneingang erstellen',
    'po_line_not_found': 'Bestellposition {po_line_id} nicht gefunden',
    'po_receive_quantity_exceeds': 'Die Menge {quantity} überschreitet die verbleibende Menge {remaining} für Position {line}',
    'po_line_product_template_not_found': 'Produktvorlage {template_id} nicht gefunden',
    'po_update_not_draft': 'Nur Bestellungen im Entwurfsstatus können aktualisiert werden',
    'po_lines_received': (
        'Die Positionen können nicht aktualisiert werden: Mengen wurden bereits '
        'empfangen. Stornieren Sie zuerst die zugehörigen Wareneingangsbelege.'
    ),
    'po_import_not_draft': 'Zeilen können nur in eine Bestellung im Entwurfsstatus importiert werden',
    'document_insufficient_stock': 'Nicht genügend Bestand zum Bestätigen: {quantity} von {needed} konnten nicht reserviert werden',
    'document_zone_split_needs_stock_unit': 'Die Position für "{item_name}" ist in einer anderen Einheit als der Lagerbestandseinheit des Produkts geschrieben und lässt sich nicht auf mehrere Regalplätze verteilen; schreiben Sie sie in der Lagerbestandseinheit oder entnehmen Sie sie aus einem einzigen Regalplatz',
    'document_record_stands_elsewhere': 'Der Datensatz „{item_name}“ liegt auf „{record_shelf}“, aber das Dokument nimmt von „{document_shelf}“ — richten Sie das Dokument auf „{record_shelf}“ aus oder verschieben Sie zuerst den Datensatz',
    'document_insufficient_stock_record_elsewhere': 'Nicht genügend Bestand zum Bestätigen: {quantity} von {needed} konnten auf „{document_shelf}“ nicht reserviert werden; der Datensatz „{item_name}“ liegt auf „{record_shelf}“ — richten Sie das Dokument auf diesen Platz aus oder verschieben Sie zuerst den Datensatz',
    'stock_would_go_negative': 'Damit läge der Bestand unter null. Inzwischen hat jemand diese Ware bewegt — neu laden und erneut versuchen.',
    'stock_reserved_over_quantity': 'Damit wäre mehr Ware reserviert, als im Regal liegt. Geben Sie eine Reservierung frei oder zählen Sie erneut.',
    'document_exceeds_order_line': 'Der Zugang von {quantity} überschreitet die Bestellposition, auf der nur noch {remaining} offen sind — jenseits der Überlieferungstoleranz von {tolerance} % wird jemand mit der Berechtigung zum Übererfassen benötigt',
    'over_receipt_needs_permission': 'Das Erfassen von {quantity} überschreitet die Überlieferungstoleranz von {tolerance} % — dafür wird jemand mit der Berechtigung zum Übererfassen benötigt',
    'over_receipt_confirm_surplus': '{product}: Die Annahme von {quantity} sind {surplus} mehr als die erwarteten {basis}. Überschuss annehmen?',
    'over_receipt_confirm_order_surplus': '{product}: Die Annahme von {quantity} sind {surplus} mehr als die {basis}, die in Bestellung {order}, Position {line} offen sind. Überschuss annehmen?',
    'over_receipt_past_ceiling': 'Die Annahme von {quantity} gegenüber {basis} überschreitet die Obergrenze für Mehrlieferungen von {ceiling}% — so viel darf niemand annehmen',
    'document_update_status': 'Nur Dokumente im Entwurfsstatus können aktualisiert werden',
    'document_correction_locked': 'Korrekturdokumente sind gesperrt — nur Notizen können geändert werden. Änderungsversuch: {fields}. Brechen Sie die Korrektur ab und erstellen Sie eine neue, wenn die Daten falsch sind.',
    'field_cannot_be_cleared': 'Diese Felder können nicht geleert werden: {fields}.',
    'ingredient_defaults_unreadable_file': 'Die Datei konnte nicht gelesen werden. Der Import erwartet eine .json- oder .csv-Datei mit einer Zeile pro Zutat.',
    'onboarding_modules_not_offered': 'Das Profil „{profile}“ bietet diese Module nicht an: {modules}',
    'location_chain_step_incomplete': 'Jeder Schritt einer Lagerortkette braucht eine ID oder einen Namen.',
    'current_password_incorrect': 'Das aktuelle Passwort ist falsch',
    'storage_own_parent': 'Ein Lagerort kann nicht sein eigener übergeordneter Lagerort sein.',
    'storage_short_code_in_use': 'Der Kurzcode „{short_code}“ wird bereits von einem anderen Lagerort verwendet.',
    'storage_would_cycle': 'Wird dieser Lagerort unter seinen eigenen untergeordneten Lagerort verschoben, entsteht ein Zyklus in der Lagerorthierarchie.',
    'template_not_builtin_copy': 'Diese Vorlage wurde nicht aus einem integrierten Layout kopiert',
    'smtp_config_invalid': 'Die Einstellungen des E-Mail-Servers sind ungültig: {reason}',
    'module_needs_newer_platform': 'Das Modul „{module}“ erfordert Inventari {required} oder neuer; installiert ist Version {current}.',
    'document_delete_status': 'Nur Entwurfsdokumente können gelöscht werden',
    'document_wms_picking_active': 'Dieses Dokument kann nicht abgeschlossen oder storniert werden, solange {sessions} aktive Kommissioniersitzung(en) laufen. Schließen oder stornieren Sie sie zuerst ab.',
    'document_wms_receiving_active': 'Dieses Dokument kann nicht abgeschlossen oder storniert werden, solange {sessions} aktive Wareneingangssitzung(en) laufen. Schließen oder stornieren Sie sie zuerst ab.',
    'document_confirm_invalid_status': 'Ein Dokument im Status {status} kann nicht bestätigt werden',
    'document_lines_need_stock_row': 'Ein Beleg vom Typ {type} nimmt Ware vom Lagerplatz, daher muss jede Position den Bestand nennen, von dem sie abgeht — Positionen {lines} nennen nur ein Produkt',
    'document_lines_need_stock_row_one': 'Ein Beleg vom Typ {type} nimmt Ware vom Lagerplatz, daher muss jede Position den Bestand nennen, von dem sie abgeht — Position {lines} nennt nur ein Produkt',
    'document_receipt_lines_need_product': 'Die Positionen {lines} nennen kein Produkt aus Ihrer Liste, und ein Wareneingang bucht nur Produkte ein — wählen Sie jede aus der Liste oder legen Sie sie als neues Produkt an',
    'document_receipt_lines_need_product_one': 'Die Position {lines} nennt kein Produkt aus Ihrer Liste, und ein Wareneingang bucht nur Produkte ein — wählen Sie es aus der Liste oder legen Sie es als neues Produkt an',
    'document_partner_tax_id_required': 'Partner "{name}" hat keine Steuer-ID, die Belege dieser Organisation verlangen sie jedoch zur Bestätigung. Tragen Sie die Steuer-ID beim Partner ein, markieren Sie den Partner als Privatperson (Verbraucher) oder schalten Sie „Partner-Steuer-ID erforderlich“ in den Dokumenteinstellungen aus.',
    'document_complete_invalid_status': 'Ein Dokument im Status {status} kann nicht abgeschlossen werden',
    'document_complete_unanswered_lines': 'Der Abschluss ohne Antwort für jede Position würde die unbeantworteten Positionen als vollständig geliefert verbuchen. Unbeantwortete Positionen: {lines}. Senden Sie deren Mengen oder setzen Sie complete_as_planned=true, um sie wie geplant zu verbuchen',
    'document_complete_skipped_lines': 'Der Abschluss würde die übersprungenen Positionen als vollständig kommissioniert oder angenommen verbuchen, ohne dass jemand gesagt hätte, was daraus wird. Übersprungene Positionen: {lines}. Legen Sie jede vor dem Abschluss zurück auf die Liste oder beantworten Sie sie als Fehlmenge mit Grund — complete_as_planned deckt sie nicht ab',
    'document_receipt_lines_need_expiry': 'Ein Produkt, das nach dem frühesten Verfallsdatum entnommen wird, kann nicht ohne Verfallsdatum angenommen werden — es würde hinter jedem datierten Bestand einsortiert. Positionen: {lines}. Senden Sie Charge und Verfallsdatum mit dem Abschluss oder tragen Sie das Datum in der Position ein',
    'picking_lot_no_longer_available': 'Die Kommissionierung kann nicht abgeschlossen werden: Charge {lot} kann die entnommenen {quantity} Einheiten nicht mehr liefern',
    'document_active_approval_request': 'Für dieses Dokument ist bereits ein Genehmigungsantrag aktiv',
    'document_cancel_invalid_status': 'Nur Dokumente im Entwurfs-, Genehmigungs- oder Bestätigungsstatus können storniert werden',
    'document_fields_closed': 'Die Felder eines abgeschlossenen oder stornierten Dokuments können nicht mehr geändert werden',
    'approval_workflow_not_found': 'Genehmigungsworkflow nicht gefunden',
    'po_pdf_invalid_status': 'Ein PDF kann nur für bestätigte oder abgeschlossene Bestellungen erstellt werden. Aktueller Status: {status}',
    'po_pdf_generation_failed': 'PDF-Erstellung fehlgeschlagen',
    'email_delivery_failed': 'Die E-Mail konnte nicht gesendet werden — der SMTP-Server ist möglicherweise nicht konfiguriert',
    'invalid_partner_type': 'Dieser Partnertyp wird nicht erkannt.',
    'invalid_country_code': 'Das Land muss ein zweistelliger ISO-3166-1-alpha-2-Code sein (z. B. PL).',
    'invalid_print_page_size': 'Das Papierformat muss A4 oder Letter sein.',
    'invalid_timezone': 'Die Zeitzone muss ein gültiger IANA-Zonenname sein (z. B. Europe/Warsaw).',
    'invalid_currency_code': 'Die Währung muss ein gültiger ISO-4217-Code sein (z. B. PLN).',
    'admin_permissions_required': 'Für diese Aktion sind Administratorrechte erforderlich',
    'invalid_url_missing_host': 'Ungültige URL: Host fehlt',
    'url_must_be_public': 'URL muss auf einen öffentlichen Host verweisen',
    'invalid_url_scheme': 'Ungültige URL: muss mit http:// oder https:// beginnen',
    'rating_must_be_1_to_5': 'Bewertung muss zwischen 1 und 5 liegen',
    'no_missing_ingredients': 'Keine fehlenden Zutaten hinzuzufügen',
    'picking_session_not_found': 'Kommissionierungssitzung nicht gefunden',
    'barcode_or_item_id_required': 'Barcode oder item_id erforderlich',
    'ingredient_not_found_or_not_picked': 'Zutat nicht gefunden oder noch nicht kommissioniert',
    'no_valid_images': 'Keine gültigen Bilder angegeben',
    'file_must_be_image': 'Datei muss ein Bild sein',
    'vision_file_too_large': 'Datei ist zu groß',
    'vision_unsupported_image_type': 'Die Datei „{filename}“ hat keinen akzeptierten Bildtyp ({content_type}). Akzeptiert: {accepted}.',
    'llm_provider_unreachable': (
        'Der KI-Anbieter hinter der Verbindung "{name}" (Modell '
        '"{model}") war nicht erreichbar. Prüfen Sie die Adresse und ob '
        'der Dienst läuft, unter Einstellungen → KI-Verbindungen.'
    ),
    'llm_provider_unreachable_generic': (
        'Der KI-Anbieter war nicht erreichbar. Prüfen Sie die Adresse der '
        'Verbindung und ob der Dienst läuft, unter Einstellungen → '
        'KI-Verbindungen.'
    ),
    'llm_provider_timeout': (
        'Die Verbindung "{name}" (Modell "{model}") hat nicht rechtzeitig '
        'geantwortet. Der Anbieter war erreichbar — ein Modell auf Ihrer '
        'eigenen Hardware braucht unter Umständen länger '
        '(LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) oder ein kleineres Kontextfenster.'
    ),
    'llm_provider_timeout_generic': (
        'Der KI-Anbieter hat nicht rechtzeitig geantwortet. Er war erreichbar '
        '— ein Modell auf Ihrer eigenen Hardware braucht unter Umständen '
        'länger (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) oder ein kleineres '
        'Kontextfenster.'
    ),
    'llm_provider_key_rejected': (
        'Der AI-Anbieter hinter der Verbindung "{name}" (Modell "{model}") '
        'hat den API-Schlüssel abgelehnt. Prüfen Sie den Schlüssel in '
        'Einstellungen → AI-Verbindungen.'
    ),
    'llm_provider_key_rejected_generic': (
        'Der AI-Anbieter hat den API-Schlüssel abgelehnt. Prüfen Sie den '
        'Schlüssel in Einstellungen → AI-Verbindungen.'
    ),
    'llm_provider_limit': (
        'Verbindung "{name}" (Modell "{model}") wurde vom AI-Anbieter '
        'abgelehnt: Das Planlimit oder das Kontoguthaben ist aufgebraucht. '
        'Prüfen Sie den Plan oder versuchen Sie es später erneut.'
    ),
    'llm_provider_limit_generic': (
        'Der AI-Anbieter hat abgelehnt: Das Planlimit oder das Kontoguthaben '
        'ist aufgebraucht. Prüfen Sie den Plan oder versuchen Sie es später '
        'erneut.'
    ),
    'llm_provider_model_unknown': (
        'Der AI-Anbieter hinter der Verbindung "{name}" kennt das Modell '
        '"{model}" nicht. Prüfen Sie den Modellnamen in Einstellungen → '
        'AI-Verbindungen.'
    ),
    'llm_provider_model_unknown_generic': (
        'Der AI-Anbieter kennt das konfigurierte Modell nicht. Prüfen Sie den '
        'Modellnamen in Einstellungen → AI-Verbindungen.'
    ),
    'llm_purpose_unbound': (
        'Für diese Funktion ist noch keine KI-Verbindung ausgewählt. '
        'Wählen Sie eine unter Einstellungen → KI-Verbindungen.'
    ),
    'llm_connection_test_failed': (
        'Der Verbindungstest konnte nicht abgeschlossen werden. Prüfen Sie '
        'die Adresse und versuchen Sie es erneut.'
    ),
    'llm_base_url_unresolved': (
        'Der Hostname "{host}" der KI-Verbindungsadresse konnte nicht '
        'aufgelöst werden — prüfen Sie die Schreibweise; ein Tippfehler liest '
        'sich hier wie ein nicht erreichbarer Anbieter. Ist die Adresse '
        'richtig geschrieben, fragen Sie den Betreiber dieses Servers, ob '
        'der Name im DNS veröffentlicht ist.'
    ),
    'llm_base_url_loopback': 'Die KI-Verbindungsadresse zeigt auf einen Loopback-Hostnamen ({host}). Nur externe Adressen — bitten Sie die Person, die diese Installation betreibt, einen lokalen Modellserver zuzulassen (Einstellung LLM_ALLOW_PRIVATE_NETWORKS).',
    'llm_base_url_private': 'Die KI-Verbindungsadresse zeigt auf eine private oder interne Adresse ({host}). Nur externe Adressen — bitten Sie die Person, die diese Installation betreibt, einen lokalen Modellserver zuzulassen (Einstellung LLM_ALLOW_PRIVATE_NETWORKS).',
    'llm_base_url_scheme': (
        'Die KI-Verbindungsadresse muss http oder https verwenden.'
    ),
    'llm_base_url_required_for_http_provider': (
        'Dieser Anbieter wird über HTTP erreicht, deshalb ist die '
        'Basis-URL erforderlich — zum Beispiel https://openrouter.ai/api/v1'
    ),
    'llm_base_url_no_hostname': (
        'Die KI-Verbindungsadresse muss einen Hostnamen enthalten.'
    ),
    'llm_base_url_refused': (
        'Die KI-Verbindungsadresse wurde abgelehnt. Nur externe Adressen — '
        'setzen Sie LLM_ALLOW_PRIVATE_NETWORKS=true bei '
        'Self-Hosted-Installationen, um einen lokalen Modellserver zuzulassen.'
    ),
    'vision_model_returned_nothing': (
        'Die Verbindung "{name}" (Modell "{model}") hat keinen Inhalt '
        'geliefert. Prüfen Sie, ob das Modell Bilder liest und ob sein '
        'Token-Budget ausreicht — am Foto liegt es nicht.'
    ),
    'vision_model_returned_nothing_generic': (
        'Das Modell hat keinen Inhalt geliefert. Prüfen Sie unter '
        'Einstellungen → KI-Verbindungen, ob es überhaupt Bilder liest.'
    ),
    'vision_label_not_understood': (
        'Die KI konnte dieses Etikett mit der Verbindung "{name}" '
        '(Modell "{model}") nicht lesen. Versuchen Sie ein schärferes Foto '
        'oder wählen Sie eine andere Verbindung unter Einstellungen → KI-Verbindungen.'
    ),
    'vision_nutrition_not_understood': (
        'Die KI konnte diese Nährwerttabelle mit der Verbindung "{name}" '
        '(Modell "{model}") nicht lesen. Versuchen Sie ein schärferes Foto '
        'oder wählen Sie eine andere Verbindung unter Einstellungen → KI-Verbindungen.'
    ),
    'vision_label_not_understood_generic': (
        'Die KI konnte dieses Etikett nicht lesen. Versuchen Sie ein schärferes Foto oder ein anderes Modell unter KI-Verbindungen.'
    ),
    'vision_nutrition_not_understood_generic': (
        'Die KI konnte diese Nährwerttabelle nicht lesen. Versuchen Sie ein schärferes Foto oder ein anderes Modell unter KI-Verbindungen.'
    ),
    'vision_ai_not_configured': (
        'Für die Bilderkennung ist noch keine KI-Verbindung ausgewählt. Wählen Sie eine unter Einstellungen → KI-Verbindungen.'
    ),
    'invalid_organization_id': 'Ungültige Organisations-ID',
    'user_has_no_organization': 'Benutzer hat keine Organisation',
    'unsupported_import_format': 'Nicht unterstütztes Importformat: {format}',
    'unsupported_export_format': 'Nicht unterstütztes Exportformat: {format}',
    'equipment_default_checkout_template': 'Standard-Ausgabeprotokoll',
    'equipment_default_checkin_template': 'Standard-Rückgabeprotokoll',
    'purchase_order_standard_template': 'Standardbestellung',
    'attestation_not_found': 'Attestierungslink nicht gefunden',
    'attestation_expired': 'Attestierungslink ist abgelaufen',
    'attestation_refused': 'Dieser Attestierungslink kann diese Aktion nicht annehmen. Bitten Sie die Organisation, die ihn gesendet hat, um einen neuen Link.',
    'campaign_closed': 'Diese Attestierungskampagne wurde geschlossen — Ihre Bestätigung kann nicht mehr erfasst werden. Wenn Sie das Gerät noch haben, wenden Sie sich an Ihre Organisation.',
    'assignment_already_returned': 'Dieses Gerät wurde bereits als zurückgegeben bestätigt — eine weitere Bestätigung ist nicht erforderlich.',
    'equipment_still_assigned': (
        'Das Gerät ist noch an eine Person ausgegeben. Nehmen Sie es zuerst zurück.'
    ),
    'equipment_deploy_requires_checkout': (
        'Ein Gerät gilt als ausgegeben, sobald es an eine Person ausgegeben wurde. '
        'Geben Sie es aus, statt den Status zu setzen.'
    ),
    'equipment_status_invalid': 'Ungültiger Status: {status}',
    'equipment_status_transition_denied': 'Status kann nicht von {old} nach {new} geändert werden',
    'equipment_status_transition_from_retired': 'Status kann nicht von {old} nach {new} geändert werden. Ausgemusterte Geräte müssen zuerst explizit reaktiviert werden.',
    'attestation_assignment_required': 'Wählen Sie das Gerät aus, für das Sie ein Problem melden',
    'meta_data_spelled_twice': (
        "'meta_data' und 'metadata' benennen dasselbe Feld zweimal. "
        'Senden Sie nur eines davon.'
    ),
    'ai_connection_not_found': 'KI-Verbindung nicht gefunden',
    'ai_connection_still_bound': 'Diese Verbindung ist einem Zweck zugeordnet. Bitte zuerst lösen.',
    'ai_connection_name_taken': 'Eine Verbindung namens „{name}“ existiert in dieser Organisation bereits.',
    'ai_connection_target_required': 'Wählen Sie eine gespeicherte Verbindung oder einen Anbieter zum Testen.',
    'ai_usage_limit_exceeded_requests': 'Die Organisation hat {used} von {limit} KI-Anfragen verbraucht, die für {period} zulässig sind. Wenden Sie sich an einen Administrator, um das Limit zu erhöhen.',
    'ai_usage_limit_exceeded_scans': 'Die Organisation hat {used} von {limit} Etiketten-Scans verbraucht, die für {period} zulässig sind. Wenden Sie sich an einen Administrator, um das Limit zu erhöhen.',
    'invalid_reset_token': 'Ungültiger oder abgelaufener Reset-Token',
    'modules_no_organization': 'Benutzer ist keiner Organisation zugeordnet',
    'modules_not_enabled': "Modul '{module_name}' ist für diese Organisation nicht aktiviert",
    'invalid_template_module': 'Modul muss "{module}" sein',
    'purge_blocked_by_audit_links': (
        'Artikel ist mit prüfungsrelevanten Datensätzen verknüpft und kann '
        'nicht dauerhaft gelöscht werden.'
    ),
    'permanent_delete_disabled': (
        'Das dauerhafte Löschen ist für diese Organisation deaktiviert.'
    ),
    'documents_approval_workflow_missing': 'Dieses Dokument braucht eine Freigabe, aber noch ist niemand dafür eingerichtet. Bitten Sie Ihren Administrator, das einzurichten.',
    'category_delete_blocked_by_items': (
        'Kategorie kann nicht gelöscht werden — sie wird verwendet ({count}). Verschieben Sie ihre Produkte zuerst in eine andere Kategorie.'
    ),
    'category_system_field_label_locked': (
        'Der Name des Feldes "{field}" gehört zum Produktkatalog und lässt sich nicht ändern.'
    ),
    'storage_delete_blocked_by_movements': (
        'Lagerort kann nicht gelöscht werden: {count} Lagerbewegungen verweisen darauf. Die Bewegungshistorie ist unveränderlich — archivieren Sie diesen Ort stattdessen.'
    ),
    'storage_delete_blocked_by_stock': (
        'Lagerort kann nicht gelöscht werden: Das Bestandsregister führt hier noch Bestand, zu dem kein Datensatz gehört. Archivieren Sie diesen Ort stattdessen oder ordnen Sie den Bestand zuerst einem Datensatz zu.'
    ),
    'storage_name_collision': (
        'Ein Lagerort mit dem Namen „{name}“ existiert bereits auf dieser Ebene.'
    ),
    # Built-in pydantic validation errors (RequestValidationError) —
    # chosen by the error's `type`, filled from its `ctx`, by
    # app.i18n._validation.translate_validation_error.
    'validation_missing': 'Dieses Feld ist erforderlich',
    'validation_string_too_long': 'Darf höchstens {max_length} Zeichen haben',
    'validation_string_too_short': 'Muss mindestens {min_length} Zeichen haben',
    'validation_pattern': 'Entspricht nicht dem erwarteten Format',
    'validation_greater_than_equal': 'Muss größer oder gleich {ge} sein',
    'validation_greater_than': 'Muss größer als {gt} sein',
    'validation_less_than_equal': 'Muss kleiner oder gleich {le} sein',
    'validation_less_than': 'Muss kleiner als {lt} sein',
    'validation_enum': 'Muss einer der folgenden sein: {expected}',
    'validation_int': 'Muss eine ganze Zahl sein',
    'validation_number': 'Muss eine Zahl sein',
    'validation_boolean': 'Muss wahr oder falsch sein',
    'validation_identifier': 'Muss eine gültige Kennung sein',
    'validation_date': 'Muss ein gültiges Datum sein',
    'document_return_requires_completed': 'Eine Rücksendung ist nur zu einem abgeschlossenen Dokument möglich',
    'document_return_type_not_eligible': 'Rücksendungen sind nur zu Wareneingängen, Warenausgängen und Umlagerungen möglich',
    'document_return_no_lines': 'Eine Rücksendung braucht mindestens eine Position',
    'document_original_line_missing': 'Position {line} gibt es im Dokument {number} nicht',
    'document_return_quantity_not_positive': 'Die Rücksendemenge in Position {line} muss größer als null sein',
    'document_return_quantity_exceeds_left': 'Eine Rücksendung von {quantity} ist mehr, als von Position {line} übrig ist ({left} von {done})',
    'document_correction_requires_completed': 'Nur ein abgeschlossenes Dokument kann korrigiert werden',
    'document_correction_no_lines': 'Eine Korrektur braucht mindestens eine Position',
    'document_correction_below_zero': 'Eine Korrektur um {delta} würde Position {line} unter null bringen — {left} von {done} sind noch korrigierbar',
    'document_correction_type_not_correctable': 'Dokumente dieses Typs können nicht korrigiert werden',
    'document_undo_type_not_supported': 'Nur ein Wareneingang, ein Warenausgang oder eine Umbuchung kann rückgängig gemacht werden',
    'document_undo_requires_completed': 'Nur ein gebuchter Beleg kann rückgängig gemacht werden',
    'document_undo_nothing_left': 'Alles, was dieser Beleg gebucht hat, wurde bereits storniert',
    'document_undo_blocked': 'Das kann nicht rückgängig gemacht werden: {reason} Verwenden Sie „Korrigieren“, um den Rest zu ändern.',
    'document_undo_stock_used': 'Das kann nicht rückgängig gemacht werden: spätere Bewegungen haben den gebuchten Bestand verbraucht. Verwenden Sie „Korrigieren“, um den Rest zu ändern.',
    'document_post_already_posted': 'Dieses Dokument wurde bereits gebucht – ein zweites Mal wurde nichts gebucht.',
    'document_post_cancelled': 'Dieses Dokument wurde storniert und kann nicht gebucht werden.',
    'document_filter_unknown': 'Dieser Filter ist nicht verfügbar: Kein aktiviertes Modul bietet ihn an ({name}).',
    'document_post_waiting_for_approval': 'Dieses Dokument wartet bereits auf Genehmigung; der Bestand ändert sich nach der Genehmigung.',
    'document_type_requires_target_location': 'Dieser Dokumenttyp braucht einen Ziellagerort',
    'document_type_requires_source_location': 'Dieser Dokumenttyp braucht einen Quelllagerort',
    'document_partner_must_be_supplier_or_manufacturer': 'Partner eines Wareneingangs muss ein Lieferant, Hersteller oder Kunde sein',
    'document_partner_must_be_customer_or_supplier': 'Partner eines Warenausgangs muss ein Kunde oder Lieferant sein',
    'document_unit_price_required': 'Jede Position braucht einen Stückpreis — er fehlt in Position {lines}',
    'document_preset_unknown': 'Es gibt keine Voreinstellung namens {name}. Verfügbar: {available}',
    'putaway_capacity_exists': 'Dieser Lagerort hat für dieses Produkt bereits eine Kapazität — bearbeiten Sie den vorhandenen Eintrag.',
    'putaway_capacity_not_found': 'Kapazitätseintrag nicht gefunden',
    'no_fields_to_update': 'Keine Felder zum Aktualisieren',
    'putaway_rule_needs_location': 'Eine Einlagerungsregel braucht mindestens einen Lagerort.',
    'putaway_rule_needs_match_key': 'Eine Einlagerungsregel braucht mindestens eine Bedingung — ein Produkt, eine Kategorie, einen Kontext-Tag oder einen Lagerorttyp.',
    'document_template_wrong_module': 'Eine Dokumentvorlage gehört zum Modul Dokumente',
    'search_query_empty': 'Geben Sie einen Suchbegriff ein',
    'document_type_invalid': 'Es gibt keinen Dokumenttyp {type}',
    'settings_payload_not_object': 'Die Einstellungen müssen als JSON-Objekt gesendet werden',
    'settings_field_required': 'Die Einstellung „{field}“ ist erforderlich',
    'settings_field_unknown': 'Unbekannte Einstellung „{field}“',
    'settings_value_not_string': 'Die Einstellung „{path}“ muss ein Text sein',
    'settings_value_not_integer': 'Die Einstellung „{path}“ muss eine ganze Zahl sein',
    'settings_value_not_number': 'Die Einstellung „{path}“ muss eine Zahl sein',
    'settings_value_not_boolean': 'Die Einstellung „{path}“ muss wahr oder falsch sein',
    'settings_value_not_object': 'Die Einstellung „{path}“ muss ein Objekt sein',
    'settings_value_not_array': 'Die Einstellung „{path}“ muss eine Liste sein',
    'settings_text_too_short': 'Die Einstellung „{path}“ muss mindestens {limit} Zeichen lang sein',
    'settings_text_too_long': 'Die Einstellung „{path}“ darf höchstens {limit} Zeichen lang sein',
    'settings_number_too_small': 'Die Einstellung „{path}“ muss mindestens {limit} betragen, erhalten: {value}',
    'settings_number_too_large': 'Die Einstellung „{path}“ darf höchstens {limit} betragen, erhalten: {value}',
    'settings_value_not_allowed': 'Die Einstellung „{path}“ muss einen dieser Werte haben: {allowed} (erhalten: {value})',
    'ai_purpose_unknown': 'Unbekannter KI-Zweck „{purpose}“',
    'attachment_file_type_invalid': 'Ungültiger Dateityp: {file_type}',
    'not_an_equipment_model': 'Kein Gerätemodell',
    'bom_line_parent_mismatch': 'Das übergeordnete Produkt der Zeile passt nicht zu dem Produkt, das diese Formel herstellt',
    'bom_cycle_detected': 'Zyklus in der Formel bei {template_id} erkannt',
    'margin_negative': 'Die Marge darf nicht negativ sein',
    'margin_too_high': 'Die Marge muss unter 100 % liegen, damit der Preis endlich bleibt',
    'label_size_invalid': 'Höhe und Breite eines Etiketts müssen größer als 0 sein.',
    'recipe_collection_not_found': 'Sammlung nicht gefunden',
    'recipe_collection_parent_not_found': 'Übergeordnete Sammlung nicht gefunden',
    'recipe_collection_own_parent': 'Eine Sammlung kann nicht ihre eigene übergeordnete Sammlung sein',
    'recipe_collection_under_descendant': 'Eine Sammlung kann nicht unter ihre eigene Untersammlung verschoben werden',
    'recipe_scrape_failed': 'Das Rezept konnte von der URL nicht abgerufen werden',
    'register_date_from_after_date_to': 'Das Startdatum darf nicht nach dem Enddatum liegen',
    'meal_plan_end_before_start': 'Das Enddatum darf nicht vor dem Startdatum liegen',
    'meal_plan_too_long': 'Ein Plan darf höchstens {days} Tage umfassen',
    'meal_plan_no_slots': 'Aktivieren Sie mindestens eine Mahlzeit im Plan',
    'meal_plan_start_in_past': 'Das Startdatum darf nicht in der Vergangenheit liegen',
    'meal_plan_empty': 'Aus einem leeren Plan lässt sich keine Einkaufsliste erstellen',
    'picking_terminate_reason_invalid': 'Ungültiger Beendigungsgrund: {reason}',
    'recipe_import_name_required': 'Die Importdaten müssen einen Rezeptnamen enthalten',
    'recipe_import_data_required': 'Für den JSON-Import sind Daten erforderlich',
    'recipe_import_unit_unknown': "Die Zutat '{ingredient}' verwendet die Einheit '{unit}', die diese Instanz nicht kennt",
    'recipe_ingredient_unit_missing': "Die Zutat '{ingredient}' hat eine Menge, aber keine Einheit",
    'recipe_import_url_required': 'Für den URL-Import ist eine URL erforderlich',
    'recipe_scrape_fetch_failed': 'Jina Reader konnte {url} nicht abrufen: {error}',
    'recipe_scrape_encoding_unsupported': 'Jina Reader hat komprimierte Inhalte zurückgegeben, die nicht sicher gelesen werden können. Verwenden Sie eine andere Importmethode.',
    'recipe_scrape_empty': 'Jina Reader lieferte für {url} keinen Inhalt',
    'recipe_scrape_no_ingredients': 'Die KI hat keine Zutaten gefunden — die Seite ist möglicherweise kein Rezept',
    'hex_color_invalid': 'Ungültige Hex-Farbe: {color}. Verwenden Sie das Format #RGB oder #RRGGBB',
    'shopping_list_nothing_to_convert': 'Keine umwandelbaren Positionen (keine hat eine Produktvorlage)',
    'stock_take_bulk_item_id_required': 'Für die Sammelzählung muss ein Artikel (item_id) angegeben werden',
    'cycle_count_scope_location_required': 'Der Umfang der zyklischen Inventur muss einen Lagerort (storage_location_id) angeben',
    'cycle_count_no_matching_items': 'Kein Artikel erfüllt die Kriterien der Planung',
    'stock_take_active_for_location': 'Für diesen Lagerort läuft bereits eine Inventur',
    'category_name_taken': 'Eine Kategorie mit diesem Namen existiert bereits',
    'invitation_code_invalid': 'Ungültiger oder abgelaufener Einladungscode',
    'invitation_other_address': 'Diese Einladung wurde für eine andere E-Mail-Adresse ausgestellt',
    'role_not_found': 'Rolle nicht gefunden',
    'role_other_organization': 'Die Rolle gehört zu einer anderen Organisation',
    'user_not_in_organization': 'Der Benutzer gehört nicht zu dieser Organisation',
    'template_other_organization': 'Die Vorlage gehört zu einer anderen Organisation',
    'template_in_use_by_items': 'Die Vorlage kann nicht gelöscht werden: Sie wird von {count} Artikel(n) verwendet',
    'barcode_already_exists': 'Der Barcode {barcode} existiert bereits',
    'stock_insufficient_for_template': 'Nicht genug Bestand für die Vorlage {template_id}: angefordert {requested}, verfügbar {available}',
    'stock_lot_not_consumable': 'Die Charge {lot} hat den Status {status} und kann weder verbraucht noch reserviert werden',
    'barcode_in_use': 'Der Barcode wird bereits verwendet: {barcode}',
    'serial_number_exists': 'Die Seriennummer existiert bereits: {serial_number}',
    'item_currency_mismatch': 'Die Artikelwährung ({item_currency}) muss der Währung der Organisation ({organization_currency}) entsprechen',
    'organization_currency_missing': 'Die Währung der Organisation ist nicht konfiguriert',
    'item_already_deleted': 'Der Artikel ist bereits gelöscht',
    'item_not_deleted': 'Der Artikel ist nicht gelöscht',
    'item_restore_quantity_unknown': 'Der Artikel kann nicht wiederhergestellt werden: Die ursprüngliche Menge ist unbekannt, weil der Löschverlauf sie nicht enthält',
    'item_purge_requires_archived': 'Nur archivierte Artikel können endgültig gelöscht werden',
    'item_purge_reason_required': 'Für das endgültige Löschen in der Produktion ist ein Grund erforderlich',
    'relocation_destination_foreign': 'Der Artikel kann nicht verschoben werden: Das Ziel gehört nicht zu dieser Organisation.',
    'relocation_blocked_by_reservations': 'Der Artikel kann nicht verschoben werden: Der Quellbestand hat offene Reservierungen. Geben Sie sie zuerst frei oder erfüllen Sie sie.',
    'short_code_invalid_format': 'Ungültiges Codeformat',
    'short_code_duplicate_in_request': 'Doppelter Kurzcode in der Anfrage: {short_code}',
    'short_codes_taken': 'Diese Kurzcodes werden in der Organisation bereits verwendet: {codes}',
    'onboarding_profile_unknown': "Unbekanntes Profil: '{profile}'",
    'storage_vanished_during_batch': 'Der Lagerort {location} ist während des Stapels verschwunden.',
    'storage_archive_blocked_by_items': 'Archivieren nicht möglich: Hier lagern noch {count} Artikel. Verschieben Sie sie zuerst oder archivieren Sie mit einem Zielort.',
    'storage_archive_target_is_self': 'Artikel können nicht in den Lagerort verschoben werden, der gerade archiviert wird.',
    'storage_archive_target_is_descendant': 'Artikel können nicht in einen untergeordneten Lagerort des archivierten Lagerorts verschoben werden.',
    'storage_archive_target_archived': 'Artikel können nicht in einen archivierten Lagerort verschoben werden.',
    'storage_restore_parent_archived': 'Die Wiederherstellung in einen archivierten übergeordneten Lagerort ist nicht möglich. Stellen Sie zuerst den übergeordneten Lagerort wieder her.',
    'storage_delete_blocked_by_references': 'Der Lagerort kann nicht gelöscht werden: Andere Datensätze verweisen noch darauf (Constraint „{constraint}“). Archivieren Sie ihn stattdessen.',
    'storage_delete_concurrent_movements': 'Der Lagerort kann nicht gelöscht werden: Eine parallele Transaktion hat Lagerbewegungen erzeugt, die darauf verweisen. Versuchen Sie es erneut, um die Anzahl zu aktualisieren. Ursprünglicher Fehler: {error}',
    'sole_administrator_cannot_leave': 'Sie können die Organisation nicht als einziger Administrator verlassen. Bestimmen Sie zuerst einen weiteren Administrator.',
    'sole_administrator_role_locked': 'Die Rolle des einzigen Administrators kann nicht geändert werden. Befördern Sie zuerst ein anderes Mitglied.',
    'organization_member_limit': 'Das Mitgliederlimit der Organisation ist erreicht. Wechseln Sie zu Inventari Cloud, um mehr Plätze zu erhalten.',
    'registration_failed': 'Die Registrierung konnte nicht abgeschlossen werden. Bitte versuchen Sie es erneut oder wenden Sie sich an den Support.',
    'superuser_required': 'Für diese Aktion sind Superuser-Berechtigungen erforderlich',
    'onboarding_already_completed': 'Das Onboarding ist bereits abgeschlossen — verwenden Sie /switch-profile',
    'module_dependency_cycle': 'Zirkuläre Abhängigkeit unter Beteiligung des Moduls „{module}“ erkannt',
    'module_dependency_cycle_among': 'Zirkuläre Abhängigkeit zwischen den Modulen erkannt: {modules}',
    'profile_switch_unknown_modules': 'Das Profil verweist auf nicht registrierte Module: {unknown_modules}',
    'profile_switch_modules_not_allowed': 'Für diese Organisation nicht zulässige Module: {not_allowed_modules}',
    'profile_switch_dependency_unregistered': 'Das Modul „{module}“ benötigt „{missing_dependency}“, das nicht registriert ist.',
    'focus_mode_module_always_on': 'Das Modul „{module}“ ist immer aktiv und kann nicht der einzige Fokus sein.',
    'focus_mode_module_unregistered': 'Das Modul „{module}“ ist nicht registriert.',
    'focus_mode_module_not_enabled': 'Das Modul „{module}“ ist für diese Organisation nicht aktiviert.',
    'focus_mode_already_active': 'Die Organisation ist bereits auf „{module}“ fokussiert.',
    'focus_mode_not_active': 'Die Organisation befindet sich nicht im Einzelmodul-Fokusmodus.',
}
