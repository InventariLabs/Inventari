from app.i18n._types import ErrorMessages

ERRORS_FR: ErrorMessages = {
    'invalid_credentials': 'E-mail ou mot de passe invalide',
    'invalid_input': 'Entrée invalide',
    'not_authenticated': 'Non authentifié',
    'user_already_exists': 'Un utilisateur avec cet e-mail existe déjà',
    'user_already_in_organization': "L'utilisateur appartient déjà à une organisation",
    'token_expired': "Le jeton d'authentification a expiré",
    'token_invalid': "Jeton d'authentification invalide",
    'insufficient_permissions': "Vous n'avez pas la permission d'effectuer cette action",
    'import_create_forbidden': "Ce compte n'a pas les permissions {permissions}, l'import ne peut donc pas créer les emplacements ou catégories manquants en son nom. Désactivez les interrupteurs correspondants dans la boîte d'import ou demandez la permission",
    'import_create_forbidden_one': "Ce compte n'a pas la permission {permissions}, l'import ne peut donc pas créer les emplacements ou catégories manquants en son nom. Désactivez les interrupteurs correspondants dans la boîte d'import ou demandez la permission",
    'import_stubs_forbidden': "Ce compte n'a pas la permission {permissions}, l'import ne peut donc pas créer de produits temporaires pour les codes-barres sans correspondance en son nom. Décochez la case « Créer des produits de remplacement » dans la boîte d'import ou demandez la permission",
    'user_blocked': 'Votre compte a été bloqué. Raison : {reason}',
    'user_blocked_no_reason': 'non précisée',
    'uom_not_found': 'Unité de mesure introuvable',
    'import_job_not_found': 'Import introuvable',
    'user_not_found': 'Utilisateur introuvable',
    'user_email_required': 'Ce compte n’a pas d’adresse e-mail et n’a donc aucun actif à afficher.',
    'user_inactive': "Votre compte est en attente d'approbation par un administrateur.",
    'item_not_found': 'Article introuvable',
    'item_quantity_above_ceiling': 'La quantité {quantity} dépasse la capacité de la colonne — la plus grande valeur enregistrable est {ceiling}',
    'item_quantity_raise_in_virtual_location': "Ce produit se trouve dans {location}, où le stock n'est pas compté — remettez-le d'abord sur une étagère, puis ajoutez la quantité",
    'counted_quantity_above_ceiling': 'La quantité comptée {quantity} dépasse la capacité de la colonne — la plus grande valeur enregistrable est {ceiling}',
    'item_unit_change_blocked_by_stock': "Cette fiche porte {quantity} {current_unit}. Changer l'unité pour {new_unit} ne ferait que réétiqueter ce nombre sans rien changer sur l'étagère. Épuisez ou sortez le stock d'abord, ou créez une fiche distincte dans la nouvelle unité.",
    'item_unit_differs_from_template_confirmation_required': "{product} est suivi en {template_unit}, et cette quantité est donnée en {chosen_unit}. Elle sera convertie en {template_unit} à l'enregistrement : confirmez que {chosen_unit} est bien l'unité voulue, ou saisissez la quantité en {template_unit}.",
    'item_unit_not_convertible_to_card': '{product} est suivi en {template_unit}, et une quantité en {chosen_unit} ne peut pas y être convertie. Saisissez la quantité en {template_unit} — ou, pour des pièces, indiquez sur le produit ce que pèse ou contient une pièce.',
    'bom_line_unit_not_convertible': 'Cet ingrédient est suivi en {stock_unit}, et {line_unit} ne peut pas se '
    'lire en {stock_unit}. Utilisez une unité de même nature, ou indiquez sur '
    'le produit ce que pèse ou contient un {stock_unit}.',
    'bom_line_self_reference': (
        'Une ligne de formule ne peut pas référencer le produit lui-même — '
        'le produit deviendrait un ingrédient de sa propre formule.'
    ),
    'bom_line_cycle': (
        'Cette ligne refermerait un cycle : le produit deviendrait un '
        'ingrédient de sa propre formule.'
    ),
    'uom_quantity_requires_whole_number': (
        "L'unité {unit} ne compte que des nombres entiers, donc {quantity} ne "
        'peut pas être enregistré. Arrondissez la quantité à un nombre entier.'
    ),
    'uom_quantity_too_many_decimal_places': (
        "L'unité {unit} accepte au plus {places} décimales, donc {quantity} "
        'ne peut pas être enregistré. Arrondissez la quantité à cette '
        'précision.'
    ),
    'item_unit_cannot_be_removed': (
        "L'unité {unit} ne peut pas être retirée : une quantité sans unité "
        'ne dit rien. Choisissez plutôt une autre unité.'
    ),
    'removal_strategy_of_shared_product': (
        "Ce produit vient du catalogue partagé : l'ordre de sortie de "
        'son stock appartient au catalogue et ne peut pas être '
        'modifié pour une seule organisation.'
    ),
    'piece_unit_missing_from_catalogue': (
        "Le catalogue d'unités de cette installation n'a pas d'unité de "
        'pièce, donc « une quantité de quoi » reste sans réponse. Indiquez '
        "l'unité explicitement, ou restaurez le catalogue d'unités standard."
    ),
    'unknown_bulk_action': 'Action groupée inconnue : {action}',
    'equipment_bulk_item_failed': ("Cet équipement n'a pas pu être modifié."),
    'stock_as_of_no_history': (
        'Cette organisation n’enregistre aucun mouvement de stock et '
        'n’a donc aucun historique à présenter. La seule réponse '
        'disponible est le stock du jour.'
    ),
    'stock_as_of_before_ledger': (
        'Le journal des mouvements commence le {starts_at}. Rien '
        'n’est connu avant — pas zéro —, un rapport au {as_of} serait '
        'une supposition.'
    ),
    'stock_as_of_pdf_too_many': (
        'Le rapport compte {total} produits — plus que les {limit} lignes '
        'qu’une impression peut contenir. Exportez-le en tableur ou '
        'choisissez un emplacement pour le restreindre.'
    ),
    'item_create_failed': "Échec de la création de l'article",
    'item_update_failed': "Échec de la mise à jour de l'article",
    'item_delete_failed': "Échec de la suppression de l'article",
    'storage_not_found': 'Emplacement de stockage introuvable',
    'storage_create_failed': "Échec de la création de l'emplacement de stockage",
    'storage_update_failed': "Échec de la mise à jour de l'emplacement de stockage",
    'storage_delete_failed': "Échec de la suppression de l'emplacement de stockage",
    'storage_delete_failed_items': "Impossible de supprimer un emplacement contenant des articles. Déplacez-les ou supprimez-les d'abord.",
    'storage_delete_blocked_by_production_orders': "Impossible de supprimer l'emplacement : il est utilisé par des ordres de production.",
    'storage_type_not_found': "Type d'emplacement de stockage introuvable",
    'storage_type_create_failed': "Échec de la création du type d'emplacement",
    'storage_type_update_failed': "Échec de la mise à jour du type d'emplacement",
    'storage_type_delete_failed': "Échec de la suppression du type d'emplacement",
    'storage_type_exists': "Un type d'emplacement avec ce code existe déjà",
    'storage_type_no_access': "Vous n'avez pas accès à ce type d'emplacement",
    'storage_type_in_use': "Le type d'emplacement est utilisé par {count} emplacements",
    'storage_usage_immutable': "La destination d'un emplacement est définie par le système et ne peut pas être modifiée.",
    'storage_type_system_modify': "Les types d'emplacement système ne peuvent pas être modifiés",
    'storage_type_system_delete': "Les types d'emplacement système ne peuvent pas être supprimés",
    'category_not_found': 'Catégorie introuvable',
    'category_create_failed': 'Échec de la création de la catégorie',
    'category_update_failed': 'Échec de la mise à jour de la catégorie',
    'category_delete_failed': 'Échec de la suppression de la catégorie',
    'storage_archived': "Cet emplacement est archivé. Restaurez-le avant d'y stocker des produits.",
    'stock_take_not_found': 'Inventaire introuvable',
    'stock_take_already_completed': "L'inventaire a déjà été terminé",
    'stock_take_not_in_progress': "L'inventaire n'est pas en cours",
    'stock_take_create_failed': "Échec de la création de l'inventaire",
    'stock_take_update_failed': "Échec de la mise à jour de l'inventaire",
    'shopping_list_not_found': 'Liste de courses introuvable',
    'shopping_list_create_failed': 'Échec de la création de la liste de courses',
    'shopping_list_update_failed': 'Échec de la mise à jour de la liste de courses',
    'shopping_list_not_writable': 'Cette liste de courses est {status} et ne peut pas être modifiée. Réactivez-la d’abord.',
    'shopping_list_delete_failed': 'Échec de la suppression de la liste de courses',
    'shopping_list_item_not_found': 'Article de la liste de courses introuvable',
    'shopping_list_item_quantity_rounds_to_zero': "La quantité {quantity} s'arrondit à zéro à la précision du stockage — la plus petite valeur enregistrable est {smallest}",
    'shopping_list_item_quantity_above_ceiling': 'La quantité {quantity} dépasse la capacité de la colonne — la plus grande valeur enregistrable est {ceiling}',
    'shopping_list_item_uom_unknown': "Unité de mesure inconnue (uom_id : {uom_id}) — l'unité n'existe pas",
    'shopping_list_item_item_unknown': "Produit inconnu (item_id : {item_id}) — le produit n'existe pas",
    'shopping_list_item_category_unknown': "Catégorie inconnue (category_id : {category_id}) — la catégorie n'existe pas",
    'shopping_list_item_template_unknown': "Modèle de produit inconnu (template_id : {template_id}) — le modèle n'existe pas",
    'organization_not_found': 'Organisation introuvable',
    'organization_create_failed': "Échec de la création de l'organisation",
    'organization_update_failed': "Échec de la mise à jour de l'organisation",
    'organization_delete_failed': "Échec de la suppression de l'organisation",
    'smtp_not_configured': "Aucun envoi d'e-mail n'est configuré pour cette organisation",
    'demo_smtp_settings_locked': "Ceci est la démo publique : le serveur de messagerie est donc fixe. Chaque message que l'application enverrait est capturé dans la boîte de réception de la démo. Les paramètres e-mail ne peuvent pas être modifiés ici.",
    'demo_credentials_locked': "Ceci est la démo publique, où chaque e-mail arrive dans une boîte publique. Les mots de passe ne peuvent pas être modifiés ni réinitialisés ici, et les visiteurs n'ont pas besoin de compte.",
    'demo_registration_locked': "Ceci est la démo publique, où les visiteurs n'ont pas besoin de compte. « Demander l'accès » n'est pas disponible ici — utilisez « Essayer la démo ».",
    'role_in_use': "Ce rôle est encore attribué à quelqu'un. Changez d'abord son rôle, puis supprimez-le.",
    'role_name_taken': 'Un rôle nommé "{name}" existe déjà dans cette organisation.',
    'invitation_not_found': 'Invitation introuvable',
    'organization_invite_invalid': "Cette invitation ne peut pas être utilisée. Vérifiez que vous utilisez l'adresse e-mail à laquelle elle a été envoyée, ou demandez-en une nouvelle.",
    'organization_invite_link_dead': "Ce lien d'invitation ne fonctionne plus. Demandez-en un nouveau à la personne qui vous l'a envoyé.",
    'organization_invite_expired': "L'invitation d'organisation a expiré",
    'email_test_failed': "Impossible d'envoyer l'e-mail de test",
    'module_org_required': 'Pour gérer les modules, vous devez appartenir à une organisation. Reconnectez-vous ou contactez le support.',
    'module_premium_locked': "Le module « {module} » est une fonctionnalité payante. Contactez l'administration du système pour l'activer pour votre organisation.",
    'module_always_on': 'Le module « {module} » est toujours actif et ne peut pas être désactivé.',
    'module_requires_other': "Le module « {required} » doit d'abord être activé.",
    'module_blocks_dependent': "Le module « {dependent} » dépend de « {module} » et est actuellement actif. Désactivez d'abord « {dependent} ».",
    'webhook_url_loopback': "Cette adresse pointe vers le serveur lui-même ({host}) : l'appel ne quitterait jamais la machine. Utilisez une adresse joignable depuis Internet, ou demandez à la personne qui gère cette installation d'autoriser les adresses locales (paramètre WEBHOOKS_ALLOW_PRIVATE_NETWORKS).",
    'webhook_url_private': "Cette adresse ({host}) n'est pas routable publiquement ou est réservée à l'infrastructure des protocoles ; le serveur refuse de l'appeler. Utilisez une adresse joignable depuis Internet, ou demandez à la personne qui gère cette installation d'autoriser les adresses locales (paramètre WEBHOOKS_ALLOW_PRIVATE_NETWORKS).",
    'webhook_url_unresolved': "Le nom d'hôte « {host} » n'a pas pu être résolu : l'adresse ne peut pas être vérifiée. Utilisez un nom résolvable publiquement, ou demandez à la personne qui gère cette installation d'autoriser les adresses locales (paramètre WEBHOOKS_ALLOW_PRIVATE_NETWORKS).",
    'webhook_url_rebinding': "Le nom d'hôte « {host} » résout vers une adresse qui n'est pas routable publiquement ou est réservée à l'infrastructure des protocoles ({resolved}). Utilisez une adresse joignable depuis Internet, ou demandez à la personne qui gère cette installation d'autoriser les adresses locales (paramètre WEBHOOKS_ALLOW_PRIVATE_NETWORKS).",
    'reg_request_new_title': "Nouvelle demande d'accès",
    'reg_request_new_content': "L'utilisateur {name} demande l'accès au système.",
    'reg_request_approved_title': 'Demande approuvée',
    'reg_request_approved_content': "L'accès pour {email} a été approuvé par {admin}.",
    'reg_link_undelivered_title': "Lien d'inscription non remis",
    'reg_link_undelivered_content': "L'e-mail contenant le lien d'inscription n'a pas pu être remis à {email}. Transmettez-lui vous-même ce lien : {link}",
    'reg_request_rejected_title': 'Demande rejetée',
    'reg_request_rejected_content': "L'accès pour {email} a été rejeté par {admin}.",
    'reconciliation_drift_title': 'Écart de stock détecté',
    'reconciliation_drift_content': (
        'Le rapprochement des stocks planifié a trouvé des chiffres qui ne '
        'concordent pas — {pairs}. Voir : Statistiques → Rapprochement.'
    ),
    'reconciliation_drift_standing_title': 'L’écart de stock persiste',
    'reconciliation_drift_standing_content': (
        'L’écart signalé précédemment n’a pas changé et persiste — {pairs}. '
        'Voir : Statistiques → Rapprochement.'
    ),
    'reconciliation_pair_quant_ledger': 'étagère vs journal des mouvements : {count}',
    'reconciliation_pair_layer_quant': 'historique des coûts vs étagère : {count}',
    'event_delivery_dead_title': 'Une tâche en arrière-plan échoue sans cesse',
    'event_delivery_dead_content': (
        'Le gestionnaire {handler} de l’événement {event} a échoué {attempts} fois et a été arrêté. Dernière erreur : {error}. L’événement est conservé dans event_deliveries pour examen.'
    ),
    'field_required': 'Ce champ est obligatoire',
    'invalid_email': "Format d'e-mail invalide",
    'password_too_short': 'Le mot de passe doit comporter au moins 8 caractères',
    'password_invalid': 'Le mot de passe doit contenir au moins une majuscule, une minuscule et un chiffre',
    'password_too_long': 'Le mot de passe peut contenir au maximum {max_bytes} octets',
    'password_needs_lowercase': 'Le mot de passe doit contenir au moins une lettre minuscule',
    'password_needs_uppercase': 'Le mot de passe doit contenir au moins une lettre majuscule',
    'password_needs_digit': 'Le mot de passe doit contenir au moins un chiffre',
    'sku_format_invalid': 'Le SKU ne peut contenir que des lettres, des chiffres, des tirets, des tirets bas et des barres obliques',
    'sku_in_use': 'Le SKU {sku} appartient déjà à un autre produit',
    'custom_field_required': 'Le champ « {field} » est obligatoire',
    'field_multi_select_shape': 'Le champ « {field} » doit être une liste d’options',
    'field_option_not_allowed': 'La valeur « {value} » ne fait pas partie des options du champ « {field} » : {options}',
    'field_money_shape': 'Le champ « {field} » doit contenir un montant et une devise, rien d’autre',
    'field_money_amount': 'Le montant du champ « {field} » doit être un nombre',
    'field_money_currency': 'La devise du champ « {field} » doit être un code ISO 4217 de 3 lettres, par exemple EUR',
    'field_select_shape': 'Le champ « {field} » doit avoir une seule option',
    'item_limit_reached': 'Cette organisation a atteint la limite d’articles. Passez à Inventari Cloud.',
    'item_archived': 'L’article est archivé et peut être restauré depuis les archives',
    'announcement_type_invalid': "Type d'annonce non valide. Autorisés : {allowed}",
    'ai_provider_invalid': 'Fournisseur non valide. Autorisés : {allowed}',
    'field_options_required': "Un champ de type {type} nécessite une liste d'options non vide",
    'member_role_exactly_one': 'Indiquez exactement un des champs role ou role_id',
    'reason_blank': 'Le motif ne peut pas être vide',
    'discrepancy_reason_required': "Un motif d'écart est requis",
    'invalid_uuid': 'Format UUID invalide',
    'sheet_unreadable': "Ce fichier n'a pas pu être lu comme un tableur. Vérifiez qu'il s'agit d'un fichier .xlsx ou .csv valide, puis réessayez.",
    'pasted_text_unreadable': "Le texte collé n'a pas pu être lu comme un tableau. Collez des lignes copiées depuis un tableur, avec le même nombre de colonnes partout.",
    'webhook_url_malformed': "Ce n'est pas une adresse web valide. Saisissez une adresse complète, par exemple https://example.com/hook.",
    'recipe_extraction_failed': "La recette n'a pas pu être extraite de cette page. Réessayez ou saisissez la recette à la main.",
    'invalid_date': 'Format de date invalide',
    'value_must_be_positive': 'La valeur doit être positive',
    'value_must_be_greater_than_zero': 'La valeur doit être supérieure à zéro',
    'insufficient_quantity': 'Stock insuffisant pour effectuer cette action',
    'file_type_not_allowed': 'Type de fichier non autorisé',
    'file_signature_mismatch': 'La signature du fichier ne correspond pas au type déclaré',
    'file_too_large': 'Le fichier dépasse la taille maximale autorisée (10 Mo)',
    'file_type_not_allowed_list': 'Type de fichier non autorisé. Autorisés : {allowed}',
    'file_content_type_missing': "Le fichier n'indique pas son type (l'en-tête Content-Type est absent).",
    'file_empty': 'Le fichier est vide.',
    'file_not_webp': "Ce fichier n'est pas une image WebP valide.",
    'import_too_many_rows': 'Le fichier compte {count} lignes ; la limite est de {limit}. Découpez-le en fichiers plus petits.',
    'storage_location_ambiguous': '« {text} » correspond à {count} emplacements de stockage ({shown}). Indiquez plutôt le chemin complet, par exemple « {example} ».',
    'pagination_cursor_invalid': 'Curseur de pagination invalide ou expiré',
    'webhook_url_scheme': 'Seules les adresses {schemes} sont autorisées pour les webhooks.',
    'webhook_url_no_hostname': "L'adresse du webhook doit inclure un nom d'hôte, par exemple https://example.com/hook.",
    'picking_already_picked': '{name} a déjà été prélevé',
    'picking_unit_mismatch': (
        'Impossible de comparer les unités de {name} — la recette et le '
        'stock utilisent des mesures différentes. Renseignez le poids ou le '
        "contenu d'une unité de stock, puis scannez à nouveau."
    ),
    'picking_picked': '{name} ✓ — {quantity} déduits',
    'invalid_mapping_json': 'JSON de mappage invalide',
    'extra_cost_not_a_receipt': 'Les frais annexes appartiennent à une réception : seule la marchandise qui arrive peut porter le coût de son acheminement.',
    'extra_cost_document_posted': (
        "Cette réception est déjà comptabilisée, un frais ne peut donc plus y être ajouté : la marchandise a pu quitter le stock et il n'y a plus rien à charger. Émettez plutôt une correction pendant que la période est ouverte."
    ),
    'extra_cost_currency_mismatch': (
        "Le frais est dans une devise différente de celle du document. Saisissez-le dans la devise du document : convertir à un taux que personne n'a enregistré mettrait dans la valeur du stock un chiffre sans historique."
    ),
    'document_shipment_dispatch_only': "Seule une expédition enregistre un envoi : le transporteur emporte des marchandises qui quittent l'entrepôt.",
    'document_tracking_template_invalid': 'Le lien de suivi pour « {carrier} » doit être une adresse web commençant par https:// ou http:// et contenant {{tracking_number}} à la place du numéro.',
    'packing_not_a_dispatch': "Seule une expédition se colise : les colis contiennent des marchandises qui quittent l'entrepôt.",
    'packing_document_not_open': "Les colis ne peuvent être modifiés que tant que l'expédition est confirmée et pas encore terminée. Une expédition terminée garde ses colis tels qu'ils ont été expédiés.",
    'packing_exceeds_picked': '{name} : seulement {remaining} préparé(s) et pas encore emballé(s). Un colis contient ce qui a été préparé, et rien de ce qui est déjà dans un autre colis.',
    'packing_exceeds_done': "{name} : les colis contiennent {packed}, plus que les {done} expédiés par cette expédition. Retirez d'abord la différence des colis, ou terminez avec la quantité qu'ils contiennent.",
    'packing_nothing_to_pack': 'Tout ce qui a été préparé est déjà emballé, il ne reste rien pour un nouveau colis.',
    'packing_no_packages': "Cette expédition n'a pas encore de colis, il n'y a donc pas de bordereau de colisage à imprimer. Emballez-la d'abord.",
    'package_not_found': 'Colis introuvable',
    'packing_scan_unrecognized': "Aucun produit ne porte le code {code}. Scannez le code-barres du produit lui-même, ou touchez sa ligne pour l'emballer.",
    'packing_scan_not_in_document': '{name} ne figure pas dans cette expédition et ne va donc dans aucun de ses colis.',
    'invalid_image_extension': "Extension d'image invalide",
    'invalid_role': 'Rôle invalide. Autorisés : {roles}',
    'role_not_in_organization': "Le rôle n'appartient pas à cette organisation",
    'failed_to_read_file': 'Impossible de lire le fichier : {error}',
    'only_image_files_allowed': 'Seuls les fichiers image sont autorisés (jpg, png, gif, webp)',
    'image_unreadable': "Ce fichier n'a pas pu être lu comme une image",
    'image_too_large': 'Image trop grande (max {limit})',
    'demo_upload_file_limit': 'La démo accepte des fichiers de {limit} maximum',
    'demo_upload_total_limit': 'La démo a atteint sa limite de fichiers ({limit}). Les envois reprendront après la prochaine réinitialisation',
    'demo_sandbox_cap_reached': "La démo a distribué toutes ses copies pour aujourd'hui. Revenez demain",
    'demo_sandbox_pool_empty': 'Toutes les copies de la démo sont prises pour le moment ; de nouvelles sont en préparation. Réessayez dans une minute',
    'barcode_or_sku_required': 'Le paramètre barcode ou sku est requis',
    'barcode_names_one_record': 'Un code-barres ne peut pas désigner {count} enregistrements : {barcode}',
    'storage_no_short_code': "L'emplacement n'a pas de code court. Générez-en un d'abord.",
    'refresh_token_expired_grace': "Jeton d'actualisation expiré au-delà du délai de grâce",
    'refresh_token_revoked': "Jeton d'actualisation révoqué",
    'cannot_remove_yourself': 'Vous ne pouvez pas vous retirer vous-même',
    'cannot_change_own_role': 'Vous ne pouvez pas modifier votre propre rôle',
    'label_in_use_by_product': "Impossible de supprimer une étiquette attribuée à un produit actif. Supprimez d'abord le produit.",
    'label_already_assigned': 'Étiquette déjà attribuée',
    'no_labels_available': "Aucune étiquette disponible pour l'impression",
    'unauthorized': 'Authentification requise',
    'forbidden': 'Accès refusé',
    'organization_required': 'Organisation requise',
    'not_found': 'Ressource introuvable',
    'conflict': 'Conflit de ressources',
    'internal_error': "Une erreur interne s'est produite",
    'rate_limit_exceeded': 'Trop de requêtes. Réessayez plus tard.',
    'service_unavailable': 'Service temporairement indisponible',
    'stock_take_edit_completed': 'Impossible de modifier un inventaire terminé ou annulé',
    'stock_take_delete_completed': 'Seuls les brouillons ou les inventaires actifs peuvent être supprimés',
    'stock_take_not_active': "L'inventaire n'est pas actif",
    'stock_take_surplus_item_id_required': 'Choisissez le produit auquel correspond cet article en surplus.',
    'stock_take_surplus_quantity_required': 'Saisissez la quantité comptée pour cet article en surplus.',
    'stock_lot_not_found': 'Lot de stock introuvable',
    'stock_moves_export_too_many': '{total} mouvements correspondent — plus que les {limit} qu’une feuille peut contenir. Réduisez les dates, le lieu ou le produit, puis exportez à nouveau.',
    'stock_take_close_requires_finalize': 'Un inventaire se clôture par sa finalisation (POST /stock-takes/{id}/complete), pas par un changement de statut',
    'period_already_closed': 'La période {period} est déjà fermée.',
    'period_closed_for_date': 'La période {period} est fermée : rien ne peut y être daté. Changez la date du document ou demandez à une personne autorisée de rouvrir la période.',
    'period_closed_for_stock_change': 'La période {period} est fermée : aucun mouvement de stock ne peut y être enregistré. Demandez à une personne autorisée de rouvrir la période.',
    'transfer_more_than_the_record_holds': "L'enregistrement « {item_name} » contient {available} et la ligne en déplace {requested}. Réduisez la quantité de la ligne ou déplacez le reste depuis un autre enregistrement.",
    'transfer_cannot_split_serialized_record': 'Le transfert ne peut pas diviser un enregistrement sérialisé ({serial_number}) : transférez le relevé entier.',
    'use_partially_more_than_left': "L'enregistrement « {item_name} » contient {available} de cet emballage et il a été indiqué qu'il en reste {requested}. Indiquez ce qu'il reste, sans dépasser ce qu'il y a.",
    'use_partially_serialized': "L'enregistrement sérialisé {serial_number} ne peut pas être ouvert et divisé ; utilisez-le en entier.",
    'use_partially_needs_counted_unit': "« {item_name} » est tenu dans une unité de mesure : il n'y a pas d'emballage à ouvrir. Retirez du stock ce que vous utilisez.",
    'use_partially_pack_has_no_measure': "« {item_name} » est compté en emballages et le produit n'indique pas ce que contient chacun : seuls « ouvert » ou « terminé » peuvent être enregistrés.",
    'use_by_needs_open_package': "L'enregistrement « {item_name} » est fermé : il n'a pas de date limite d'utilisation. Ouvrez-le d'abord ; d'ici là, la date du lot fait foi.",
    'period_not_closed': "La période {period} n'est pas fermée.",
    'wms_session_now_held_by': "Cette session est désormais chez {owner} ; plus aucun scan n'est accepté d'ici.",
    'wms_session_held_by_other_user': "Une session d'un autre utilisateur est active sur ce document (ouverte par {owner}).",
    'wms_pick_document_not_found': "Le document {document} est introuvable dans cette organisation : la session de préparation n'a pas été lancée.",
    'wms_pick_document_not_confirmed': "Le document {number} n'est pas confirmé : la session de préparation n'a pas été lancée. Seuls les documents confirmés peuvent être préparés.",
    'wms_pick_document_not_dispatch': "Le document {number} n'est pas une expédition : la session de préparation n'a pas été lancée. Seules les expéditions peuvent être préparées ensemble.",
    'wms_pick_document_in_session': "Le document {number} est déjà en préparation dans une autre session (ouverte par {owner}) : la session de préparation n'a pas été lancée.",
    'wms_line_document_closed': 'Le document {number} est {status} : ses lignes dans cette session ne peuvent plus être modifiées.',
    'wms_short_below_scanned': 'La quantité finale ne peut pas être inférieure à la quantité scannée ({scanned}) ; pour enregistrer moins, elle doit remplacer les scans.',
    'wms_short_pick_needs_outcome': 'Une ligne prélevée en moins demande un motif : « Manquant » laisse le reste dû dans un reliquat, tout autre motif clôt l’écart.',
    'wms_session_not_found': 'La session active est introuvable. Elle a peut-être déjà été terminée ou annulée.',
    'wms_line_not_found': 'La ligne de session est introuvable.',
    'wms_line_not_pending': "La ligne de session est introuvable ou n'est plus en attente.",
    'wms_quantity_cannot_be_negative': 'La quantité ne peut pas être négative.',
    'wms_quantity_above_expected': 'La quantité ne peut pas dépasser la quantité attendue.',
    'wms_cannot_complete_no_lines': "Impossible de terminer la session : elle n'a aucune ligne.",
    'wms_cannot_complete_lines_pending': 'Impossible de terminer la session : {count} ligne(s) sont encore en attente.',
    'wms_cannot_complete_destination_not_scanned': 'Impossible de terminer la session : l’emplacement de destination n’a pas encore été scanné.',
    'wms_document_not_confirmed': "Le document est introuvable ou n'est pas confirmé.",
    'wms_document_type_not_supported': 'Cette session ne traite pas les documents de type {document_type}.',
    'wms_nothing_to_undo': "Cette ligne n'a rien d'enregistré à annuler.",
    'wms_undo_line_is_packed': "{name} : un colis contient déjà {packed} de ce qui a été préparé. Retirez-le d'abord du colis, puis annulez la préparation.",
    'wms_skip_line_is_packed': "{name} : un colis contient déjà {packed} de ce qui a été préparé. Retirez-le d'abord du colis, puis ignorez la ligne.",
    'wms_cancel_session_is_packed': "{name} : un colis contient déjà {packed} de ce qui a été préparé. Retirez-le d'abord du colis, puis annulez la session.",
    'wms_barcode_required': "Scannez d'abord un code-barres.",
    'document_execution_line_foreign': "Cette ligne d'exécution n'appartient pas à ce document.",
    'document_execution_line_repeated': "Chaque ligne du document ne peut être exécutée qu'une fois.",
    'document_done_quantity_negative': 'La quantité exécutée ne peut pas être négative : {quantity}.',
    'document_done_quantity_above_expected': 'La quantité exécutée {quantity} dépasse la quantité attendue (max. {expected}).',
    'document_held_quantity_negative': 'La quantité retenue ne peut pas être négative : {quantity}.',
    'document_held_quantity_above_received': 'La quantité retenue {quantity} dépasse la quantité reçue ({received}).',
    'document_held_quantity_needs_receipt': 'Seule une réception peut retenir des marchandises.',
    'document_held_quantity_needs_code': 'Une quantité retenue nécessite le code Dommage ou Retenu pour la qualité.',
    'document_partial_needs_discrepancy_code': "Une exécution partielle nécessite un code d'écart.",
    'document_correction_above_expected': 'Une correction de {quantity} dépasse la quantité attendue {expected} en valeur absolue.',
    'document_correction_sign_mismatch': "Une correction doit conserver le signe de l'écart attendu : {quantity} face à {expected}.",
    'document_correction_missing_original': "Cette correction n'indique pas le document qu'elle corrige.",
    'document_correction_original_not_found': 'Le document corrigé {document} est introuvable.',
    'document_correction_would_go_negative': 'La correction ferait passer {item} sous zéro : actuel {current}, variation {delta}, résultat {result}.',
    'document_adjustment_would_go_negative': "L'ajustement ferait passer {item} sous zéro : actuel {current}, variation {delta}, résultat {result}.",
    'document_line_needs_identity': 'La ligne du document doit indiquer un enregistrement, un produit ou un nom.',
    'document_rework_wrong_status': "Un document au statut {status} ne peut pas revenir au brouillon ; seuls un document confirmé ou en attente d'approbation le peuvent.",
    'stock_record_not_found': "L'enregistrement {item} est introuvable.",
    'stock_product_not_found': 'Le produit {product} est introuvable.',
    'stock_insufficient_record': 'Stock insuffisant pour « {item} » : disponible {available}, demandé {requested}.',
    'receipt_needs_target_location': "Le document de réception n'a pas d'emplacement de destination.",
    'receipt_needs_quarantine_location': "La réception contient des marchandises endommagées ou bloquées pour la qualité, mais le profil des documents n'indique aucun emplacement de quarantaine. Indiquez-en un dans les paramètres des documents.",
    'transfer_needs_target_location': "Le document de transfert n'a pas d'emplacement de destination.",
    'receiving_mode_needs_a_warehouse': 'Seul un emplacement de premier niveau choisit sa façon de réceptionner.',
    'putaway_needs_another_location': "La marchandise est déjà ici : choisissez l'emplacement où elle va.",
    'replenishment_nothing_to_move': "Il n'y a rien à prendre en réserve : la marchandise n'y est plus, ou l'emplacement n'en a plus besoin.",
    'replenishment_shelf_scan_required': "Scannez l'emplacement de réserve d'où vous prenez la marchandise.",
    'replenishment_shelf_scan_mismatch': "Ce code désigne un autre emplacement : scannez l'emplacement de réserve d'où la marchandise est prise.",
    'putaway_shelf_scan_required': "Scannez l'étiquette de l'emplacement avant de ranger la marchandise.",
    'home_shelf_receiving': "Une zone de réception ne peut pas être un emplacement habituel : la marchandise n'y fait qu'attendre.",
    'home_shelf_quarantine': "Un emplacement de quarantaine ne peut pas être un emplacement habituel : la marchandise retenue n'y est pas rangée.",
    'home_shelf_not_stock': 'Cet emplacement ne reçoit pas de stock : il ne peut pas être un emplacement habituel.',
    'stock_take_status_unchangeable': 'Impossible de changer le statut de {current} à {new}.',
    'api_keys_limit_reached': "L'organisation a déjà {count} clés API actives, soit le maximum. Révoquez-en une pour en créer une autre.",
    'document_pdf_requires_confirmed': "Un PDF est produit à partir d'un document confirmé ou terminé. Celui-ci est {status}.",
    'documents_pdf_require_confirmed': "Un PDF groupé n'est produit qu'à partir de documents confirmés ou terminés. Non imprimables : {numbers}.",
    'stock_take_item_not_found': "Position d'inventaire introuvable",
    'stock_take_item_already_exists': "L'article a déjà été ajouté à cet inventaire",
    'stock_take_item_outside_location': "Cet article se trouve hors de l'emplacement inventorié ; le compter ici écraserait la quantité qu'il y possède",
    'stock_take_shelf_outside_location': "Cet emplacement ne fait pas partie de l'inventaire de {location}",
    'stock_take_uncounted_items': 'Il reste {count} articles non comptés',
    'stock_none_at_location': "Il n'y a pas de {product} à l'emplacement {location}.",
    'stock_all_batches_held': "Chaque lot de {product} à l'emplacement {location} est en quarantaine ou bloqué, rien ne peut donc être utilisé.",
    'stock_not_enough': "L'emplacement {location} dispose de {available} de {product} et {requested} ont été demandés.",
    'stock_take_over_cap': 'Pour {count} article(s), la quantité comptée dépasse largement le stock du système. Vérifiez-les puis confirmez pour enregistrer les quantités comptées.',
    'stock_take_over_tolerance': "Pour {count} article(s), la quantité comptée s'écarte du stock système au-delà de la tolérance de cet inventaire. Quelqu'un qui en a le droit doit les accepter avant leur comptabilisation.",
    'stock_take_tolerance_reason_missing': "Pour {count} article(s), l'écart dépasse la tolérance et le motif manque. Donnez un motif à chacun, puis terminez l'inventaire.",
    'stock_take_tolerance_not_allowed': "Accepter un écart au-delà de la tolérance demande le droit d'approbation des inventaires.",
    'stock_take_awaiting_recount': "Pour {count} article(s), un recomptage a été demandé. Recomptez-les, puis terminez l'inventaire.",
    'stock_take_stock_moved': "{count} ligne(s) ont été comptées sur une quantité que le stock n'a plus. Elles ont été renvoyées pour être recomptées.",
    'document_not_found': 'Document introuvable',
    'work_item_not_found': 'Tâche introuvable',
    'work_item_taken': 'Quelqu’un d’autre vient de prendre cette tâche.',
    'pdf_generation_failed': 'Échec de la génération du PDF',
    'import_only_draft': 'Les lignes ne peuvent être importées que dans les documents BROUILLON',
    'paste_empty': "Aucune ligne à importer — collez au moins une ligne d'en-tête et une ligne de données",
    'import_asset_name_missing': 'Nom de l’équipement manquant',
    'import_line_name_missing': 'Nom de produit manquant',
    'import_location_unresolved': 'Emplacement de stockage introuvable',
    'import_location_not_found': 'Aucun emplacement ne s’appelle « {value} »',
    'import_price_invalid': 'Colonne « {column} » : « {value} » n’est pas un prix',
    'import_date_invalid': 'Colonne « {column} » : « {value} » n’est pas une date',
    'import_job_failed': 'L’importation s’est arrêtée à cause d’une erreur inattendue.',
    'import_job_interrupted': 'L’importation a été interrompue avant la fin.',
    'import_column_not_a_number': 'Colonne « {column} » : « {value} » n’est pas un nombre',
    'import_quantity_not_positive': 'Colonne « {column} » : la quantité doit être supérieure à zéro, « {value} » ne l’est pas',
    'import_column_location_not_found': 'Colonne « {column} » : emplacement « {value} » introuvable',
    'import_column_category_not_found': 'Colonne « {column} » : catégorie « {value} » introuvable',
    'import_unknown_unit': 'Colonne « {column} » : unité inconnue « {value} ». Unités connues : {units}',
    'import_column_not_yes_no': 'Colonne « {column} » : « {value} » n’est ni oui ni non',
    'import_column_not_in_options': 'Colonne « {column} » : « {value} » ne fait pas partie des choix : {options}',
    'import_column_quantity_blank': 'Colonne « {column} » : la quantité est vide. Renseignez-la ou retirez l’association de la quantité pour importer chaque ligne comme 1',
    'import_column_field_shape': 'Colonne « {column} » : la valeur ne convient pas au champ auquel la colonne est associée',
    'import_field_required_unreadable': 'Le champ « {field} » est obligatoire et ne peut pas être lu depuis une cellule',
    'import_field_required_no_column': 'Le champ « {field} » est obligatoire et le fichier n’a pas de colonne pour lui',
    'import_column_field_required': 'Colonne « {column} » : le champ est obligatoire',
    'import_column_reason': 'Colonne « {column} » : {reason}',
    'import_row_failed': 'La ligne n’a pas pu être importée',
    'document_lines_quantity_not_positive': 'Les lignes {lines} ont une quantité inférieure ou égale à zéro. Corrigez-les avant de confirmer.',
    'document_delivery_lines_reference_items': "Les lignes d'un document de livraison doivent référencer des produits existants",
    'document_scrap_lines_reference_items': "Les lignes d'un document de rebut doivent référencer des produits existants",
    'document_reason_scrap_only': 'Seul un document de rebut peut porter un motif de mise au rebut',
    'document_scrap_reason_required': 'Un document de rebut dit pourquoi la marchandise est sortie : choisissez un motif et, pour « Autre », écrivez-le dans les remarques',
    'document_transfer_lines_reference_items': "Les lignes d'un document de transfert doivent référencer des produits existants",
    'document_correction_lines_reference_items': "Les lignes d'un document de correction doivent référencer des produits existants",
    'document_adjustment_lines_reference_items': "Les lignes d'un document d'ajustement doivent référencer des produits existants",
    'recipe_collection_name_taken': 'Une collection de recettes nommée « {name} » existe déjà dans cette organisation.',
    'recipe_name_taken': 'Une formule portant ce nom existe déjà pour ce produit.',
    'recipe_not_found': 'Recette introuvable',
    'picking_active_recipe_locked': "Les ingrédients ne peuvent pas être modifiés tant qu'une session de prélèvement est active. Annulez ou terminez d'abord la session.",
    'meal_plan_dates_exclude_entries': "Supprimez d'abord les entrées des dates exclues.",
    'meal_plan_position_taken': "Aucune position libre n'a été trouvée dans ce repas.",
    'meal_plan_entry_date_out_of_range': "La date de l'entrée est en dehors de la période du plan.",
    'meal_plan_slot_not_enabled': "Ce repas n'est pas activé pour ce plan.",
    'shopping_exclusion_exists': 'Cette exclusion existe déjà.',
    'shopping_item_already_purchased': 'Cet article est déjà marqué comme acheté.',
    'shopping_item_already_purchased_reset': "Cet article est déjà marqué comme acheté. Marquez-le d'abord comme non acheté pour le modifier.",
    'shopping_list_not_editable': 'Une liste de courses terminée ou archivée ne peut pas être modifiée.',
    'shopping_lists_module_disabled': "Le module Listes de courses n'est pas activé pour cette organisation.",
    'maker_recipe_not_found': 'Formule introuvable',
    'uom_quantity_non_negative': 'La quantité ne peut pas être négative',
    'uom_conversion_unavailable': (
        'La quantité en {unit} ne peut pas être convertie en unité de '
        'stock {stock_unit}'
    ),
    'webhook_not_found': 'Webhook introuvable',
    'putaway_rule_not_found': 'Règle de rangement introuvable',
    'document_line_not_found': 'Ligne de document introuvable',
    'putaway_unknown_context_tag': 'Groupe de catégories « {value} » inconnu — choisissez-en un défini par une catégorie existante',
    'putaway_unknown_storage_type': "Type de stockage « {value} » inconnu — choisissez l'un des types de stockage de l'organisation",
    'location_not_internal': '« {name} » est un emplacement virtuel — la marchandise ne peut être rangée que dans des emplacements réels',
    'location_archived': '« {name} » est archivé — restaurez-le d’abord ou choisissez un emplacement encore visible dans les listes',
    'line_target_receipt_only': 'La destination ne peut être indiquée que sur les lignes de réception — les lignes de sortie et de transfert prennent leur emplacement sur le document',
    'line_target_already_received': "Cette ligne a déjà été reçue dans la session de réception en cours ; la marchandise reste à l'emplacement où elle a été reçue",
    'exclusion_not_found': 'Exclusion introuvable',
    'tag_not_found': "Tag '{tag}' introuvable dans aucune recette",
    'meal_plan_not_found': 'Plan de repas introuvable',
    'meal_plan_slot_conflict': 'Des entrées existent dans les créneaux désactivés : {slots}',
    'meal_plan_entry_not_found': 'Entrée du plan de repas introuvable',
    'attachment_not_found': 'Pièce jointe introuvable',
    'api_key_not_found': 'Clé API introuvable',
    'invalid_api_key': 'Clé API invalide ou expirée',
    'api_key_owner_inactive': 'Le compte auquel appartient cette clé API est inactif.',
    'unit_conversion_already_exists': 'Une conversion depuis {unit} pour « {ingredient} » existe déjà dans cette organisation. Modifiez-la au lieu de la créer.',
    'conversion_not_found': 'Conversion introuvable',
    'conversion_not_found_or_system': 'Conversion introuvable ou système par défaut',
    'template_not_found': 'Modèle introuvable',
    'template_import_not_json': "Le fichier n'a pas pu être lu comme un export de modèle — ce n'est pas du JSON valide.",
    'template_import_wrong_kind': "Ce fichier n'est pas un modèle de document exporté.",
    'template_import_wrong_version': 'Le fichier a été exporté au format version {version} ; cette installation lit la version {supported}.',
    'template_import_invalid_field': 'Le champ « {field} » est absent ou invalide.',
    'template_import_unknown_placeholders': 'Le modèle référence des champs qui n’existent pas : {placeholders}.',
    'template_import_not_renderable': 'Le modèle n’a pas pu être rendu : {detail}',
    'model_not_found': "Modèle d'équipement introuvable",
    'widget_not_found': 'Widget introuvable',
    'bom_line_not_found': 'Ligne de nomenclature introuvable',
    'bom_line_already_exists': (
        'Cette formule contient déjà cet ingrédient — une ligne entre les deux '
        'produits existe déjà.'
    ),
    'bom_depth_exceeded': (
        'Cette nomenclature est imbriquée sur plus de {max_depth} niveaux — '
        'trop profonde pour être résolue.'
    ),
    'cost_line_not_found': 'Ligne de coût introuvable',
    'production_order_not_found': 'Ordre de production introuvable',
    'production_no_recipe': (
        "Aucune formule pour ce produit — créez d'abord une formule"
    ),
    'production_recipe_not_found': (
        'Formule {recipe_id} introuvable dans cette organisation'
    ),
    'production_recipe_product_mismatch': ("La formule n'appartient pas à ce produit"),
    'production_complete_not_draft': (
        'Cet ordre de fabrication a déjà le statut {status} — seul un '
        'brouillon peut être terminé.'
    ),
    'production_reverse_not_completed': (
        "Cette production a le statut {status}, il n'y a donc rien à reprendre — seule une production terminée peut être annulée."
    ),
    'production_reverse_output_used': (
        "Cette production ne peut pas être annulée : une partie de ce qu'elle a fabriqué a déjà quitté son emplacement. Enregistrez plutôt une correction de stock pour ce qui reste."
    ),
    'production_cancel_not_draft': (
        'Cet ordre de fabrication a déjà le statut {status} — seul un '
        'brouillon peut être annulé.'
    ),
    'production_update_not_draft': (
        'Cet ordre de fabrication a déjà le statut {status} — seul un '
        'brouillon peut être modifié.'
    ),
    'production_actual_qty_must_be_positive': (
        'La quantité produite doit être supérieure à zéro.'
    ),
    'production_overproduction_disabled': (
        'La surproduction est désactivée dans les paramètres — cet ordre ne '
        'peut pas produire plus que prévu.'
    ),
    'production_ingredient_unmeasurable': (
        "L'unité d'un ingrédient ne peut pas être comparée à son stock : on ne sait "
        "pas combien retirer de l'étagère — corrigez d'abord l'unité de la ligne de formule."
    ),
    'production_short_of_stock': "Pas assez d'ingrédients en stock pour cet ordre de fabrication.",
    'output_template_not_found': 'Modèle de sortie introuvable',
    'purchase_order_not_found': 'Bon de commande introuvable',
    'reorder_rule_not_found': 'Règle de réapprovisionnement introuvable',
    'pricelist_entry_not_found': 'Entrée de liste de prix introuvable',
    'reorder_max_below_min': 'max_quantity ({max_quantity}) doit être >= min_quantity ({min_quantity})',
    'reorder_safety_stock_negative': 'safety_stock doit être >= 0, valeur {safety_stock}',
    'reorder_min_quantity_negative': 'min_quantity doit être >= 0, valeur {min_quantity}',
    'pricelist_unit_price_not_positive': 'unit_price doit être > 0, valeur {unit_price}',
    'pricelist_min_quantity_not_positive': 'min_quantity doit être > 0, valeur {min_quantity}',
    'pricelist_valid_to_before_valid_from': 'valid_to ({valid_to}) doit être >= valid_from ({valid_from})',
    'pricelist_duplicate': (
        'Ce fournisseur a déjà un prix pour ce produit sur les mêmes dates et '
        'avec la même quantité minimale. Modifiez cette entrée au lieu d’en '
        'ajouter une deuxième.'
    ),
    'tax_rate_not_found': 'Taux de taxe introuvable',
    'announcement_not_found': 'Annonce introuvable',
    'approval_request_not_found': "Demande d'approbation introuvable",
    'cycle_count_schedule_not_found': 'Planification de comptage cyclique introuvable',
    'document_type_config_not_found': 'Configuration du type de document introuvable',
    'history_entry_not_found': "Entrée d'historique introuvable",
    'ingredient_not_found': 'Ingrédient introuvable',
    'label_not_found': 'Étiquette introuvable',
    'scan_unrecognized': 'Code non reconnu — aucun produit, étiquette, emplacement ou document ne correspond',
    'member_not_found': 'Membre introuvable',
    'module_not_found': 'Module introuvable',
    'notification_not_found': 'Notification introuvable',
    'partner_not_found': 'Partenaire introuvable',
    'partner_name_exists': 'Un partenaire portant le nom « {name} » et le type « {partner_type} » existe déjà.',
    'partner_code_exists': 'Un partenaire portant le code « {code} » existe déjà.',
    'partner_delete_open_purchase_orders': 'Impossible de supprimer le partenaire : {count} bons de commande ouverts le référencent',
    'partner_import_name_missing': 'Nom du partenaire manquant',
    'partner_import_duplicate': 'Partenaire en double : « {twin} » a déjà ce nom ou cet identifiant fiscal',
    'product_not_found': 'Produit introuvable',
    'product_template_not_found': 'Modèle de produit introuvable',
    'profile_not_found': 'Profil introuvable',
    'receiving_session_not_found': 'Session de réception introuvable',
    'request_not_found': 'Demande introuvable',
    'workflow_not_found': 'Flux de travail introuvable',
    'campaign_not_found': 'Campagne introuvable',
    'attestation_no_active_assignments': 'Aucune affectation active dans le périmètre choisi',
    'attestation_not_draft': 'Cette campagne est déjà {status} — seul un brouillon peut être lancé',
    'attestation_reminders_not_active': 'Les rappels ne partent que pour une campagne en cours',
    'campaign_deadline_past': "L'échéance de la campagne doit être aujourd'hui ou plus tard",
    'attestation_complete_not_allowed': 'Une campagne au statut {status} ne peut pas être terminée',
    'attestation_scope_exceeds_limit': 'Le périmètre couvre plus de {limit} articles. Réduisez-le ou scindez la campagne.',
    'assignment_not_found': 'Attribution introuvable',
    'maintenance_log_not_found': 'Journal de maintenance introuvable',
    'equipment_cannot_checkout_retired': "Impossible d'emprunter une ressource retirée",
    'equipment_cannot_checkout_in_maintenance': "Impossible d'emprunter une ressource en maintenance ; passez-la d'abord à Disponible",
    'equipment_assignment_needs_person_or_location': 'Indiquez la personne ou le lieu, pas les deux',
    'equipment_bulk_scope_too_large': '{matched} ressources correspondent aux filtres ; une action en couvre au plus {limit}. Affinez les filtres.',
    'equipment_assignment_already_active': "L'article a déjà une attribution active",
    'equipment_assignment_already_checked_in': "L'attribut a déjà été retourné",
    'api_key_cannot_manage': "Les clés API ne peuvent pas gérer d'autres clés API",
    'api_key_cannot_create': "Les clés API ne peuvent pas créer d'autres clés API",
    'api_key_cannot_revoke': "Les clés API ne peuvent pas révoquer d'autres clés API",
    'api_key_scope_refused': 'Cette clé API est limitée à {scope} et ne peut pas être utilisée ici',
    'api_key_scope_unknown': "Il n'existe pas de portée de clé API nommée « {scope} »",
    'api_key_permission_not_grantable': 'Une clé API ne peut pas recevoir la permission {permission} : vous ne la détenez pas, ou aucune clé ne la porte',
    'api_key_permission_outside_scope': 'La permission {permission} ne fait pas partie des portées choisies pour cette clé',
    'print_no_agent': "Aucune imprimante n'est connectée. Démarrez Inventari Print Agent à côté de l'imprimante.",
    'print_choose_agent': 'Plusieurs imprimantes sont connectées. Choisissez celle sur laquelle imprimer.',
    'print_agent_protocol_missing': "Cet agent ne dit rien du protocole d'impression qu'il parle : il est antérieur au protocole versionné. Mettez à jour l'agent d'impression.",
    'print_agent_protocol_unsupported': "Cet agent parle le protocole d'impression {agent} ; ce serveur parle le protocole d'impression {server}. Mettez à jour le plus ancien des deux.",
    'print_agent_not_found': 'Imprimante introuvable',
    'print_job_not_found': "Tâche d'impression introuvable",
    'print_job_nothing_to_print': "Rien à imprimer : aucune des étiquettes choisies n'a été trouvée",
    'product_label_no_code': "Rien à imprimer : aucun des produits choisis n'a de code. Générez-en un dans le formulaire du produit",
    'product_label_too_narrow': 'Le code {code} ne tient pas sur une étiquette de {width} mm de large : ses barres demandent au moins {needed} mm. Choisissez une étiquette plus large',
    'product_label_too_short': "L'étiquette de {height} mm de haut est trop basse : après le nom et le texte, il reste trop peu de hauteur aux barres du code {code} pour qu'un lecteur les voie. Choisissez une étiquette plus haute",
    'storage_code_template_invalid': "Le modèle de code « {template} » n'est pas utilisable. Écrivez des champs comme {{zone}}-{{rack:02}}-{{level:02}}, avec un séparateur entre eux, ou un préfixe d'au plus cinq lettres et chiffres comme LOC",
    'storage_code_template_not_tree': 'Cet entrepôt tire des codes au hasard : donnez-lui un modèle avec des champs, comme {zone}-{rack:02}-{level:02}, avant de numéroter ses emplacements',
    'storage_code_parent_not_numbered': "Cet emplacement ne peut pas être numéroté seul : les emplacements au-dessus n'ont pas encore leurs codes du modèle, ou il est plus profond que le modèle ne va. Numérotez d'abord le niveau au-dessus",
    'storage_code_number_not_here': 'Seul un emplacement ordinaire peut être numéroté, pas un emplacement archivé ou virtuel',
    'storage_code_template_not_warehouse': "Un modèle de code appartient à un entrepôt, un emplacement en haut de l'arbre",
    'print_job_not_claimed': "Cette tâche d'impression n'est pas imprimée par cette imprimante",
    'print_job_not_retryable': "Seule une tâche d'impression en échec peut être renvoyée",
    'print_job_one_target': "Envoyez un seul type d'étiquettes : étiquettes du stock par identifiant, par code, ou emplacements.",
    'webhook_admin_only': 'Seuls les administrateurs peuvent gérer les webhooks',
    'approvals_manage_admin_only': "Seuls les administrateurs et gestionnaires peuvent modifier les flux d'approbation",
    'approvals_action_admin_only': "Vous n'avez pas l'autorisation d'approuver ou de rejeter des demandes",
    'approvals_read_forbidden': "Vous n'avez pas l'autorisation de consulter les demandes d'approbation",
    'approvals_write_forbidden': "Vous n'avez pas l'autorisation de soumettre des demandes d'approbation",
    'documents_approve_requires_grant': "Vous n'avez pas l'autorisation d'approuver ou de rejeter des documents",
    'po_approval_workflow_missing': 'Cette commande doit être approuvée, mais personne n’est encore désigné pour le faire. Demandez à votre administrateur de le configurer.',
    'po_supplier_required': 'Un bon de commande ne peut pas être confirmé sans fournisseur',
    'document_type_requires_partner': 'Ce type de document nécessite un partenaire.',
    'partner_has_no_email': "Le partenaire n'a pas d'adresse e-mail.",
    'po_has_no_partner': "Ce bon de commande n'a pas de fournisseur à qui l'envoyer.",
    'approval_no_active_workflow': "Aucun flux d'approbation actif n'est configuré pour cette action.",
    'po_no_pending_approval_request': "Aucune demande d'approbation en attente pour ce bon de commande.",
    'po_request_approval_invalid_status': 'Ce bon de commande ne peut plus être soumis à approbation.',
    'po_approve_invalid_status': "Seul un bon de commande en attente d'approbation peut être approuvé.",
    'approval_cannot_approve_own_request': 'Vous ne pouvez pas approuver votre propre demande.',
    'approval_cannot_reject_own_request': 'Vous ne pouvez pas rejeter votre propre demande.',
    'approval_approve_invalid_status': 'Seule une demande en attente de décision peut être approuvée.',
    'approval_reject_invalid_status': 'Seule une demande en attente de décision peut être rejetée.',
    'approval_cancel_invalid_status': 'Seule une demande ouverte peut être retirée.',
    'approval_decision_already_taken': "Quelqu'un d'autre a déjà statué sur cette demande.",
    'approval_not_stage_approver': "Vous n'êtes pas approbateur pour cette étape.",
    'approval_only_requester_can_cancel': "Seule la personne à l'origine de la demande peut la retirer.",
    'approval_workflow_inactive': "Le flux d'approbation de cette demande n'est plus actif.",
    'approval_request_already_open': "Une demande d'approbation est déjà ouverte pour cet enregistrement.",
    'approval_workflow_no_stages': "Ce flux d'approbation n'a aucune étape configurée.",
    'approval_workflow_needs_stage': "Un flux d'approbation doit comporter au moins une étape.",
    'approval_workflow_modify_blocked': "Ce flux ne peut pas être modifié tant que des demandes l'attendent ({count} : {documents}). La personne qui a fait une demande peut la retirer, et un approbateur peut la trancher — réglez-les d'abord.",
    'approval_workflow_delete_blocked': "Ce flux ne peut pas être supprimé tant que des demandes l'attendent ({count} : {documents}). La personne qui a fait une demande peut la retirer, et un approbateur peut la trancher — réglez-les d'abord.",
    'approval_workflow_archived': "Ce flux a été supprimé et il est archivé : ses demandes affichent toujours les étapes qu'elles ont suivies, il ne peut donc être ni modifié ni réactivé. Créez un nouveau flux à sa place.",
    'approval_unknown_approvers': "Certains des approbateurs sélectionnés n'appartiennent pas à cette organisation.",
    'approval_unknown_requesters': "Certaines des personnes ou certains des rôles sélectionnés n'appartiennent pas à cette organisation.",
    'approval_requester_scope_everyone_with_names': "Un flux qui s'applique à tout le monde ne nomme ni personne ni rôle.",
    'approval_requester_scope_names_nobody': 'Choisissez au moins une personne ou un rôle, ou tout le monde.',
    'approval_stage_unsolvable': "L'étape « {label} » ne pourra jamais être tranchée : aucun des approbateurs nommés n'a accès aux approbations. Ajoutez au moins une personne ayant accès.",
    'approval_scope_changed': "Ce que ce circuit retiendrait a changé depuis l'ouverture — relisez-le et activez le circuit si c'est toujours ce que vous voulez.",
    'approval_scope_required': 'Pour activer un circuit, envoyez la portée que vous avez vue — le champ « expected_scope » —, sinon le circuit reste désactivé.',
    'approval_stage_open_unsolvable': "L'étape « {label} » attend une personne disposant du droit d'approuver, et personne dans cette organisation ne l'a : aucune demande ne serait jamais tranchée. Accordez-le à quelqu'un ou nommez un approbateur.",
    'approval_required_first': "Cette action nécessite d'abord une approbation. Faites-en la demande avant de continuer.",
    'approval_workflow_required_but_missing': "Cela nécessite une approbation, mais aucun circuit d'approbation actif n'existe pour elle. Créez-en un ou levez l'exigence.",
    'approval_required_after_rejection': "La demande d'approbation de cette action a été rejetée. Faites-en une nouvelle avant de continuer.",
    'approval_granted_for_another_holder': "L'approbation a été accordée pour un emprunt par {holder}. Demandez-en une pour cet emprunt.",
    'document_no_pending_approval_request': "Aucune demande d'approbation en attente pour ce document.",
    'document_request_approval_invalid_status': 'Seul un document confirmé peut être soumis à approbation.',
    'po_confirm_invalid_status': 'Ce bon de commande ne peut pas être confirmé dans son état actuel.',
    'po_email_invalid_status': "Impossible d'envoyer un e-mail pour un bon de commande au statut {status}. Seuls CONFIRMED ou COMPLETED sont autorisés.",
    'po_email_invalid_address': 'Adresse e-mail du partenaire invalide : {email}',
    'po_partner_inactive': 'Impossible de confirmer le bon de commande : le partenaire "{name}" est inactif',
    'po_partner_not_supplier': 'Impossible de confirmer le bon de commande : le partenaire "{name}" a le type "{partner_type}", qui n\'est pas un type fournisseur',
    'po_approval_race_condition': "Impossible de créer la demande d'approbation — elle a peut-être été traitée par une autre action. Réessayez.",
    'po_already_cancelled': 'Ce bon de commande est déjà annulé',
    'po_cancel_completed': "Impossible d'annuler un bon de commande terminé",
    'po_cancel_received_quantities': "Impossible d'annuler ce bon de commande car des quantités ont déjà été reçues — annulez d'abord les réceptions liées",
    'po_cancel_open_receipts': "Impossible d'annuler ce bon de commande tant que des réceptions sont ouvertes — terminez-les ou annulez-les d'abord : {numbers}",
    'po_receipt_requires_confirmed': 'Seul un bon de commande confirmé peut créer une réception',
    'po_line_not_found': 'Ligne de bon de commande {po_line_id} introuvable',
    'po_receive_quantity_exceeds': 'La quantité {quantity} dépasse le reste {remaining} pour la ligne {line}',
    'po_line_product_template_not_found': 'Fiche produit {template_id} introuvable',
    'po_update_not_draft': 'Seuls les bons de commande au statut brouillon peuvent être mis à jour',
    'po_lines_received': (
        'Impossible de modifier les lignes : des articles ont déjà été reçus. '
        'Annulez d’abord les bons de réception concernés.'
    ),
    'po_import_not_draft': 'Les lignes ne peuvent être importées que dans un bon de commande au statut brouillon',
    'document_insufficient_stock': "Stock insuffisant pour confirmer : {quantity} sur {needed} n'ont pas pu être réservés",
    'document_zone_split_needs_stock_unit': "La ligne de « {item_name} » est saisie dans une unité autre que l'unité de stock du produit et ne peut pas être répartie sur plusieurs emplacements ; saisissez-la dans l'unité de stock ou prélevez-la sur un seul emplacement",
    'document_record_stands_elsewhere': "L'enregistrement « {item_name} » est sur « {record_shelf} », mais le document prend sur « {document_shelf} » — visez « {record_shelf} » ou déplacez d'abord l'enregistrement",
    'document_insufficient_stock_record_elsewhere': "Stock insuffisant pour confirmer : {quantity} sur {needed} n'ont pas pu être réservés sur « {document_shelf} » ; l'enregistrement « {item_name} » est sur « {record_shelf} » — visez cet emplacement ou déplacez d'abord l'enregistrement",
    'stock_would_go_negative': "Cela ferait passer le stock sous zéro. Quelqu'un a déplacé ces marchandises entre-temps — rechargez et réessayez.",
    'stock_reserved_over_quantity': "Cela réserverait plus de marchandises qu'il n'y en a en rayon. Libérez une réservation ou recomptez.",
    'document_exceeds_order_line': 'Réceptionner {quantity} dépasse la ligne de commande, sur laquelle il ne reste que {remaining} — au-delà de la tolérance de sur-réception de {tolerance} %, il faut une personne autorisée à recevoir au-delà de la tolérance',
    'over_receipt_needs_permission': 'Recevoir {quantity} dépasse la tolérance de sur-réception de {tolerance} % — il faut une personne autorisée à recevoir au-delà de la tolérance',
    'over_receipt_confirm_surplus': "{product} : recevoir {quantity}, c'est {surplus} de plus que les {basis} attendus. Recevoir l'excédent ?",
    'over_receipt_confirm_order_surplus': "{product} : recevoir {quantity}, c'est {surplus} de plus que les {basis} restant sur la commande {order}, ligne {line}. Recevoir l'excédent ?",
    'over_receipt_past_ceiling': 'Recevoir {quantity} pour {basis} dépasse le plafond de sur-réception de {ceiling} % — personne ne peut recevoir autant',
    'document_update_status': 'Seuls les documents au statut brouillon peuvent être mis à jour',
    'document_correction_locked': 'Les documents de correction sont verrouillés — seules les notes peuvent être modifiées. Tentative de modification : {fields}. Annulez la correction et créez-en une nouvelle si les données sont erronées.',
    'field_cannot_be_cleared': 'Ces champs ne peuvent pas être vidés : {fields}.',
    'ingredient_defaults_unreadable_file': "Impossible de lire le fichier. L'import attend un fichier .json ou .csv avec une ligne par ingrédient.",
    'onboarding_modules_not_offered': 'Le profil « {profile} » ne propose pas ces modules : {modules}',
    'location_chain_step_incomplete': "Chaque étape d'une chaîne d'emplacements doit avoir un identifiant ou un nom.",
    'current_password_incorrect': 'Le mot de passe actuel est incorrect',
    'storage_own_parent': 'Un emplacement ne peut pas être son propre parent.',
    'storage_short_code_in_use': 'Le code court « {short_code} » est déjà utilisé par un autre emplacement.',
    'storage_would_cycle': "Déplacer cet emplacement sous l'un de ses propres sous-emplacements créerait un cycle dans la hiérarchie des emplacements.",
    'template_not_builtin_copy': "Ce modèle n'a pas été copié d'une mise en page intégrée",
    'smtp_config_invalid': 'Les paramètres du serveur de messagerie ne sont pas valides : {reason}',
    'module_needs_newer_platform': 'Le module « {module} » nécessite Inventari {required} ou plus récent ; la version actuelle est {current}.',
    'document_delete_status': 'Seuls les documents brouillon peuvent être supprimés',
    'document_wms_picking_active': "Impossible de terminer ou d'annuler ce document tant que {sessions} session(s) de préparation WMS sont en cours. Terminez-les ou annulez-les d'abord.",
    'document_wms_receiving_active': "Impossible de terminer ou d'annuler ce document tant que {sessions} session(s) de réception WMS sont en cours. Terminez-les ou annulez-les d'abord.",
    'document_confirm_invalid_status': 'Impossible de confirmer un document au statut {status}',
    'document_lines_need_stock_row': 'Un document de type {type} sort de la marchandise d’un emplacement : chaque ligne doit donc nommer le stock d’où elle sort — les lignes {lines} ne nomment qu’un produit',
    'document_lines_need_stock_row_one': 'Un document de type {type} sort de la marchandise d’un emplacement : chaque ligne doit donc nommer le stock d’où elle sort — la ligne {lines} ne nomme qu’un produit',
    'document_receipt_lines_need_product': 'Les lignes {lines} ne nomment aucun produit de votre liste, et une réception ne met en stock que des produits — choisissez chacune dans la liste ou ajoutez-la comme nouveau produit',
    'document_receipt_lines_need_product_one': 'La ligne {lines} ne nomme aucun produit de votre liste, et une réception ne met en stock que des produits — choisissez-le dans la liste ou ajoutez-le comme nouveau produit',
    'document_partner_tax_id_required': "Le partenaire \"{name}\" n'a pas d'identifiant fiscal, mais les documents de cette organisation l'exigent pour la confirmation. Ajoutez l'identifiant fiscal au partenaire, indiquez qu'il s'agit d'un particulier (consommateur) ou désactivez « Exiger l'ID fiscal du partenaire » dans les Paramètres des documents.",
    'document_complete_invalid_status': 'Impossible de terminer un document au statut {status}',
    'document_complete_unanswered_lines': 'Terminer sans réponse pour chaque ligne enregistrerait les lignes sans réponse comme livrées en totalité. Lignes sans réponse : {lines}. Envoyez leurs quantités ou indiquez complete_as_planned=true pour les enregistrer comme prévu',
    'document_complete_skipped_lines': "Terminer enregistrerait les lignes ignorées comme prélevées ou réceptionnées en totalité, sans que personne n'ait dit ce qu'elles deviennent. Lignes ignorées : {lines}. Remettez chacune dans la liste, ou répondez qu'elle est incomplète avec un motif, avant de terminer — complete_as_planned ne les couvre pas",
    'document_receipt_lines_need_expiry': 'Un produit sorti selon la péremption la plus proche ne peut pas être réceptionné sans date de péremption : il serait classé après chaque stock daté. Lignes : {lines}. Envoyez le lot et la date avec la validation, ou saisissez la date sur la ligne',
    'picking_lot_no_longer_available': 'Impossible de clôturer le prélèvement : le lot {lot} ne peut plus fournir les {quantity} unités prélevées',
    'document_active_approval_request': "Une demande d'approbation active existe pour ce document",
    'document_cancel_invalid_status': "Seuls les documents brouillon, en attente d'approbation ou confirmés peuvent être annulés",
    'document_fields_closed': "Les champs d'un document terminé ou annulé ne peuvent plus être modifiés",
    'approval_workflow_not_found': "Workflow d'approbation introuvable",
    'po_pdf_invalid_status': 'Le PDF ne peut être généré que pour les bons de commande confirmés ou terminés. Statut actuel : {status}',
    'po_pdf_generation_failed': 'Échec de la génération du PDF',
    'email_delivery_failed': "Impossible d'envoyer l'e-mail — le serveur SMTP n'est peut-être pas configuré",
    'invalid_partner_type': "Ce type de partenaire n'est pas reconnu.",
    'invalid_country_code': 'Le pays doit être un code ISO 3166-1 alpha-2 à deux lettres (ex. PL).',
    'invalid_print_page_size': 'Le format de papier doit être A4 ou Letter.',
    'invalid_timezone': 'Le fuseau horaire doit être un nom de zone IANA valide (ex. Europe/Warsaw).',
    'invalid_currency_code': 'La devise doit être un code ISO 4217 valide (ex. PLN).',
    'admin_permissions_required': "Cette action nécessite des droits d'administrateur",
    'invalid_url_missing_host': 'URL invalide : hôte manquant',
    'url_must_be_public': "L'URL doit pointer vers un hôte public",
    'invalid_url_scheme': 'URL invalide : doit commencer par http:// ou https://',
    'rating_must_be_1_to_5': 'La note doit être comprise entre 1 et 5',
    'no_missing_ingredients': 'Aucun ingrédient manquant à ajouter',
    'picking_session_not_found': 'Session de prélèvement introuvable',
    'barcode_or_item_id_required': 'barcode ou item_id requis',
    'ingredient_not_found_or_not_picked': 'Ingrédient introuvable ou pas encore prélevé',
    'no_valid_images': 'Aucune image valide fournie',
    'file_must_be_image': 'Le fichier doit être une image',
    'vision_file_too_large': 'Le fichier est trop volumineux',
    'vision_unsupported_image_type': 'Le fichier « {filename} » n’a pas un type d’image accepté ({content_type}). Acceptés : {accepted}.',
    'llm_provider_unreachable': (
        "Impossible de joindre le fournisseur d'IA derrière la connexion "
        '"{name}" (modèle "{model}"). Vérifiez l\'adresse et la '
        'disponibilité du service dans Paramètres → Connexions IA.'
    ),
    'llm_provider_unreachable_generic': (
        "Impossible de joindre le fournisseur d'IA. Vérifiez l'adresse de "
        'la connexion et la disponibilité du service dans Paramètres → '
        'Connexions IA.'
    ),
    'llm_provider_timeout': (
        'La connexion "{name}" (modèle "{model}") n\'a pas répondu à temps. '
        'Le fournisseur a bien été joint : un modèle exécuté sur votre '
        'propre machine peut demander plus de temps '
        '(LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) ou une fenêtre de contexte plus '
        'petite.'
    ),
    'llm_provider_timeout_generic': (
        "Le fournisseur d'IA n'a pas répondu à temps. Il a bien été joint : "
        'un modèle exécuté sur votre propre machine peut demander plus de '
        'temps (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) ou une fenêtre de '
        'contexte plus petite.'
    ),
    'llm_provider_key_rejected': (
        'Le fournisseur d’IA derrière la connexion "{name}" (modèle '
        '"{model}") a rejeté la clé API. Vérifiez la clé dans Paramètres → '
        'Connexions IA.'
    ),
    'llm_provider_key_rejected_generic': (
        'Le fournisseur d’IA a rejeté la clé API. Vérifiez la clé dans '
        'Paramètres → Connexions IA.'
    ),
    'llm_provider_limit': (
        'La connexion "{name}" (modèle "{model}") a été refusée par le '
        'fournisseur d’IA : la limite du forfait ou le solde du compte est '
        'épuisé. Vérifiez le forfait ou réessayez plus tard.'
    ),
    'llm_provider_limit_generic': (
        'Le fournisseur d’IA a refusé : la limite du forfait ou le solde du '
        'compte est épuisé. Vérifiez le forfait ou réessayez plus tard.'
    ),
    'llm_provider_model_unknown': (
        'Le fournisseur d’IA derrière la connexion "{name}" ne connaît pas le '
        'modèle "{model}". Vérifiez le nom du modèle dans Paramètres → '
        'Connexions IA.'
    ),
    'llm_provider_model_unknown_generic': (
        'Le fournisseur d’IA ne connaît pas le modèle configuré. Vérifiez le '
        'nom du modèle dans Paramètres → Connexions IA.'
    ),
    'llm_purpose_unbound': (
        "Aucune connexion IA n'est encore choisie pour cette "
        'fonctionnalité. Choisissez-en une dans Paramètres → Connexions IA.'
    ),
    'llm_connection_test_failed': (
        "Le test de connexion n'a pas pu aboutir. Vérifiez l'adresse et réessayez."
    ),
    'llm_base_url_unresolved': (
        "Le nom d'hôte \"{host}\" de l'adresse de connexion IA n'a pas pu "
        "être résolu — vérifiez l'orthographe ; une faute de frappe se lit "
        "ici comme un fournisseur injoignable. Si l'adresse est bien "
        "orthographiée, demandez à l'exploitant de ce serveur si le nom est "
        'publié dans le DNS.'
    ),
    'llm_base_url_loopback': "L'adresse de connexion IA cible un nom d'hôte de bouclage ({host}). Uniquement des adresses externes — demandez à la personne qui gère cette installation d'autoriser un serveur de modèle local (paramètre LLM_ALLOW_PRIVATE_NETWORKS).",
    'llm_base_url_private': "L'adresse de connexion IA cible une adresse privée ou interne ({host}). Uniquement des adresses externes — demandez à la personne qui gère cette installation d'autoriser un serveur de modèle local (paramètre LLM_ALLOW_PRIVATE_NETWORKS).",
    'llm_base_url_scheme': ("L'adresse de connexion IA doit utiliser http ou https."),
    'llm_base_url_required_for_http_provider': (
        "Ce fournisseur est accessible via HTTP, l'URL de base est donc "
        'requise — par exemple https://openrouter.ai/api/v1'
    ),
    'llm_base_url_no_hostname': (
        "L'adresse de connexion IA doit inclure un nom d'hôte."
    ),
    'llm_base_url_refused': (
        "L'adresse de connexion IA a été refusée. Uniquement des adresses "
        'externes — définissez LLM_ALLOW_PRIVATE_NETWORKS=true sur les '
        'installations auto-hébergées pour autoriser un serveur de modèle '
        'local.'
    ),
    'vision_model_returned_nothing': (
        'La connexion "{name}" (modèle "{model}") n\'a renvoyé aucun '
        'contenu. Vérifiez que le modèle lit les images et que son budget '
        "de jetons suffit — la photo n'est pas en cause."
    ),
    'vision_model_returned_nothing_generic': (
        "Le modèle n'a renvoyé aucun contenu. Vérifiez dans Paramètres → "
        "Connexions IA qu'il lit bien les images."
    ),
    'vision_label_not_understood': (
        "L'IA n'a pas pu lire cette étiquette avec la connexion « {name} » "
        '(modèle « {model} »). Essayez une photo plus nette ou choisissez une '
        'autre connexion dans Paramètres → Connexions IA.'
    ),
    'vision_nutrition_not_understood': (
        "L'IA n'a pas pu lire ce tableau nutritionnel avec la connexion "
        '« {name} » (modèle « {model} »). Essayez une photo plus nette ou '
        'choisissez une autre connexion dans Paramètres → Connexions IA.'
    ),
    'vision_label_not_understood_generic': (
        "L'IA n'a pas pu lire cette étiquette. Essayez une photo plus nette ou un autre modèle dans Connexions IA."
    ),
    'vision_nutrition_not_understood_generic': (
        "L'IA n'a pas pu lire ce tableau nutritionnel. Essayez une photo plus nette ou un autre modèle dans Connexions IA."
    ),
    'vision_ai_not_configured': (
        "Aucune connexion IA n'est encore choisie pour la reconnaissance "
        "d'images. Choisissez-en une dans Paramètres → Connexions IA."
    ),
    'invalid_organization_id': "Identifiant d'organisation invalide",
    'user_has_no_organization': "L'utilisateur n'a pas d'organisation",
    'unsupported_import_format': "Format d'import non pris en charge : {format}",
    'unsupported_export_format': "Format d'export non pris en charge : {format}",
    'equipment_default_checkout_template': 'Protocole de sortie par défaut',
    'equipment_default_checkin_template': 'Protocole de retour par défaut',
    'purchase_order_standard_template': 'Commande fournisseur standard',
    'attestation_not_found': "Lien d'attestation introuvable",
    'attestation_expired': "Lien d'attestation expiré",
    'attestation_refused': "Ce lien d'attestation ne peut pas accepter cette action. Demandez un nouveau lien à l'organisation qui l'a envoyé.",
    'campaign_closed': 'Cette campagne d’attestation est clôturée — votre confirmation ne peut plus être enregistrée. Si vous détenez encore cet équipement, contactez votre organisation.',
    'assignment_already_returned': 'Cet équipement a déjà été confirmé comme retourné — aucune confirmation supplémentaire n’est nécessaire.',
    'equipment_still_assigned': (
        "L'équipement est encore attribué à une personne. "
        'Enregistrez son retour au préalable.'
    ),
    'equipment_deploy_requires_checkout': (
        "Un actif devient sorti lorsqu'il est remis à une personne. "
        'Sortez-le au lieu de modifier le statut.'
    ),
    'equipment_status_invalid': 'Statut invalide : {status}',
    'equipment_status_transition_denied': 'Impossible de changer le statut de {old} à {new}',
    'equipment_status_transition_from_retired': "Impossible de changer le statut de {old} à {new}. Les équipements retirés doivent d'abord être explicitement réactivés.",
    'attestation_assignment_required': 'Sélectionnez l’équipement concerné par le problème',
    'meta_data_spelled_twice': (
        "'meta_data' et 'metadata' nomment deux fois le même champ. "
        "N'envoyez que l'un des deux."
    ),
    'ai_connection_not_found': 'Connexion IA introuvable',
    'ai_connection_still_bound': "Cette connexion est associée à un objectif. Détachez-la d'abord.",
    'ai_connection_name_taken': 'Une connexion nommée « {name} » existe déjà dans cette organisation.',
    'ai_connection_target_required': 'Choisissez une connexion enregistrée ou un fournisseur à tester.',
    'ai_usage_limit_exceeded_requests': "L'organisation a utilisé {used} sur {limit} requêtes IA autorisées pour {period}. Contactez un administrateur pour augmenter la limite.",
    'ai_usage_limit_exceeded_scans': "L'organisation a utilisé {used} sur {limit} analyses d'étiquettes autorisées pour {period}. Contactez un administrateur pour augmenter la limite.",
    'invalid_reset_token': 'Jeton de réinitialisation invalide ou expiré',
    'modules_no_organization': 'Utilisateur non associé à une organisation',
    'modules_not_enabled': "Le module '{module_name}' n'est pas activé pour cette organisation",
    'invalid_template_module': 'Le module doit être "{module}"',
    'purge_blocked_by_audit_links': (
        "L'article est lié à des enregistrements d'audit et ne peut pas être "
        'supprimé définitivement.'
    ),
    'permanent_delete_disabled': (
        'La suppression définitive est désactivée pour cette organisation.'
    ),
    'documents_approval_workflow_missing': 'Ce document doit être approuvé, mais personne n’est encore désigné pour le faire. Demandez à votre administrateur de le configurer.',
    'category_delete_blocked_by_items': (
        'Impossible de supprimer la catégorie — elle est utilisée ({count}). Déplacez d’abord ses produits vers une autre catégorie.'
    ),
    'category_system_field_label_locked': (
        'Le nom du champ « {field} » appartient au catalogue de produits et ne peut pas être modifié.'
    ),
    'storage_delete_blocked_by_movements': (
        'Impossible de supprimer l’emplacement : {count} mouvements de stock y renvoient. L’historique des mouvements est immuable — archivez cet emplacement plutôt que de le supprimer.'
    ),
    'storage_delete_blocked_by_stock': (
        'Impossible de supprimer l’emplacement : le registre des stocks y détient encore du stock sans aucun enregistrement associé. Archivez cet emplacement ou rattachez d’abord ce stock à un enregistrement.'
    ),
    'storage_name_collision': (
        'Un emplacement nommé « {name} » existe déjà à ce niveau.'
    ),
    # Built-in pydantic validation errors (RequestValidationError) —
    # chosen by the error's `type`, filled from its `ctx`, by
    # app.i18n._validation.translate_validation_error.
    'validation_missing': 'Ce champ est obligatoire',
    'validation_string_too_long': 'Doit contenir au maximum {max_length} caractères',
    'validation_string_too_short': 'Doit contenir au minimum {min_length} caractères',
    'validation_string_too_long_one': 'Doit contenir au maximum {max_length} caractère',
    'validation_string_too_short_one': 'Doit contenir au minimum {min_length} caractère',
    'validation_pattern': 'Ne correspond pas au format attendu',
    'validation_greater_than_equal': 'Doit être supérieur ou égal à {ge}',
    'validation_greater_than': 'Doit être supérieur à {gt}',
    'validation_less_than_equal': 'Doit être inférieur ou égal à {le}',
    'validation_less_than': 'Doit être inférieur à {lt}',
    'validation_enum': "Doit être l'une des valeurs suivantes : {expected}",
    'validation_int': 'Doit être un nombre entier',
    'validation_number': 'Doit être un nombre',
    'validation_boolean': 'Doit être vrai ou faux',
    'validation_identifier': 'Doit être un identifiant valide',
    'validation_date': 'Doit être une date valide',
    'document_return_requires_completed': "Un retour ne peut être créé qu'à partir d'un document terminé",
    'document_return_type_not_eligible': 'Un retour ne peut être créé que pour une réception, une sortie ou un transfert',
    'document_return_no_lines': 'Un retour doit comporter au moins une ligne',
    'document_original_line_missing': "La ligne {line} n'existe pas dans le document {number}",
    'document_return_quantity_not_positive': 'La quantité retournée à la ligne {line} doit être supérieure à zéro',
    'document_return_quantity_exceeds_left': 'Un retour de {quantity} dépasse ce qui reste de la ligne {line} ({left} sur {done})',
    'document_correction_requires_completed': 'Seul un document terminé peut être corrigé',
    'document_correction_no_lines': 'Une correction doit comporter au moins une ligne',
    'document_correction_below_zero': 'Une correction de {delta} ferait passer la ligne {line} sous zéro — il reste {left} sur {done} à corriger',
    'document_correction_type_not_correctable': 'Les documents de ce type ne peuvent pas être corrigés',
    'document_undo_type_not_supported': 'Seul un bon de réception, de sortie ou de transfert peut être annulé',
    'document_undo_requires_completed': 'Seul un document validé peut être annulé',
    'document_undo_nothing_left': 'Tout ce que ce document a comptabilisé a déjà été annulé',
    'document_undo_blocked': "Impossible d'annuler : {reason} Utilisez « Corriger » pour modifier ce qui reste.",
    'document_undo_stock_used': "Impossible d'annuler : des mouvements ultérieurs ont consommé le stock comptabilisé. Utilisez « Corriger » pour modifier ce qui reste.",
    'document_post_already_posted': "Ce document a déjà été comptabilisé ; rien n'a été comptabilisé une seconde fois.",
    'document_post_cancelled': 'Ce document a été annulé ; il ne peut donc pas être comptabilisé.',
    'document_filter_unknown': 'Ce filtre n’est pas disponible : aucun module activé ne le propose ({name}).',
    'document_post_waiting_for_approval': 'Ce document attend déjà son approbation ; le stock bougera une fois celle-ci donnée.',
    'document_type_requires_target_location': 'Ce type de document nécessite un emplacement de destination',
    'document_type_requires_source_location': "Ce type de document nécessite un emplacement d'origine",
    'document_partner_must_be_supplier_or_manufacturer': "Le partenaire d'une réception doit être un fournisseur, un fabricant ou un client",
    'document_partner_must_be_customer_or_supplier': "Le partenaire d'une sortie doit être un client ou un fournisseur",
    'document_unit_price_required': 'Chaque ligne doit avoir un prix unitaire — il manque aux lignes {lines}',
    'document_preset_unknown': "Il n'existe pas de préréglage nommé {name}. Disponibles : {available}",
    'putaway_capacity_exists': 'Cet emplacement a déjà une capacité pour ce produit — modifiez plutôt l’entrée existante.',
    'putaway_capacity_not_found': 'Entrée de capacité introuvable',
    'no_fields_to_update': 'Aucun champ à mettre à jour',
    'putaway_rule_needs_location': 'Une règle de rangement doit indiquer au moins un emplacement.',
    'putaway_rule_needs_match_key': 'Une règle de rangement doit avoir au moins une condition — un produit, une catégorie, une étiquette de contexte ou un type d’emplacement.',
    'document_template_wrong_module': 'Un modèle de document appartient au module Documents',
    'search_query_empty': 'Saisissez un terme à rechercher',
    'document_type_invalid': "Le type de document {type} n'existe pas",
    'settings_payload_not_object': "Les réglages doivent être envoyés sous forme d'objet JSON",
    'settings_field_required': 'Le réglage « {field} » est obligatoire',
    'settings_field_unknown': 'Réglage inconnu « {field} »',
    'settings_value_not_string': 'Le réglage « {path} » doit être un texte',
    'settings_value_not_integer': 'Le réglage « {path} » doit être un nombre entier',
    'settings_value_not_number': 'Le réglage « {path} » doit être un nombre',
    'settings_value_not_boolean': 'Le réglage « {path} » doit être vrai ou faux',
    'settings_value_not_object': 'Le réglage « {path} » doit être un objet',
    'settings_value_not_array': 'Le réglage « {path} » doit être une liste',
    'settings_text_too_short': 'Le réglage « {path} » doit comporter au moins {limit} caractères',
    'settings_text_too_long': 'Le réglage « {path} » doit comporter au plus {limit} caractères',
    'settings_number_too_small': 'Le réglage « {path} » doit valoir au moins {limit} (reçu : {value})',
    'settings_number_too_large': 'Le réglage « {path} » doit valoir au plus {limit} (reçu : {value})',
    'settings_value_not_allowed': "Le réglage « {path} » doit être l'une de ces valeurs : {allowed} (reçu : {value})",
    'ai_purpose_unknown': "Finalité d'IA inconnue « {purpose} »",
    'attachment_file_type_invalid': 'Type de fichier invalide : {file_type}',
    'not_an_equipment_model': "Ce n'est pas un modèle d'équipement",
    'bom_line_parent_mismatch': 'Le produit parent de la ligne ne correspond pas au produit que fabrique cette formule',
    'bom_cycle_detected': 'Cycle détecté dans la formule à {template_id}',
    'margin_negative': 'La marge ne peut pas être négative',
    'margin_too_high': 'La marge doit être inférieure à 100 % pour que le prix reste fini',
    'label_size_invalid': "La hauteur et la largeur d'une étiquette doivent être supérieures à 0.",
    'recipe_collection_not_found': 'Collection introuvable',
    'recipe_collection_parent_not_found': 'Collection parente introuvable',
    'recipe_collection_own_parent': 'Une collection ne peut pas être sa propre parente',
    'recipe_collection_under_descendant': 'Une collection ne peut pas être déplacée sous sa propre sous-collection',
    'recipe_scrape_failed': "Impossible de récupérer la recette depuis l'URL",
    'register_date_from_after_date_to': 'La date de début ne peut pas être postérieure à la date de fin',
    'meal_plan_end_before_start': 'La date de fin ne peut pas précéder la date de début',
    'meal_plan_too_long': 'Un plan ne peut pas dépasser {days} jours',
    'meal_plan_no_slots': 'Activez au moins un repas dans le plan',
    'meal_plan_start_in_past': 'La date de début ne peut pas être dans le passé',
    'meal_plan_empty': "Impossible de générer une liste de courses à partir d'un plan vide",
    'picking_terminate_reason_invalid': 'Motif de fin invalide : {reason}',
    'recipe_import_name_required': "Les données d'import doivent contenir le nom de la recette",
    'recipe_import_data_required': "L'import JSON requiert des données",
    'recipe_import_unit_unknown': "L'ingrédient '{ingredient}' utilise l'unité '{unit}', que cette instance ne connaît pas",
    'recipe_import_unit_missing': "L'ingrédient '{ingredient}' a une quantité mais pas d'unité",
    'recipe_import_url_required': "L'import par URL requiert une URL",
    'recipe_scrape_fetch_failed': "Jina Reader n'a pas pu récupérer {url} : {error}",
    'recipe_scrape_encoding_unsupported': "Jina Reader a renvoyé un contenu compressé qui ne peut pas être lu en toute sécurité. Essayez une autre méthode d'import.",
    'recipe_scrape_empty': "Jina Reader n'a renvoyé aucun contenu pour {url}",
    'recipe_scrape_no_ingredients': "L'IA n'a trouvé aucun ingrédient — la page n'est peut-être pas une recette",
    'hex_color_invalid': 'Couleur hexadécimale invalide : {color}. Utilisez le format #RGB ou #RRGGBB',
    'shopping_list_nothing_to_convert': "Aucune ligne convertible (aucune n'a de modèle de produit)",
    'stock_take_bulk_item_id_required': "Le comptage groupé requiert de préciser l'article (item_id)",
    'cycle_count_scope_location_required': "Le périmètre du comptage cyclique doit préciser l'emplacement de stockage (storage_location_id)",
    'cycle_count_no_matching_items': 'Aucun article ne correspond aux critères de la planification',
    'stock_take_active_for_location': 'Un inventaire est déjà en cours pour cet emplacement de stockage',
    'category_name_taken': 'Une catégorie portant ce nom existe déjà',
    'invitation_code_invalid': "Code d'invitation invalide ou expiré",
    'invitation_other_address': 'Cette invitation a été émise pour une autre adresse e-mail',
    'role_not_found': 'Rôle introuvable',
    'role_other_organization': 'Le rôle appartient à une autre organisation',
    'user_not_in_organization': "L'utilisateur n'appartient pas à cette organisation",
    'template_other_organization': 'Le modèle appartient à une autre organisation',
    'template_in_use_by_items': 'Impossible de supprimer le modèle : il est utilisé par {count} article(s)',
    'barcode_already_exists': 'Le code-barres {barcode} existe déjà',
    'stock_insufficient_for_template': 'Stock insuffisant pour le modèle {template_id} : demandé {requested}, disponible {available}',
    'stock_lot_not_consumable': 'Le lot {lot} est {status} et ne peut être ni consommé ni réservé',
    'barcode_in_use': 'Code-barres déjà utilisé : {barcode}',
    'serial_number_exists': 'Ce numéro de série existe déjà : {serial_number}',
    'item_currency_mismatch': "La devise de l'article ({item_currency}) doit correspondre à celle de l'organisation ({organization_currency})",
    'organization_currency_missing': "La devise de l'organisation n'est pas configurée",
    'item_already_deleted': "L'article est déjà supprimé",
    'item_not_deleted': "L'article n'est pas supprimé",
    'item_restore_quantity_unknown': "Impossible de restaurer l'article : la quantité d'origine est inconnue car l'historique de suppression ne la contient pas",
    'item_purge_requires_archived': 'Seuls les articles archivés peuvent être purgés',
    'item_purge_reason_required': 'Un motif est requis pour la suppression définitive en production',
    'relocation_destination_foreign': "Impossible de déplacer l'article : la destination n'appartient pas à cette organisation.",
    'relocation_blocked_by_reservations': "Impossible de déplacer l'article : le stock source a des réservations en cours. Libérez-les ou honorez-les d'abord.",
    'short_code_invalid_format': 'Format de code invalide',
    'short_code_duplicate_in_request': 'Code court en double dans la requête : {short_code}',
    'short_codes_taken': "Ces codes courts sont déjà utilisés dans l'organisation : {codes}",
    'onboarding_profile_unknown': "Profil inconnu : '{profile}'",
    'storage_vanished_during_batch': "L'emplacement de stockage {location} a disparu pendant le lot.",
    'storage_archive_blocked_by_items': "Archivage impossible : {count} article(s) sont encore stockés ici. Déplacez-les d'abord ou archivez avec un emplacement cible.",
    'storage_archive_target_is_self': "Impossible de déplacer les articles vers l'emplacement en cours d'archivage.",
    'storage_archive_target_is_descendant': "Impossible de déplacer les articles vers un emplacement enfant de celui qu'on archive.",
    'storage_archive_target_archived': 'Impossible de déplacer les articles vers un emplacement archivé.',
    'storage_restore_parent_archived': "Impossible de restaurer dans un emplacement parent archivé. Restaurez d'abord le parent.",
    'storage_delete_blocked_by_references': "Impossible de supprimer l'emplacement : d'autres enregistrements y font encore référence (contrainte « {constraint} »). Archivez-le plutôt.",
    'storage_delete_concurrent_movements': "Impossible de supprimer l'emplacement : une transaction concurrente a créé des mouvements de stock qui y renvoient. Réessayez pour actualiser le compte. Erreur d'origine : {error}",
    'sole_administrator_cannot_leave': "Vous ne pouvez pas quitter l'organisation en étant le seul administrateur. Désignez d'abord un autre administrateur.",
    'sole_administrator_role_locked': "Impossible de modifier le rôle de l'unique administrateur. Promouvez d'abord un autre membre.",
    'organization_member_limit': "La limite de membres de l'organisation est atteinte. Passez à Inventari Cloud pour obtenir plus de places.",
    'registration_failed': "Impossible de finaliser l'inscription. Veuillez réessayer ou contacter l'assistance.",
    'superuser_required': 'Cette action nécessite les droits de superutilisateur',
    'onboarding_already_completed': "L'intégration est déjà terminée — utilisez /switch-profile",
    'module_dependency_cycle': 'Dépendance circulaire détectée impliquant le module « {module} »',
    'module_dependency_cycle_among': 'Dépendance circulaire détectée entre les modules : {modules}',
    'profile_switch_unknown_modules': 'Le profil fait référence à des modules non enregistrés : {unknown_modules}',
    'profile_switch_modules_not_allowed': 'Modules non autorisés pour cette organisation : {not_allowed_modules}',
    'profile_switch_dependency_unregistered': "Le module « {module} » nécessite « {missing_dependency} », qui n'est pas enregistré.",
    'focus_mode_module_always_on': 'Le module « {module} » est toujours actif et ne peut pas être le seul focus.',
    'focus_mode_module_unregistered': "Le module « {module} » n'est pas enregistré.",
    'focus_mode_module_not_enabled': "Le module « {module} » n'est pas activé pour cette organisation.",
    'focus_mode_already_active': "L'organisation est déjà centrée sur « {module} ».",
    'focus_mode_not_active': "L'organisation n'est pas en mode focus sur un seul module.",
}
