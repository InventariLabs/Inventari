from app.i18n._types import ErrorMessages

ERRORS_ES: ErrorMessages = {
    'invalid_credentials': 'Correo o contraseña inválidos',
    'invalid_input': 'Entrada no válida',
    'not_authenticated': 'No autenticado',
    'user_already_exists': 'Ya existe un usuario con este correo',
    'user_already_in_organization': 'El usuario ya pertenece a una organización',
    'token_expired': 'El token de autenticación ha expirado',
    'token_invalid': 'Token de autenticación inválido',
    'insufficient_permissions': 'No tiene permiso para realizar esta acción',
    'import_create_forbidden': 'Esta cuenta no tiene el permiso {permissions}, así que la importación no puede crear ubicaciones o categorías que falten en su nombre. Desactiva los interruptores correspondientes en el diálogo de importación o solicita el permiso',
    'import_stubs_forbidden': 'Esta cuenta no tiene el permiso {permissions}, así que la importación no puede crear productos temporales para códigos de barras sin coincidencia en su nombre. Desmarca la casilla "Crear productos sustitutos" en el diálogo de importación o solicita el permiso',
    'user_blocked': 'Su cuenta ha sido bloqueada. Motivo: {reason}',
    'user_blocked_no_reason': 'no indicado',
    'uom_not_found': 'Unidad de medida no encontrada',
    'import_job_not_found': 'Importación no encontrada',
    'user_not_found': 'Usuario no encontrado',
    'user_email_required': 'Esta cuenta no tiene dirección de correo, así que no tiene activos que mostrar.',
    'user_inactive': 'Su cuenta está pendiente de aprobación por un administrador.',
    'item_not_found': 'Artículo no encontrado',
    'item_quantity_above_ceiling': 'La cantidad {quantity} supera la capacidad de la columna — el valor más grande guardable es {ceiling}',
    'item_quantity_raise_in_virtual_location': 'Este producto está en {location}, donde el stock no se cuenta — devuélvelo primero a una estantería y luego añade la cantidad',
    'counted_quantity_above_ceiling': 'La cantidad contada {quantity} supera la capacidad de la columna — el valor más grande guardable es {ceiling}',
    'item_unit_change_blocked_by_stock': 'Este registro tiene {quantity} {current_unit}. Cambiar la unidad a {new_unit} solo reetiquetaría ese número sin cambiar lo que hay en la estantería. Consúmelo o dalo de baja primero, o crea un registro aparte en la nueva unidad.',
    'item_unit_differs_from_template_confirmation_required': '{product} se lleva en {template_unit}, y esta cantidad está dada en {chosen_unit}. Al guardar se convertirá a {template_unit}, así que confirma que {chosen_unit} es la unidad que querías, o introduce la cantidad en {template_unit}.',
    'item_unit_not_convertible_to_card': '{product} se lleva en {template_unit}, y una cantidad en {chosen_unit} no puede convertirse a esa unidad. Introduce la cantidad en {template_unit} — o, para piezas, indica en el producto cuánto pesa o contiene una pieza.',
    'bom_line_unit_not_convertible': 'Este ingrediente se lleva en {stock_unit}, y {line_unit} no puede '
    'leerse como {stock_unit}. Usa una unidad del mismo tipo, o indica en el '
    'producto cuánto pesa o contiene un {stock_unit}.',
    'bom_line_self_reference': (
        'Una línea de la fórmula no puede referenciar el producto en sí — '
        'el producto pasaría a ser ingrediente de su propia fórmula.'
    ),
    'bom_line_cycle': (
        'Esta línea cerraría un ciclo: el producto pasaría a ser ingrediente '
        'de su propia fórmula.'
    ),
    'uom_quantity_requires_whole_number': (
        'La unidad {unit} solo admite números enteros, así que {quantity} no '
        'se puede guardar. Redondea la cantidad a un número entero.'
    ),
    'uom_quantity_too_many_decimal_places': (
        'La unidad {unit} admite como máximo {places} decimales, así que '
        '{quantity} no se puede guardar. Redondea la cantidad a esa '
        'precisión.'
    ),
    'item_unit_cannot_be_removed': (
        'La unidad {unit} no se puede quitar: una cantidad sin unidad no '
        'dice nada. Elija otra unidad en su lugar.'
    ),
    'removal_strategy_of_shared_product': (
        'Este producto procede del catálogo compartido, así que el '
        'orden en que sale su stock es del catálogo y no se puede '
        'cambiar para una sola organización.'
    ),
    'piece_unit_missing_from_catalogue': (
        'El catálogo de unidades de esta instalación no tiene unidad de '
        'pieza, así que «una cantidad de qué» se queda sin respuesta. Indica '
        'la unidad explícitamente o restaura el catálogo de unidades '
        'estándar.'
    ),
    'unknown_bulk_action': 'Acción masiva desconocida: {action}',
    'equipment_bulk_item_failed': ('No se pudo modificar este activo.'),
    'stock_as_of_no_history': (
        'Esta organización no registra movimientos de stock, así que no '
        'tiene historial del que informar. La única respuesta '
        'disponible es el stock de hoy.'
    ),
    'stock_as_of_before_ledger': (
        'El libro de movimientos empieza el {starts_at}. No se sabe '
        'nada de antes — no cero —, un informe para el {as_of} sería '
        'una suposición.'
    ),
    'stock_as_of_pdf_too_many': (
        'El informe tiene {total} productos — más de las {limit} filas que '
        'caben en una impresión. Expórtalo como hoja de cálculo o elige una '
        'ubicación para acotarlo.'
    ),
    'item_create_failed': 'Error al crear el artículo',
    'item_update_failed': 'Error al actualizar el artículo',
    'item_delete_failed': 'Error al eliminar el artículo',
    'storage_not_found': 'Ubicación de almacenamiento no encontrada',
    'storage_create_failed': 'Error al crear la ubicación de almacenamiento',
    'storage_update_failed': 'Error al actualizar la ubicación de almacenamiento',
    'storage_delete_failed': 'Error al eliminar la ubicación de almacenamiento',
    'storage_delete_failed_items': 'No se puede eliminar una ubicación que contiene artículos. Muévalos o elimínelos primero.',
    'storage_delete_blocked_by_production_orders': 'No se puede eliminar la ubicación: la utilizan órdenes de producción.',
    'storage_type_not_found': 'Tipo de ubicación de almacenamiento no encontrado',
    'storage_type_create_failed': 'Error al crear el tipo de ubicación',
    'storage_type_update_failed': 'Error al actualizar el tipo de ubicación',
    'storage_type_delete_failed': 'Error al eliminar el tipo de ubicación',
    'storage_type_exists': 'Ya existe un tipo de ubicación con este código',
    'storage_type_no_access': 'No tiene acceso a este tipo de ubicación',
    'storage_type_in_use': 'El tipo de ubicación está siendo usado por {count} ubicaciones',
    'storage_usage_immutable': 'El propósito de una ubicación lo establece el sistema y no se puede cambiar.',
    'storage_type_system_modify': 'Los tipos de ubicación del sistema no se pueden modificar',
    'storage_type_system_delete': 'Los tipos de ubicación del sistema no se pueden eliminar',
    'category_not_found': 'Categoría no encontrada',
    'category_create_failed': 'Error al crear la categoría',
    'category_update_failed': 'Error al actualizar la categoría',
    'category_delete_failed': 'Error al eliminar la categoría',
    'storage_archived': 'Esta ubicación está archivada. Restáurala antes de guardar productos aquí.',
    'stock_take_not_found': 'Inventario no encontrado',
    'stock_take_already_completed': 'El inventario ya ha sido completado',
    'stock_take_not_in_progress': 'El inventario no está en curso',
    'stock_take_create_failed': 'Error al crear el inventario',
    'stock_take_update_failed': 'Error al actualizar el inventario',
    'shopping_list_not_found': 'Lista de compras no encontrada',
    'shopping_list_create_failed': 'Error al crear la lista de compras',
    'shopping_list_update_failed': 'Error al actualizar la lista de compras',
    'shopping_list_not_writable': 'Esta lista de la compra está {status} y no se puede modificar. Reactívala primero.',
    'shopping_list_delete_failed': 'Error al eliminar la lista de compras',
    'shopping_list_item_not_found': 'Artículo de la lista de compras no encontrado',
    'shopping_list_item_quantity_rounds_to_zero': 'La cantidad {quantity} se redondea a cero con la precisión del almacenamiento — el valor más pequeño guardable es {smallest}',
    'shopping_list_item_quantity_above_ceiling': 'La cantidad {quantity} supera la capacidad de la columna — el valor más grande guardable es {ceiling}',
    'shopping_list_item_uom_unknown': 'Unidad de medida desconocida (uom_id: {uom_id}) — la unidad no existe',
    'shopping_list_item_item_unknown': 'Producto desconocido (item_id: {item_id}) — el producto no existe',
    'shopping_list_item_category_unknown': 'Categoría desconocida (category_id: {category_id}) — la categoría no existe',
    'shopping_list_item_template_unknown': 'Plantilla de producto desconocida (template_id: {template_id}) — la plantilla no existe',
    'organization_not_found': 'Organización no encontrada',
    'organization_create_failed': 'Error al crear la organización',
    'organization_update_failed': 'Error al actualizar la organización',
    'organization_delete_failed': 'Error al eliminar la organización',
    'smtp_not_configured': 'Esta organización no tiene configurado el envío de correo',
    'demo_smtp_settings_locked': 'Esta es la demo pública, así que el servidor de correo es fijo: cada mensaje que enviaría la aplicación se captura en la bandeja de entrada de la demo. Los ajustes de correo no se pueden cambiar aquí.',
    'demo_credentials_locked': 'Esta es la demo pública, donde cada correo llega a una bandeja pública. Aquí no se pueden cambiar ni restablecer las contraseñas, y los visitantes no necesitan una cuenta.',
    'demo_registration_locked': 'Esta es la demo pública, donde los visitantes no necesitan una cuenta. «Solicitar acceso» no está disponible aquí: usa «Probar la demo».',
    'role_in_use': 'Este rol todavía está asignado a alguien. Cambia primero su rol y luego elimínalo.',
    'role_name_taken': 'Ya existe un rol llamado "{name}" en esta organización.',
    'invitation_not_found': 'Invitación no encontrada',
    'organization_invite_invalid': 'Invitación de organización inválida',
    'organization_invite_wrong_email': 'Esta invitación se emitió para otra dirección de correo. Usa la dirección a la que se envió.',
    'organization_invite_expired': 'La invitación de organización ha expirado',
    'email_test_failed': 'No se pudo enviar el correo de prueba',
    'module_org_required': 'Para gestionar módulos debes pertenecer a una organización. Inicia sesión de nuevo o contacta con soporte.',
    'module_premium_locked': 'El módulo «{module}» es una función de pago. Contacta con la administración del sistema para activarlo en tu organización.',
    'module_always_on': 'El módulo «{module}» está siempre activo y no se puede desactivar.',
    'module_requires_other': 'Primero hay que activar el módulo «{required}».',
    'module_blocks_dependent': 'El módulo «{dependent}» depende de «{module}» y está activo. Desactiva primero «{dependent}».',
    'webhook_url_loopback': 'Esta dirección apunta al propio servidor ({host}), así que la llamada nunca saldría de la máquina. Usa una dirección accesible desde internet o pide a quien administra esta instalación que permita direcciones locales (ajuste WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'webhook_url_private': 'Esta dirección ({host}) no admite enrutamiento público o está reservada para la infraestructura de protocolos, y el servidor rechaza esas llamadas. Usa una dirección accesible desde internet o pide a quien administra esta instalación que permita direcciones locales (ajuste WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'webhook_url_unresolved': 'El nombre «{host}» no se pudo resolver, así que la dirección no se puede comprobar. Usa un nombre resoluble públicamente o pide a quien administra esta instalación que permita direcciones locales (ajuste WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'webhook_url_rebinding': 'El nombre «{host}» resuelve a una dirección sin enrutamiento público o reservada para la infraestructura de protocolos ({resolved}). Usa una dirección accesible desde internet o pide a quien administra esta instalación que permita direcciones locales (ajuste WEBHOOKS_ALLOW_PRIVATE_NETWORKS).',
    'reg_request_new_title': 'Nueva solicitud de acceso',
    'reg_request_new_content': 'El usuario {name} está solicitando acceso al sistema.',
    'reg_request_approved_title': 'Solicitud aprobada',
    'reg_request_approved_content': 'El acceso para {email} ha sido aprobado por {admin}.',
    'reg_link_undelivered_title': 'Enlace de registro no entregado',
    'reg_link_undelivered_content': 'No se pudo entregar el correo con el enlace de registro a {email}. Pásele usted mismo este enlace: {link}',
    'reg_request_rejected_title': 'Solicitud rechazada',
    'reg_request_rejected_content': 'El acceso para {email} ha sido rechazado por {admin}.',
    'reconciliation_drift_title': 'Discrepancia de existencias detectada',
    'reconciliation_drift_content': (
        'La conciliación de existencias programada encontró cifras que no '
        'coinciden — {pairs}. Ver: Estadísticas → Conciliación.'
    ),
    'reconciliation_drift_standing_title': 'La discrepancia de existencias persiste',
    'reconciliation_drift_standing_content': (
        'La discrepancia notificada antes no ha cambiado y persiste — '
        '{pairs}. Ver: Estadísticas → Conciliación.'
    ),
    'reconciliation_pair_quant_ledger': 'estante vs libro de movimientos: {count}',
    'reconciliation_pair_layer_quant': 'historial de coste vs estante: {count}',
    'event_delivery_dead_title': 'Una tarea en segundo plano sigue fallando',
    'event_delivery_dead_content': (
        'El controlador {handler} del evento {event} falló {attempts} veces y se detuvo. Último error: {error}. El evento se conserva en event_deliveries para su revisión.'
    ),
    'field_required': 'Este campo es obligatorio',
    'invalid_email': 'Formato de correo electrónico inválido',
    'password_too_short': 'La contraseña debe tener al menos 8 caracteres',
    'password_invalid': 'La contraseña debe contener al menos una mayúscula, una minúscula y un número',
    'password_too_long': 'La contraseña puede tener como máximo {max_bytes} bytes',
    'password_needs_lowercase': 'La contraseña debe contener al menos una letra minúscula',
    'password_needs_uppercase': 'La contraseña debe contener al menos una letra mayúscula',
    'password_needs_digit': 'La contraseña debe contener al menos un dígito',
    'sku_format_invalid': 'El SKU solo puede contener letras, dígitos, guiones, guiones bajos y barras',
    'sku_in_use': 'El SKU {sku} ya pertenece a otro producto',
    'custom_field_required': 'El campo «{field}» es obligatorio',
    'field_multi_select_shape': 'El campo «{field}» debe ser una lista de opciones',
    'field_option_not_allowed': 'El valor «{value}» no es una de las opciones del campo «{field}»: {options}',
    'field_money_shape': 'El campo «{field}» debe contener un importe y una moneda, y nada más',
    'field_money_amount': 'El importe del campo «{field}» debe ser un número',
    'field_money_currency': 'La moneda del campo «{field}» debe ser un código ISO 4217 de 3 letras, por ejemplo EUR',
    'field_select_shape': 'El campo «{field}» debe tener una sola opción',
    'item_limit_reached': 'Esta organización ha alcanzado el límite de artículos. Pásese a Inventari Cloud.',
    'item_archived': 'El artículo está archivado y se puede restaurar desde el archivo',
    'announcement_type_invalid': 'Tipo de anuncio no válido. Permitidos: {allowed}',
    'ai_provider_invalid': 'Proveedor no válido. Permitidos: {allowed}',
    'field_options_required': 'Un campo de tipo {type} necesita una lista de opciones no vacía',
    'member_role_exactly_one': 'Indique exactamente uno de role o role_id',
    'reason_blank': 'El motivo no puede estar vacío',
    'discrepancy_reason_required': 'Se requiere un motivo de la discrepancia',
    'invalid_uuid': 'Formato UUID inválido',
    'sheet_unreadable': 'No se pudo leer este archivo como hoja de cálculo. Compruebe que sea un archivo .xlsx o .csv válido e inténtelo de nuevo.',
    'pasted_text_unreadable': 'No se pudo leer el texto pegado como tabla. Pegue filas copiadas de una hoja de cálculo, con el mismo número de columnas en cada una.',
    'webhook_url_malformed': 'Esta no es una dirección web válida. Introduzca una dirección completa, por ejemplo https://example.com/hook.',
    'recipe_extraction_failed': 'No se pudo extraer la receta de esta página. Inténtelo de nuevo o introduzca la receta a mano.',
    'invalid_date': 'Formato de fecha inválido',
    'value_must_be_positive': 'El valor debe ser positivo',
    'value_must_be_greater_than_zero': 'El valor debe ser mayor que cero',
    'insufficient_quantity': 'Stock insuficiente para realizar esta acción',
    'file_type_not_allowed': 'Tipo de archivo no permitido',
    'file_signature_mismatch': 'La firma del archivo no coincide con el tipo declarado',
    'file_too_large': 'El archivo excede el tamaño máximo permitido (10 MB)',
    'file_type_not_allowed_list': 'Tipo de archivo no permitido. Permitidos: {allowed}',
    'file_content_type_missing': 'El archivo no indica su tipo (falta la cabecera Content-Type).',
    'file_empty': 'El archivo está vacío.',
    'file_not_webp': 'Este archivo no es una imagen WebP válida.',
    'import_too_many_rows': 'El archivo tiene {count} filas; el límite es {limit}. Divídalo en archivos más pequeños.',
    'storage_location_ambiguous': '«{text}» coincide con {count} ubicaciones de almacenamiento ({shown}). Indique la ruta completa, por ejemplo «{example}».',
    'pagination_cursor_invalid': 'Cursor de paginación no válido o caducado',
    'webhook_url_scheme': 'Para los webhooks solo se permiten direcciones {schemes}.',
    'webhook_url_no_hostname': 'La dirección del webhook debe incluir un nombre de host, por ejemplo https://example.com/hook.',
    'picking_already_picked': '{name} ya ha sido recogido',
    'picking_unit_mismatch': (
        'No se pueden comparar las unidades de {name}: la receta y las '
        'existencias usan medidas distintas. Registre cuánto pesa o contiene '
        'una unidad de existencias y vuelva a escanear.'
    ),
    'picking_picked': '{name} ✓ — se descuentan {quantity}',
    'invalid_mapping_json': 'JSON de mapeo inválido',
    'extra_cost_not_a_receipt': 'Los costes adicionales pertenecen a una entrada: solo la mercancía que llega puede llevar el coste de traerla.',
    'extra_cost_document_posted': (
        'Esta entrada ya está contabilizada, así que no se le puede añadir un coste: la mercancía puede haber salido y no queda nada a lo que cargarlo. Emita una corrección de la entrada con el periodo abierto.'
    ),
    'extra_cost_currency_mismatch': (
        'El coste adicional está en una moneda distinta a la del documento. Introdúzcalo en la moneda del documento: convertir a un tipo que nadie registró pondría en el valor del stock un número sin historial.'
    ),
    'document_shipment_dispatch_only': 'Solo una expedición registra un envío: el transportista se lleva mercancía que sale del almacén.',
    'document_tracking_template_invalid': 'El enlace de seguimiento de «{carrier}» debe ser una dirección web que empiece por https:// o http:// y contenga {{tracking_number}} donde va el número.',
    'packing_not_a_dispatch': 'Solo se embala una expedición: los bultos contienen mercancía que sale del almacén.',
    'packing_document_not_open': 'Los bultos solo se pueden cambiar mientras la expedición está confirmada y aún no completada. Una expedición completada conserva sus bultos tal como se enviaron.',
    'packing_exceeds_picked': '{name}: solo {remaining} preparado(s) y aún sin embalar. Un bulto contiene lo que se preparó, y nada de lo que ya está en otro bulto.',
    'packing_exceeds_done': '{name}: los bultos contienen {packed}, más de los {done} que envía esta expedición. Saque primero la diferencia de los bultos, o complete con la cantidad que contienen.',
    'packing_nothing_to_pack': 'Todo lo preparado ya está embalado, así que no queda nada para un bulto nuevo.',
    'packing_no_packages': 'Esta expedición aún no tiene bultos, así que no hay lista de embalaje que imprimir. Embálela primero.',
    'package_not_found': 'Bulto no encontrado',
    'packing_scan_unrecognized': 'Ningún producto lleva el código {code}. Escanee el código de barras del propio producto o toque su línea para embalarlo.',
    'packing_scan_not_in_document': '{name} no está en esta salida, así que no va en sus paquetes.',
    'invalid_image_extension': 'Extensión de imagen inválida',
    'invalid_role': 'Rol inválido. Permitidos: {roles}',
    'role_not_in_organization': 'El rol no pertenece a esta organización',
    'failed_to_read_file': 'Error al leer el archivo: {error}',
    'only_image_files_allowed': 'Solo se permiten archivos de imagen (jpg, png, gif, webp)',
    'image_unreadable': 'No se pudo leer este archivo como imagen',
    'image_too_large': 'Imagen demasiado grande (máx. {limit})',
    'demo_upload_file_limit': 'La demo acepta archivos de hasta {limit}',
    'demo_upload_total_limit': 'La demo alcanzó su límite de archivos subidos ({limit}). Se podrá subir de nuevo tras el próximo reinicio',
    'demo_sandbox_cap_reached': 'La demo ya ha repartido todas sus copias de hoy. Vuelva mañana',
    'demo_sandbox_pool_empty': 'Todas las copias de la demo están ocupadas ahora mismo y se están preparando nuevas. Inténtelo dentro de un minuto',
    'barcode_or_sku_required': 'Se requiere el parámetro barcode o sku',
    'barcode_names_one_record': 'Un código de barras no puede nombrar {count} registros: {barcode}',
    'storage_no_short_code': 'La ubicación no tiene código corto. Genere uno primero.',
    'refresh_token_expired_grace': 'Token de actualización expirado más allá del período de gracia',
    'refresh_token_revoked': 'Token de actualización revocado',
    'cannot_remove_yourself': 'No puede eliminarse a sí mismo',
    'cannot_change_own_role': 'No puedes cambiar tu propio rol',
    'label_in_use_by_product': 'No se puede eliminar una etiqueta asignada a un producto activo. Elimine primero el producto.',
    'label_already_assigned': 'Etiqueta ya asignada',
    'no_labels_available': 'No hay etiquetas disponibles para imprimir',
    'unauthorized': 'Autenticación requerida',
    'forbidden': 'Acceso denegado',
    'organization_required': 'Organización requerida',
    'not_found': 'Recurso no encontrado',
    'conflict': 'Conflicto de recursos',
    'internal_error': 'Ocurrió un error interno',
    'rate_limit_exceeded': 'Demasiadas solicitudes. Inténtalo de nuevo más tarde.',
    'service_unavailable': 'Servicio temporalmente no disponible',
    'stock_take_edit_completed': 'No se puede editar un inventario completado o cancelado',
    'stock_take_delete_completed': 'Solo se pueden eliminar borradores o inventarios activos',
    'stock_take_not_active': 'El inventario no está activo',
    'stock_take_surplus_item_id_required': 'Elige el producto al que corresponde este artículo sobrante.',
    'stock_take_surplus_quantity_required': 'Introduce la cantidad contada de este artículo sobrante.',
    'stock_lot_not_found': 'Lote de existencias no encontrado',
    'stock_moves_export_too_many': 'Coinciden {total} movimientos — más de los {limit} que caben en una hoja. Acota las fechas, el lugar o el producto y vuelve a exportar.',
    'stock_take_close_requires_finalize': 'Un inventario se cierra al finalizarlo (POST /stock-takes/{id}/complete), no con un cambio de estado',
    'period_already_closed': 'El período {period} ya está cerrado.',
    'period_closed_for_date': 'El período {period} está cerrado, así que no se puede fechar nada en él. Cambie la fecha del documento o pida a alguien autorizado que reabra el período.',
    'period_closed_for_stock_change': 'El período {period} está cerrado, así que no se puede registrar ningún movimiento de stock en él. Pida a alguien autorizado que reabra el período.',
    'transfer_more_than_the_record_holds': 'El registro «{item_name}» contiene {available} y la línea traslada {requested}. Reduzca la cantidad de la línea o traslade el resto desde otro registro.',
    'transfer_cannot_split_serialized_record': 'La transferencia no puede dividir el registro serializado {serial_number}; transfiere el registro completo.',
    'use_partially_more_than_left': 'El registro «{item_name}» contiene {available} de este envase y se indicó que quedan {requested}. Indique cuánto queda; no puede ser más de lo que hay.',
    'use_partially_serialized': 'El registro con número de serie {serial_number} no se puede abrir ni dividir; úselo completo.',
    'use_partially_needs_counted_unit': '«{item_name}» se lleva en una unidad de medida, así que no hay un envase que abrir. Reste del stock lo que use.',
    'use_partially_pack_has_no_measure': '«{item_name}» se cuenta en envases y el producto no indica cuánto contiene uno, así que solo se puede registrar «abierto» o «terminado».',
    'use_by_needs_open_package': 'El registro «{item_name}» está cerrado, así que no tiene fecha de consumo. Ábralo primero; hasta entonces vale la fecha del lote.',
    'period_not_closed': 'El período {period} no está cerrado.',
    'wms_session_now_held_by': 'Esta sesión ahora está a cargo de {owner}; desde aquí ya no se aceptan escaneos.',
    'wms_session_held_by_other_user': 'Otro usuario tiene una sesión activa en este documento (abierta por {owner}).',
    'wms_pick_document_not_found': 'No se encontró el documento {document} en esta organización, así que la sesión de preparación no se inició.',
    'wms_pick_document_not_confirmed': 'El documento {number} no está confirmado, así que la sesión de preparación no se inició. Solo se pueden preparar documentos confirmados.',
    'wms_pick_document_not_dispatch': 'El documento {number} no es una salida, así que la sesión de preparación no se inició. Solo las salidas se pueden preparar juntas.',
    'wms_pick_document_in_session': 'El documento {number} ya se está preparando en otra sesión (abierta por {owner}), así que la sesión de preparación no se inició.',
    'wms_line_document_closed': 'El documento {number} está {status}, así que sus líneas en esta sesión ya no se pueden cambiar.',
    'wms_short_below_scanned': 'La cantidad final no puede ser inferior a la cantidad escaneada ({scanned}); para registrar menos, debe sustituir los escaneos.',
    'wms_short_pick_needs_outcome': 'Una línea recogida de menos necesita un motivo: «Faltante» deja el resto pendiente en un pedido pendiente, otro motivo cierra la diferencia.',
    'wms_session_not_found': 'No se encontró la sesión activa. Puede que ya se haya completado o cancelado.',
    'wms_line_not_found': 'No se encontró la línea de la sesión.',
    'wms_line_not_pending': 'No se encontró la línea de la sesión o ya no está pendiente.',
    'wms_quantity_cannot_be_negative': 'La cantidad no puede ser negativa.',
    'wms_quantity_above_expected': 'La cantidad no puede superar la cantidad esperada.',
    'wms_cannot_complete_no_lines': 'No se puede completar la sesión: no tiene líneas.',
    'wms_cannot_complete_lines_pending': 'No se puede completar la sesión: {count} línea(s) siguen pendientes.',
    'wms_cannot_complete_destination_not_scanned': 'No se puede completar la sesión: falta escanear la ubicación de destino.',
    'wms_document_not_confirmed': 'No se encontró el documento o no está confirmado.',
    'wms_document_type_not_supported': 'Esta sesión no admite documentos de tipo {document_type}.',
    'wms_nothing_to_undo': 'Esta línea no tiene nada registrado que se pueda deshacer.',
    'wms_undo_line_is_packed': '{name}: un bulto ya contiene {packed} de lo preparado. Sáquelo primero del bulto y luego deshaga la preparación.',
    'wms_skip_line_is_packed': '{name}: un bulto ya contiene {packed} de lo preparado. Sáquelo primero del bulto y luego omita la línea.',
    'wms_cancel_session_is_packed': '{name}: un bulto ya contiene {packed} de lo preparado. Sáquelo primero del bulto y luego cancele la sesión.',
    'wms_barcode_required': 'Escanee primero un código de barras.',
    'document_execution_line_foreign': 'Esta línea de ejecución no pertenece a este documento.',
    'document_execution_line_repeated': 'Cada línea del documento solo se puede ejecutar una vez.',
    'document_done_quantity_negative': 'La cantidad ejecutada no puede ser negativa: {quantity}.',
    'document_done_quantity_above_expected': 'La cantidad ejecutada {quantity} supera la cantidad esperada (máx. {expected}).',
    'document_held_quantity_negative': 'La cantidad retenida no puede ser negativa: {quantity}.',
    'document_held_quantity_above_received': 'La cantidad retenida {quantity} supera la cantidad recibida ({received}).',
    'document_held_quantity_needs_receipt': 'Solo una recepción puede retener mercancía.',
    'document_held_quantity_needs_code': 'Una cantidad retenida necesita el código Daño o Retenido por calidad.',
    'document_partial_needs_discrepancy_code': 'Una ejecución parcial necesita un código de discrepancia.',
    'document_correction_above_expected': 'Una corrección de {quantity} supera la cantidad esperada {expected} en valores absolutos.',
    'document_correction_sign_mismatch': 'Una corrección debe mantener el signo de la diferencia esperada: {quantity} frente a {expected}.',
    'document_correction_missing_original': 'Esta corrección no indica el documento que corrige.',
    'document_correction_original_not_found': 'No se encontró el documento corregido {document}.',
    'document_correction_would_go_negative': 'La corrección dejaría {item} por debajo de cero: actual {current}, cambio {delta}, resultado {result}.',
    'document_adjustment_would_go_negative': 'El ajuste dejaría {item} por debajo de cero: actual {current}, cambio {delta}, resultado {result}.',
    'document_line_needs_identity': 'La línea del documento debe indicar un registro, un producto o un nombre.',
    'document_rework_wrong_status': 'Un documento en estado {status} no se puede devolver a borrador; solo uno confirmado o pendiente de aprobación puede.',
    'stock_record_not_found': 'No se encontró el registro {item}.',
    'stock_product_not_found': 'No se encontró el producto {product}.',
    'stock_insufficient_record': 'Stock insuficiente para «{item}»: disponible {available}, solicitado {requested}.',
    'receipt_needs_target_location': 'El documento de recepción no tiene una ubicación de destino.',
    'receipt_needs_quarantine_location': 'La recepción incluye mercancía dañada o retenida por calidad, pero el perfil de documentos no indica ninguna ubicación de cuarentena. Indíquela en los ajustes de documentos.',
    'transfer_needs_target_location': 'El documento de transferencia no tiene una ubicación de destino.',
    'receiving_mode_needs_a_warehouse': 'Solo una ubicación de primer nivel elige cómo recibe.',
    'putaway_needs_another_location': 'La mercancía ya está aquí: elige la ubicación a la que va.',
    'replenishment_nothing_to_move': 'No hay nada que llevar de la reserva: la mercancía ya no está allí o la ubicación de surtido ya no la necesita.',
    'replenishment_shelf_scan_required': 'Escanea la ubicación de reserva de la que retiras la mercancía.',
    'replenishment_shelf_scan_mismatch': 'Ese código nombra otra ubicación: escanea la ubicación de reserva de la que se retira la mercancía.',
    'putaway_shelf_scan_required': 'Escanea la etiqueta de la ubicación antes de guardar la mercancía.',
    'home_shelf_receiving': 'Una zona de recepción no puede ser la ubicación habitual: la mercancía solo espera allí.',
    'home_shelf_quarantine': 'Una ubicación de cuarentena no puede ser la ubicación habitual: la mercancía retenida no se guarda allí.',
    'home_shelf_not_stock': 'Esta ubicación no admite stock, por eso no puede ser la ubicación habitual.',
    'stock_take_status_unchangeable': 'No se puede cambiar el estado de {current} a {new}.',
    'api_keys_limit_reached': 'La organización ya tiene {count} claves API activas, que es el máximo. Revoca una para crear otra.',
    'document_pdf_requires_confirmed': 'Un PDF se genera a partir de un documento confirmado o completado. Este está en estado {status}.',
    'documents_pdf_require_confirmed': 'Un PDF combinado solo se genera a partir de documentos confirmados o completados. No imprimibles: {numbers}.',
    'stock_take_item_not_found': 'Posición de inventario no encontrada',
    'stock_take_item_already_exists': 'El artículo ya ha sido añadido a este inventario',
    'stock_take_item_outside_location': 'Este artículo se encuentra fuera de la ubicación inventariada; contarlo aquí sobrescribiría la cantidad que tiene allí',
    'stock_take_shelf_outside_location': 'Esta ubicación no forma parte del inventario de {location}',
    'stock_take_uncounted_items': 'Quedan {count} artículos sin contar',
    'stock_none_at_location': 'En la ubicación {location} no hay {product}.',
    'stock_all_batches_held': 'Cada lote de {product} en la ubicación {location} está en cuarentena o retenido, así que no se puede usar ninguno.',
    'stock_not_enough': 'La ubicación {location} tiene {available} de {product} disponible y se pidieron {requested}.',
    'stock_take_over_cap': 'En {count} artículo(s) la cantidad contada supera con creces el stock del sistema. Revísalos y confirma para guardar las cantidades contadas.',
    'stock_take_over_tolerance': 'En {count} artículo(s) la cantidad contada se aleja del stock del sistema más de lo que permite la tolerancia de este inventario. Antes de contabilizarlas, alguien con permiso debe aceptarlas.',
    'stock_take_tolerance_reason_missing': 'En {count} artículo(s) la diferencia supera la tolerancia y no indica el motivo. Da un motivo a cada una y luego finaliza el inventario.',
    'stock_take_tolerance_not_allowed': 'Aceptar una diferencia por encima de la tolerancia requiere el permiso de aprobación de inventarios.',
    'stock_take_awaiting_recount': 'En {count} artículo(s) se pidió volver a contar. Cuéntalos otra vez y luego finaliza el inventario.',
    'stock_take_stock_moved': '{count} línea(s) se contaron contra una cantidad que las existencias ya no tienen. Se han devuelto para volver a contarlas.',
    'document_not_found': 'Documento no encontrado',
    'work_item_not_found': 'Tarea no encontrada',
    'work_item_taken': 'Otra persona acaba de tomar esta tarea.',
    'pdf_generation_failed': 'Error en la generación del PDF',
    'import_only_draft': 'Las líneas solo se pueden importar en documentos BORRADOR',
    'paste_empty': 'No hay líneas para importar — pegue al menos una fila de encabezado y una fila de datos',
    'import_asset_name_missing': 'Falta el nombre del activo',
    'import_line_name_missing': 'Falta el nombre del producto',
    'import_location_unresolved': 'No se pudo resolver la ubicación de almacenamiento',
    'import_location_not_found': 'Ninguna ubicación se llama «{value}»',
    'import_price_invalid': 'Columna «{column}»: «{value}» no es un precio',
    'import_date_invalid': 'Columna «{column}»: «{value}» no es una fecha',
    'import_column_not_a_number': 'Columna «{column}»: «{value}» no es un número',
    'import_quantity_not_positive': 'Columna «{column}»: la cantidad debe ser mayor que cero, «{value}» no lo es',
    'import_column_location_not_found': 'Columna «{column}»: no se encontró la ubicación «{value}»',
    'import_column_category_not_found': 'Columna «{column}»: no se encontró la categoría «{value}»',
    'import_unknown_unit': 'Columna «{column}»: unidad desconocida «{value}». Unidades conocidas: {units}',
    'import_column_not_yes_no': 'Columna «{column}»: «{value}» no es sí ni no',
    'import_column_not_in_options': 'Columna «{column}»: «{value}» no es una de las opciones: {options}',
    'import_column_quantity_blank': 'Columna «{column}»: la cantidad está vacía. Rellénela o quite la asignación de la cantidad para importar cada fila como 1',
    'import_column_field_shape': 'Columna «{column}»: el valor no encaja en el campo al que está asignada la columna',
    'import_field_required_unreadable': 'El campo «{field}» es obligatorio y no se puede leer de una celda',
    'import_field_required_no_column': 'El campo «{field}» es obligatorio y el archivo no tiene columna para él',
    'import_column_field_required': 'Columna «{column}»: el campo es obligatorio',
    'import_column_reason': 'Columna «{column}»: {reason}',
    'import_row_failed': 'No se pudo importar la fila',
    'document_lines_quantity_not_positive': 'Las líneas {lines} tienen una cantidad de cero o menos. Corrígelas antes de confirmar.',
    'document_delivery_lines_reference_items': 'Las líneas de un documento de entrega deben hacer referencia a productos existentes',
    'document_scrap_lines_reference_items': 'Las líneas de un documento de desecho deben hacer referencia a productos existentes',
    'document_reason_scrap_only': 'Solo un documento de desecho lleva un motivo de baja',
    'document_scrap_reason_required': 'Un documento de desecho dice por qué se da de baja la mercancía: elija un motivo y, con «Otro», escríbalo en las notas',
    'document_transfer_lines_reference_items': 'Las líneas de un documento de transferencia deben hacer referencia a productos existentes',
    'document_correction_lines_reference_items': 'Las líneas de un documento de corrección deben hacer referencia a productos existentes',
    'document_adjustment_lines_reference_items': 'Las líneas de un documento de ajuste deben hacer referencia a productos existentes',
    'recipe_collection_name_taken': 'Ya existe una colección de recetas llamada «{name}» en esta organización.',
    'recipe_name_taken': 'Ya existe una fórmula con este nombre para este producto.',
    'recipe_not_found': 'Receta no encontrada',
    'picking_active_recipe_locked': 'No se pueden editar los ingredientes mientras haya una sesión de recolección activa. Cancela o completa primero la sesión.',
    'meal_plan_dates_exclude_entries': 'Elimina primero las entradas de las fechas excluidas.',
    'meal_plan_position_taken': 'No se encontró una posición libre en esa comida.',
    'meal_plan_entry_date_out_of_range': 'La fecha de la entrada está fuera del rango de fechas del plan.',
    'meal_plan_slot_not_enabled': 'Esa comida no está habilitada para este plan.',
    'shopping_exclusion_exists': 'Esta exclusión ya existe.',
    'shopping_item_already_purchased': 'Este artículo ya está marcado como comprado.',
    'shopping_item_already_purchased_reset': 'Este artículo ya está marcado como comprado. Márcalo primero como no comprado para cambiarlo.',
    'shopping_list_not_editable': 'No se puede editar una lista de compras completada o archivada.',
    'shopping_lists_module_disabled': 'El módulo de listas de compras no está habilitado para esta organización.',
    'maker_recipe_not_found': 'Fórmula no encontrada',
    'uom_quantity_non_negative': 'La cantidad no puede ser negativa',
    'uom_conversion_unavailable': (
        'La cantidad en {unit} no se puede convertir a la unidad de '
        'almacén {stock_unit}'
    ),
    'webhook_not_found': 'Webhook no encontrado',
    'putaway_rule_not_found': 'Regla de ubicación no encontrada',
    'document_line_not_found': 'Línea de documento no encontrada',
    'putaway_unknown_context_tag': 'Grupo de categorías «{value}» desconocido — elige uno definido por una categoría existente',
    'putaway_unknown_storage_type': 'Tipo de almacén «{value}» desconocido — elige uno de los tipos de la organización',
    'location_not_internal': '«{name}» es una ubicación virtual — la mercancía solo puede ubicarse en ubicaciones reales',
    'location_archived': '«{name}» está archivada — restáurala primero o elige una ubicación que las listas aún muestren',
    'line_target_receipt_only': 'El destino solo puede indicarse en líneas de recepción — las líneas de salida y traslado toman su ubicación del documento',
    'line_target_already_received': 'Esta línea ya se recibió en la sesión de recepción abierta; la mercancía queda en la ubicación donde se recibió',
    'exclusion_not_found': 'Exclusión no encontrada',
    'tag_not_found': "Etiqueta '{tag}' no encontrada en ninguna receta",
    'meal_plan_not_found': 'Plan de comidas no encontrado',
    'meal_plan_slot_conflict': 'Hay entradas en las franjas desactivadas: {slots}',
    'meal_plan_entry_not_found': 'Entrada del plan de comidas no encontrada',
    'attachment_not_found': 'Adjunto no encontrado',
    'api_key_not_found': 'Clave API no encontrada',
    'invalid_api_key': 'Clave de API no válida o caducada',
    'api_key_owner_inactive': 'La cuenta a la que pertenece esta clave de API está inactiva.',
    'unit_conversion_already_exists': 'Ya existe una conversión desde {unit} para «{ingredient}» en esta organización. Edítala en lugar de crear otra.',
    'conversion_not_found': 'Conversión no encontrada',
    'conversion_not_found_or_system': 'Conversión no encontrada o predeterminada del sistema',
    'template_not_found': 'Plantilla no encontrada',
    'template_import_not_json': 'El archivo no se pudo leer como una exportación de plantilla: no es JSON válido.',
    'template_import_wrong_kind': 'Este archivo no es una plantilla de documento exportada.',
    'template_import_wrong_version': 'El archivo fue exportado en la versión de formato {version}; esta instalación lee la versión {supported}.',
    'template_import_invalid_field': 'El campo «{field}» falta o no es válido.',
    'template_import_unknown_placeholders': 'La plantilla hace referencia a campos que no existen: {placeholders}.',
    'template_import_not_renderable': 'No se pudo renderizar la plantilla: {detail}',
    'model_not_found': 'Modelo de equipo no encontrado',
    'widget_not_found': 'Widget no encontrado',
    'bom_line_not_found': 'Línea de lista de materiales no encontrada',
    'bom_line_already_exists': (
        'Esta fórmula ya incluye ese ingrediente — ya existe una línea entre '
        'los dos productos.'
    ),
    'bom_depth_exceeded': (
        'Esta lista de materiales está anidada más de {max_depth} niveles — '
        'demasiado profunda para resolverla.'
    ),
    'cost_line_not_found': 'Línea de coste no encontrada',
    'production_order_not_found': 'Orden de producción no encontrada',
    'production_no_recipe': (
        'No hay fórmula para este producto — cree primero una fórmula'
    ),
    'production_recipe_not_found': (
        'La fórmula {recipe_id} no existe en esta organización'
    ),
    'production_recipe_product_mismatch': ('La fórmula no pertenece a este producto'),
    'production_complete_not_draft': (
        'Esta orden de producción ya tiene el estado {status} — solo se puede '
        'completar un borrador.'
    ),
    'production_reverse_not_completed': (
        'Esta producción tiene el estado {status}, así que no hay nada que deshacer — solo se puede deshacer una producción completada.'
    ),
    'production_reverse_output_used': (
        'Esta producción no se puede deshacer: parte de lo que fabricó ya salió de su ubicación. Registre en su lugar una corrección de stock de lo que queda.'
    ),
    'production_cancel_not_draft': (
        'Esta orden de producción ya tiene el estado {status} — solo se puede '
        'cancelar un borrador.'
    ),
    'production_update_not_draft': (
        'Esta orden de producción ya tiene el estado {status} — solo se puede '
        'editar un borrador.'
    ),
    'production_actual_qty_must_be_positive': (
        'La cantidad producida debe ser mayor que cero.'
    ),
    'production_overproduction_disabled': (
        'La sobreproducción está desactivada en la configuración — esta orden '
        'no puede producir más de lo previsto.'
    ),
    'production_ingredient_unmeasurable': (
        'La unidad de un ingrediente no se puede comparar con su existencia, así que '
        'no se sabe cuánto retirar del estante: corrija antes la unidad de la línea de la fórmula.'
    ),
    'production_short_of_stock': 'No hay suficientes ingredientes en stock para esta orden de producción.',
    'output_template_not_found': 'Plantilla de salida no encontrada',
    'purchase_order_not_found': 'Orden de compra no encontrada',
    'reorder_rule_not_found': 'Regla de reposición no encontrada',
    'pricelist_entry_not_found': 'Entrada de lista de precios no encontrada',
    'reorder_max_below_min': 'max_quantity ({max_quantity}) debe ser >= min_quantity ({min_quantity})',
    'reorder_safety_stock_negative': 'safety_stock debe ser >= 0, recibido {safety_stock}',
    'reorder_min_quantity_negative': 'min_quantity debe ser >= 0, recibido {min_quantity}',
    'pricelist_unit_price_not_positive': 'unit_price debe ser > 0, recibido {unit_price}',
    'pricelist_min_quantity_not_positive': 'min_quantity debe ser > 0, recibido {min_quantity}',
    'pricelist_valid_to_before_valid_from': 'valid_to ({valid_to}) debe ser >= valid_from ({valid_from})',
    'pricelist_duplicate': (
        'Este proveedor ya tiene un precio para este producto en las mismas '
        'fechas y con la misma cantidad mínima. Edita esa entrada en lugar de '
        'añadir una segunda.'
    ),
    'tax_rate_not_found': 'Tasa de impuesto no encontrada',
    'announcement_not_found': 'Anuncio no encontrado',
    'approval_request_not_found': 'Solicitud de aprobación no encontrada',
    'cycle_count_schedule_not_found': 'Programación de conteo cíclico no encontrada',
    'document_type_config_not_found': 'Configuración del tipo de documento no encontrada',
    'history_entry_not_found': 'Entrada de historial no encontrada',
    'ingredient_not_found': 'Ingrediente no encontrado',
    'label_not_found': 'Etiqueta no encontrada',
    'scan_unrecognized': 'Código no reconocido: ningún producto, etiqueta, ubicación o documento coincide',
    'member_not_found': 'Miembro no encontrado',
    'module_not_found': 'Módulo no encontrado',
    'notification_not_found': 'Notificación no encontrada',
    'partner_not_found': 'Socio no encontrado',
    'partner_name_exists': 'Ya existe un socio con el nombre "{name}" y el tipo "{partner_type}".',
    'partner_code_exists': 'Ya existe un socio con el código "{code}".',
    'partner_delete_open_purchase_orders': 'No se puede eliminar el socio: {count} órdenes de compra abiertas hacen referencia a él',
    'partner_import_name_missing': 'Falta el nombre del socio',
    'partner_import_duplicate': 'Socio duplicado: "{twin}" ya tiene este nombre o este identificador fiscal',
    'product_not_found': 'Producto no encontrado',
    'product_template_not_found': 'Plantilla de producto no encontrada',
    'profile_not_found': 'Perfil no encontrado',
    'receiving_session_not_found': 'Sesión de recepción no encontrada',
    'request_not_found': 'Solicitud no encontrada',
    'workflow_not_found': 'Flujo de trabajo no encontrado',
    'campaign_not_found': 'Campaña no encontrada',
    'attestation_no_active_assignments': 'En el ámbito elegido no hay asignaciones activas',
    'attestation_not_draft': 'Esta campaña ya está {status}: solo se puede iniciar un borrador',
    'attestation_reminders_not_active': 'Solo se pueden enviar recordatorios de una campaña en curso',
    'campaign_deadline_past': 'La fecha límite de la campaña debe ser hoy o más tarde',
    'attestation_complete_not_allowed': 'Una campaña en estado {status} no se puede completar',
    'attestation_scope_exceeds_limit': 'El ámbito abarca más de {limit} recursos. Redúzcalo o divida la confirmación.',
    'assignment_not_found': 'Asignación no encontrada',
    'maintenance_log_not_found': 'Registro de mantenimiento no encontrado',
    'equipment_cannot_checkout_retired': 'No se puede prestar un recurso dado de baja',
    'equipment_cannot_checkout_in_maintenance': 'No se puede prestar un recurso en mantenimiento; márquelo primero como Disponible',
    'equipment_assignment_needs_person_or_location': 'Indique la persona o la ubicación, pero no ambas',
    'equipment_bulk_scope_too_large': '{matched} recursos coinciden con los filtros; una acción abarca como máximo {limit}. Acote los filtros.',
    'equipment_assignment_already_active': 'El artículo ya tiene una asignación activa',
    'equipment_assignment_already_checked_in': 'La asignación ya fue devuelta',
    'api_key_cannot_manage': 'Las claves API no pueden administrar otras claves API',
    'api_key_cannot_create': 'Las claves API no pueden crear otras claves API',
    'api_key_cannot_revoke': 'Las claves API no pueden revocar otras claves API',
    'api_key_scope_refused': 'Esta clave API está limitada a {scope} y no se puede usar aquí',
    'api_key_scope_unknown': 'No existe un ámbito de clave API llamado «{scope}»',
    'api_key_permission_not_grantable': 'Una clave API no puede recibir el permiso {permission}: usted no lo tiene, o ninguna clave lo lleva',
    'api_key_permission_outside_scope': 'El permiso {permission} no pertenece a los ámbitos elegidos para esta clave',
    'print_no_agent': 'No hay ninguna impresora conectada. Inicia Inventari Print Agent junto a la impresora.',
    'print_choose_agent': 'Hay varias impresoras conectadas. Elige en cuál imprimir.',
    'print_agent_protocol_missing': 'Este agente no dice nada sobre el protocolo de impresión que habla: es anterior al protocolo con versión. Actualiza el agente de impresión.',
    'print_agent_protocol_unsupported': 'Este agente habla el protocolo de impresión {agent}; este servidor habla el protocolo de impresión {server}. Actualiza lo más antiguo de los dos.',
    'print_agent_not_found': 'Impresora no encontrada',
    'print_job_not_found': 'Trabajo de impresión no encontrado',
    'print_job_nothing_to_print': 'Nada que imprimir: no se encontró ninguna de las etiquetas elegidas',
    'product_label_no_code': 'Nada que imprimir: ninguno de los productos elegidos tiene código. Genere uno en el formulario del producto',
    'product_label_too_narrow': 'El código {code} no cabe en una etiqueta de {width} mm de ancho: sus barras necesitan al menos {needed} mm. Elija una etiqueta más ancha',
    'product_label_too_short': 'La etiqueta de {height} mm de alto es demasiado baja: tras el nombre y el texto, a las barras del código {code} les queda muy poca altura para que un lector las vea. Elija una etiqueta más alta',
    'storage_code_template_invalid': 'La plantilla de códigos «{template}» no se puede usar. Escriba campos como {{zone}}-{{rack:02}}-{{level:02}}, con un separador entre ellos, o un prefijo de hasta cinco letras y dígitos como LOC',
    'storage_code_template_not_tree': 'Este almacén genera códigos al azar: dele una plantilla con campos, como {zone}-{rack:02}-{level:02}, antes de numerar sus ubicaciones',
    'storage_code_parent_not_numbered': 'Esta ubicación no se puede numerar por sí sola: las de encima aún no llevan los códigos de la plantilla, o está a más profundidad de la que cubre la plantilla. Numere primero el nivel superior',
    'storage_code_number_not_here': 'Solo se puede numerar una ubicación corriente, no una archivada ni virtual',
    'storage_code_template_not_warehouse': 'Una plantilla de códigos pertenece a un almacén, una ubicación en la cima del árbol',
    'print_job_not_claimed': 'Esta impresora no está imprimiendo este trabajo',
    'print_job_not_retryable': 'Solo se puede reenviar un trabajo de impresión fallido',
    'print_job_one_target': 'Envía un solo tipo de etiqueta: etiquetas del grupo por id, etiquetas del grupo por código o ubicaciones.',
    'webhook_admin_only': 'Solo los administradores pueden gestionar webhooks',
    'approvals_manage_admin_only': 'Solo administradores y gerentes pueden modificar los flujos de aprobación',
    'approvals_action_admin_only': 'No tienes permiso para aprobar o rechazar solicitudes',
    'approvals_read_forbidden': 'No tienes permiso para ver las solicitudes de aprobación',
    'approvals_write_forbidden': 'No tienes permiso para crear solicitudes de aprobación',
    'documents_approve_requires_grant': 'No tienes permiso para aprobar o rechazar documentos',
    'po_approval_workflow_missing': 'Este pedido necesita aprobación, pero todavía no hay nadie designado para darla. Pida a su administrador que lo configure.',
    'po_supplier_required': 'Una orden de compra no puede confirmarse sin proveedor',
    'document_type_requires_partner': 'Este tipo de documento requiere un socio.',
    'partner_has_no_email': 'El socio no tiene dirección de correo electrónico.',
    'po_has_no_partner': 'Este pedido no tiene un proveedor al que enviarlo.',
    'approval_no_active_workflow': 'No hay ningún flujo de aprobación activo configurado para esta acción.',
    'po_no_pending_approval_request': 'No hay ninguna solicitud de aprobación pendiente para esta orden de compra.',
    'po_request_approval_invalid_status': 'Esta orden de compra ya no puede enviarse para aprobación.',
    'po_approve_invalid_status': 'Solo se puede aprobar una orden de compra pendiente de aprobación.',
    'approval_cannot_approve_own_request': 'No puedes aprobar tu propia solicitud.',
    'approval_cannot_reject_own_request': 'No puedes rechazar tu propia solicitud.',
    'approval_approve_invalid_status': 'Solo se puede aprobar una solicitud pendiente de decisión.',
    'approval_reject_invalid_status': 'Solo se puede rechazar una solicitud pendiente de decisión.',
    'approval_cancel_invalid_status': 'Solo se puede retirar una solicitud abierta.',
    'approval_decision_already_taken': 'Otra persona ya ha resuelto esta solicitud.',
    'approval_not_stage_approver': 'No eres persona aprobadora de esta etapa.',
    'approval_only_requester_can_cancel': 'Solo quien creó la solicitud puede retirarla.',
    'approval_workflow_inactive': 'El flujo de aprobación de esta solicitud ya no está activo.',
    'approval_request_already_open': 'Ya hay una solicitud de aprobación abierta para este registro.',
    'approval_workflow_no_stages': 'Este flujo de aprobación no tiene etapas configuradas.',
    'approval_workflow_needs_stage': 'Un flujo de aprobación necesita al menos una etapa.',
    'approval_workflow_modify_blocked': 'Este flujo no se puede modificar mientras haya solicitudes esperando en él ({count}: {documents}). Quien creó una solicitud puede retirarla y un aprobador puede resolverla — ciérralas primero.',
    'approval_workflow_delete_blocked': 'Este flujo no se puede eliminar mientras haya solicitudes esperando en él ({count}: {documents}). Quien creó una solicitud puede retirarla y un aprobador puede resolverla — ciérralas primero.',
    'approval_workflow_archived': 'Este flujo se eliminó y está archivado: sus solicitudes siguen mostrando las etapas por las que pasaron, así que no se puede modificar ni volver a activar. Crea un flujo nuevo en su lugar.',
    'approval_unknown_approvers': 'Algunas de las personas aprobadoras seleccionadas no pertenecen a esta organización.',
    'approval_unknown_requesters': 'Algunas de las personas o roles seleccionados no pertenecen a esta organización.',
    'approval_requester_scope_everyone_with_names': 'Un flujo que se aplica a todos no nombra personas ni roles.',
    'approval_requester_scope_names_nobody': 'Elija al menos una persona o un rol, o a todos.',
    'approval_stage_unsolvable': 'La etapa «{label}» nunca podrá decidirse: ninguno de los aprobadores nombrados tiene acceso a aprobaciones. Añade al menos una persona con acceso.',
    'approval_scope_changed': 'Lo que este flujo retendría ha cambiado desde que lo abriste: vuelve a leerlo y activa el flujo si sigue siendo lo que quieres.',
    'approval_scope_required': 'Para activar un flujo hay que enviar el alcance que viste: el campo «expected_scope»; si no, el flujo sigue desactivado.',
    'approval_stage_open_unsolvable': 'La etapa «{label}» espera a alguien con el permiso de aprobar, y nadie en esta organización lo tiene: ninguna solicitud llegaría a decidirse. Concédelo a alguien o nombra a un aprobador.',
    'approval_required_first': 'Esta acción necesita una aprobación previa. Solicítala antes de continuar.',
    'approval_workflow_required_but_missing': 'Esto requiere una aprobación, pero no hay ningún flujo de aprobación activo para ella. Crea uno o retira el requisito.',
    'approval_required_after_rejection': 'La solicitud de aprobación de esta acción fue rechazada. Crea una nueva antes de continuar.',
    'approval_granted_for_another_holder': 'La aprobación se concedió para un préstamo a {holder}. Solicita una para este préstamo.',
    'document_no_pending_approval_request': 'No hay ninguna solicitud de aprobación pendiente para este documento.',
    'document_request_approval_invalid_status': 'Solo un documento confirmado se puede enviar a aprobación.',
    'po_confirm_invalid_status': 'Esta orden de compra no se puede confirmar en su estado actual.',
    'po_email_invalid_status': 'No se puede enviar un correo para una orden de compra en estado {status}. Solo se permiten CONFIRMED o COMPLETED.',
    'po_email_invalid_address': 'Dirección de correo del socio no válida: {email}',
    'po_partner_inactive': 'No se puede confirmar la orden de compra: el socio "{name}" está inactivo',
    'po_partner_not_supplier': 'No se puede confirmar la orden de compra: el socio "{name}" tiene el tipo "{partner_type}", que no es un tipo de proveedor',
    'po_approval_race_condition': 'No se pudo crear la solicitud de aprobación; es posible que otra acción la haya gestionado. Inténtelo de nuevo.',
    'po_already_cancelled': 'Esta orden de compra ya está cancelada',
    'po_cancel_completed': 'No se puede cancelar una orden de compra completada',
    'po_cancel_received_quantities': 'No se puede cancelar esta orden de compra porque ya se recibieron cantidades: cancele primero las recepciones vinculadas',
    'po_cancel_open_receipts': 'No se puede cancelar esta orden de compra mientras haya recepciones abiertas: complételas o cancelelas primero: {numbers}',
    'po_receipt_requires_confirmed': 'Solo las órdenes de compra confirmadas pueden crear una recepción',
    'po_line_not_found': 'Línea de orden de compra {po_line_id} no encontrada',
    'po_receive_quantity_exceeds': 'La cantidad {quantity} supera el restante {remaining} de la línea {line}',
    'po_line_product_template_not_found': 'Plantilla de producto {template_id} no encontrada',
    'po_update_not_draft': 'Solo se pueden actualizar las órdenes de compra en estado borrador',
    'po_lines_received': (
        'No se pueden actualizar las líneas: parte de los artículos ya se ha '
        'recibido. Primero cancela los albaranes de recepción correspondientes.'
    ),
    'po_import_not_draft': 'Las líneas solo se pueden importar en una orden de compra en estado borrador',
    'document_insufficient_stock': 'Stock insuficiente para confirmar: no se pudieron reservar {quantity} de {needed}',
    'document_zone_split_needs_stock_unit': 'La línea de "{item_name}" está escrita en una unidad distinta de la unidad de stock del producto y no puede repartirse entre varias estanterías; escríbala en la unidad de stock o sáquela de una sola estantería',
    'document_record_stands_elsewhere': 'El registro «{item_name}» está en «{record_shelf}», pero el documento retira de «{document_shelf}»: apunte el documento a «{record_shelf}» o mueva primero el registro',
    'document_insufficient_stock_record_elsewhere': 'Stock insuficiente para confirmar: no se pudieron reservar {quantity} de {needed} en «{document_shelf}»; el registro «{item_name}» está en «{record_shelf}»: apunte el documento a esa ubicación o mueva primero el registro',
    'stock_would_go_negative': 'Eso dejaría el stock por debajo de cero. Mientras tanto alguien ha movido esta mercancía: recarga e inténtalo de nuevo.',
    'stock_reserved_over_quantity': 'Eso reservaría más mercancía de la que hay en la estantería. Libera una reserva o vuelve a contar.',
    'document_exceeds_order_line': 'Recibir {quantity} supera la línea del pedido, en la que solo quedan {remaining} — por encima de la tolerancia de sobre-recepción del {tolerance}% se necesita a alguien con permiso para recibir por encima de la tolerancia',
    'over_receipt_needs_permission': 'Recibir {quantity} supera la tolerancia de sobre-recepción del {tolerance}% — se necesita a alguien con permiso para recibir por encima de la tolerancia',
    'over_receipt_confirm_surplus': '{product}: recibir {quantity} son {surplus} más que los {basis} esperados. ¿Recibir el excedente?',
    'over_receipt_confirm_order_surplus': '{product}: recibir {quantity} son {surplus} más que los {basis} pendientes en el pedido {order}, línea {line}. ¿Recibir el excedente?',
    'over_receipt_past_ceiling': 'Recibir {quantity} frente a {basis} supera el límite de sobrerecepción del {ceiling} % — nadie puede recibir tanto',
    'document_update_status': 'Solo se pueden actualizar los documentos en estado borrador',
    'document_correction_locked': 'Los documentos de corrección están bloqueados: solo se pueden modificar las notas. Intento de cambio: {fields}. Cancele la corrección y cree una nueva si los datos son incorrectos.',
    'field_cannot_be_cleared': 'Estos campos no se pueden vaciar: {fields}.',
    'ingredient_defaults_unreadable_file': 'No se pudo leer el archivo. La importación espera un archivo .json o .csv con una fila por ingrediente.',
    'onboarding_modules_not_offered': 'El perfil «{profile}» no ofrece estos módulos: {modules}',
    'location_chain_step_incomplete': 'Cada paso de una cadena de ubicaciones necesita un id o un nombre.',
    'current_password_incorrect': 'La contraseña actual es incorrecta',
    'storage_own_parent': 'Una ubicación no puede ser su propia ubicación superior.',
    'storage_short_code_in_use': 'El código corto «{short_code}» ya lo usa otra ubicación.',
    'storage_would_cycle': 'Mover esta ubicación debajo de una de sus propias ubicaciones subordinadas crearía un ciclo en la jerarquía de ubicaciones.',
    'template_not_builtin_copy': 'Esta plantilla no se copió de un diseño integrado',
    'smtp_config_invalid': 'La configuración del servidor de correo no es válida: {reason}',
    'module_needs_newer_platform': 'El módulo «{module}» requiere Inventari {required} o superior; la versión actual es {current}.',
    'document_delete_status': 'Solo se pueden eliminar los documentos en borrador',
    'document_wms_picking_active': 'No se puede completar ni cancelar este documento mientras haya {sessions} sesión(es) de preparación WMS en curso. Complételas o cancelelas primero.',
    'document_wms_receiving_active': 'No se puede completar ni cancelar este documento mientras haya {sessions} sesión(es) de recepción WMS en curso. Complételas o cancelelas primero.',
    'document_confirm_invalid_status': 'No se puede confirmar un documento en estado {status}',
    'document_lines_need_stock_row': 'Un documento de tipo {type} saca mercancía de una ubicación, así que cada línea debe indicar el stock del que sale: las líneas {lines} solo indican un producto',
    'document_lines_need_stock_row_one': 'Un documento de tipo {type} saca mercancía de una ubicación, así que cada línea debe indicar el stock del que sale: la línea {lines} solo indica un producto',
    'document_receipt_lines_need_product': 'Las líneas {lines} no indican ningún producto de su lista, y una recepción solo da entrada a productos: elija cada uno de la lista o añádalo como producto nuevo',
    'document_receipt_lines_need_product_one': 'La línea {lines} no indica ningún producto de su lista, y una recepción solo da entrada a productos: elíjalo de la lista o añádalo como producto nuevo',
    'document_partner_tax_id_required': 'El socio "{name}" no tiene identificador fiscal, pero los documentos de esta organización lo exigen para confirmar. Añade el identificador fiscal al socio, márcalo como particular (consumidor) o desactiva «Exigir ID fiscal del socio» en Configuración de documentos.',
    'document_complete_invalid_status': 'No se puede completar un documento en estado {status}',
    'document_complete_unanswered_lines': 'Completar sin una respuesta para cada línea registraría las líneas sin respuesta como entregadas por completo. Líneas sin respuesta: {lines}. Envíe sus cantidades o indique complete_as_planned=true para registrarlas según lo previsto',
    'document_complete_skipped_lines': 'Completar registraría las líneas omitidas como preparadas o recibidas por completo, sin que nadie haya dicho qué ocurre con ellas. Líneas omitidas: {lines}. Devuelva cada una a la lista, o respóndala como incompleta con un motivo, antes de completar; complete_as_planned no las cubre',
    'document_receipt_lines_need_expiry': 'Un producto que sale por la caducidad más próxima no puede recibirse sin fecha de caducidad: quedaría ordenado detrás de cada registro con fecha. Líneas: {lines}. Envía el lote y la fecha con la finalización o escribe la fecha en la línea',
    'picking_lot_no_longer_available': 'No se puede cerrar la preparación: el lote {lot} ya no puede dar las {quantity} unidades recogidas de él',
    'document_active_approval_request': 'Existe una solicitud de aprobación activa para este documento',
    'document_cancel_invalid_status': 'Solo se pueden cancelar los documentos en borrador, pendientes de aprobación o confirmados',
    'document_fields_closed': 'Los campos de un documento completado o cancelado ya no se pueden cambiar',
    'approval_workflow_not_found': 'Flujo de aprobación no encontrado',
    'po_pdf_invalid_status': 'El PDF solo se puede generar para órdenes de compra confirmadas o completadas. Estado actual: {status}',
    'po_pdf_generation_failed': 'No se pudo generar el PDF',
    'email_delivery_failed': 'No se pudo enviar el correo: es posible que el servidor SMTP no esté configurado',
    'invalid_partner_type': 'Este tipo de socio no se reconoce.',
    'invalid_country_code': 'El país debe ser un código ISO 3166-1 alfa-2 de dos letras (p. ej. PL).',
    'invalid_print_page_size': 'El tamaño de papel debe ser A4 o Letter.',
    'invalid_timezone': 'La zona horaria debe ser un nombre de zona IANA válido (p. ej. Europe/Warsaw).',
    'invalid_currency_code': 'La moneda debe ser un código ISO 4217 válido (p. ej. PLN).',
    'admin_permissions_required': 'Esta acción requiere permisos de administrador',
    'invalid_url_missing_host': 'URL inválida: falta el host',
    'url_must_be_public': 'La URL debe apuntar a un host público',
    'invalid_url_scheme': 'URL inválida: debe comenzar con http:// o https://',
    'rating_must_be_1_to_5': 'La calificación debe estar entre 1 y 5',
    'no_missing_ingredients': 'No hay ingredientes faltantes para agregar',
    'picking_session_not_found': 'Sesión de recolección no encontrada',
    'barcode_or_item_id_required': 'Se requiere barcode o item_id',
    'ingredient_not_found_or_not_picked': 'Ingrediente no encontrado o aún no recolectado',
    'no_valid_images': 'No se proporcionaron imágenes válidas',
    'file_must_be_image': 'El archivo debe ser una imagen',
    'vision_file_too_large': 'El archivo es demasiado grande',
    'vision_unsupported_image_type': 'El archivo «{filename}» no tiene un tipo de imagen aceptado ({content_type}). Aceptados: {accepted}.',
    'llm_provider_unreachable': (
        'No se pudo contactar con el proveedor de IA de la conexión '
        '"{name}" (modelo "{model}"). Comprueba la dirección y si el '
        'servicio está activo en Ajustes → Conexiones de IA.'
    ),
    'llm_provider_unreachable_generic': (
        'No se pudo contactar con el proveedor de IA. Comprueba la '
        'dirección de la conexión y si el servicio está activo en Ajustes '
        '→ Conexiones de IA.'
    ),
    'llm_provider_timeout': (
        'La conexión "{name}" (modelo "{model}") no respondió a tiempo. Se '
        'contactó con el proveedor: un modelo que se ejecuta en tu propio '
        'equipo puede necesitar más tiempo '
        '(LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) o una ventana de contexto menor.'
    ),
    'llm_provider_timeout_generic': (
        'El proveedor de IA no respondió a tiempo. Se contactó con él: un '
        'modelo que se ejecuta en tu propio equipo puede necesitar más '
        'tiempo (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) o una ventana de '
        'contexto menor.'
    ),
    'llm_provider_key_rejected': (
        'El proveedor de IA de la conexión "{name}" (modelo "{model}") '
        'rechazó la clave de API. Revise la clave en Ajustes → Conexiones de '
        'IA.'
    ),
    'llm_provider_key_rejected_generic': (
        'El proveedor de IA rechazó la clave de API. Revise la clave en '
        'Ajustes → Conexiones de IA.'
    ),
    'llm_provider_limit': (
        'La conexión "{name}" (modelo "{model}") fue rechazada por el '
        'proveedor de IA: el límite del plan o el saldo de la cuenta se ha '
        'agotado. Revise el plan o inténtelo más tarde.'
    ),
    'llm_provider_limit_generic': (
        'El proveedor de IA rechazó: el límite del plan o el saldo de la '
        'cuenta se ha agotado. Revise el plan o inténtelo más tarde.'
    ),
    'llm_provider_model_unknown': (
        'El proveedor de IA de la conexión "{name}" no conoce el modelo '
        '"{model}". Revise el nombre del modelo en Ajustes → Conexiones de '
        'IA.'
    ),
    'llm_provider_model_unknown_generic': (
        'El proveedor de IA no conoce el modelo configurado. Revise el nombre '
        'del modelo en Ajustes → Conexiones de IA.'
    ),
    'llm_purpose_unbound': (
        'Todavía no hay ninguna conexión de IA elegida para esta '
        'funcionalidad. Elige una en Ajustes → Conexiones de IA.'
    ),
    'llm_connection_test_failed': (
        'No se pudo completar la prueba de conexión. Comprueba la dirección '
        'e inténtalo de nuevo.'
    ),
    'llm_base_url_unresolved': (
        'No se pudo resolver el nombre de host "{host}" de la dirección de '
        'conexión de IA — comprueba la ortografía; un error tipográfico se '
        'lee aquí como un proveedor inaccesible. Si la dirección está bien '
        'escrita, pregunta a quien administra ese servidor si el nombre está '
        'publicado en DNS.'
    ),
    'llm_base_url_loopback': 'La dirección de conexión de IA apunta a un nombre de host de bucle local ({host}). Solo direcciones externas — pide a quien administra esta instalación que permita un servidor de modelo local (ajuste LLM_ALLOW_PRIVATE_NETWORKS).',
    'llm_base_url_private': 'La dirección de conexión de IA apunta a una dirección privada o interna ({host}). Solo direcciones externas — pide a quien administra esta instalación que permita un servidor de modelo local (ajuste LLM_ALLOW_PRIVATE_NETWORKS).',
    'llm_base_url_scheme': ('La dirección de conexión de IA debe usar http o https.'),
    'llm_base_url_required_for_http_provider': (
        'Este proveedor se alcanza por HTTP, así que la URL base es '
        'obligatoria — por ejemplo https://openrouter.ai/api/v1'
    ),
    'llm_base_url_no_hostname': (
        'La dirección de conexión de IA debe incluir un nombre de host.'
    ),
    'llm_base_url_refused': (
        'La dirección de conexión de IA fue rechazada. Solo direcciones '
        'externas — define LLM_ALLOW_PRIVATE_NETWORKS=true en instalaciones '
        'autoalojadas para permitir un servidor de modelo local.'
    ),
    'vision_model_returned_nothing': (
        'La conexión "{name}" (modelo "{model}") no devolvió contenido. '
        'Comprueba que el modelo lee imágenes y que su presupuesto de '
        'tokens es suficiente — la foto no es el problema.'
    ),
    'vision_model_returned_nothing_generic': (
        'El modelo no devolvió contenido. Comprueba en Ajustes → '
        'Conexiones de IA si lee imágenes.'
    ),
    'vision_label_not_understood': (
        'La IA no pudo leer esta etiqueta con la conexión "{name}" '
        '(modelo "{model}"). Prueba con una foto más nítida u otra conexión '
        'en Ajustes → Conexiones de IA.'
    ),
    'vision_nutrition_not_understood': (
        'La IA no pudo leer esta tabla nutricional con la conexión "{name}" '
        '(modelo "{model}"). Prueba con una foto más nítida u otra conexión '
        'en Ajustes → Conexiones de IA.'
    ),
    'vision_label_not_understood_generic': (
        'La IA no pudo leer esta etiqueta. Prueba con una foto más nítida u otro modelo en Conexiones de IA.'
    ),
    'vision_nutrition_not_understood_generic': (
        'La IA no pudo leer esta tabla nutricional. Prueba con una foto más nítida u otro modelo en Conexiones de IA.'
    ),
    'vision_ai_not_configured': (
        'Todavía no hay ninguna conexión de IA elegida para el reconocimiento de imágenes. Elige una en Ajustes → Conexiones de IA.'
    ),
    'invalid_organization_id': 'ID de organización inválido',
    'user_has_no_organization': 'El usuario no tiene organización',
    'unsupported_import_format': 'Formato de importación no soportado: {format}',
    'unsupported_export_format': 'Formato de exportación no soportado: {format}',
    'equipment_default_checkout_template': 'Protocolo de salida predeterminado',
    'equipment_default_checkin_template': 'Protocolo de devolución predeterminado',
    'purchase_order_standard_template': 'Pedido de compra estándar',
    'attestation_not_found': 'Enlace de atestación no encontrado',
    'attestation_expired': 'Enlace de atestación expirado',
    'attestation_refused': 'Este enlace de atestación no puede aceptar esta acción. Pide a la organización que lo envió un enlace nuevo.',
    'campaign_closed': 'Esta campaña de certificación se ha cerrado: su confirmación ya no puede registrarse. Si todavía conserva el equipo, contacte con su organización.',
    'assignment_already_returned': 'Este equipo ya se ha confirmado como devuelto: no se necesita ninguna confirmación adicional.',
    'equipment_still_assigned': (
        'El activo sigue asignado a una persona. Regístralo de vuelta primero.'
    ),
    'equipment_deploy_requires_checkout': (
        'Un activo pasa a estar prestado cuando se entrega a una persona. '
        'Préstalo en lugar de cambiar el estado.'
    ),
    'attestation_assignment_required': 'Selecciona el activo sobre el que informas del problema',
    'meta_data_spelled_twice': (
        "'meta_data' y 'metadata' nombran un mismo campo dos veces. "
        'Envía solo uno de ellos.'
    ),
    'ai_connection_not_found': 'Conexión de IA no encontrada',
    'ai_connection_still_bound': 'Esta conexión está asignada a un propósito. Desasígnela primero.',
    'ai_connection_name_taken': 'Ya existe una conexión llamada «{name}» en esta organización.',
    'ai_connection_target_required': 'Elige una conexión guardada o un proveedor para probar.',
    'ai_usage_limit_exceeded_requests': 'La organización ha usado {used} de {limit} solicitudes de IA permitidas para {period}. Contacte con un administrador para aumentar el límite.',
    'ai_usage_limit_exceeded_scans': 'La organización ha usado {used} de {limit} escaneos de etiquetas permitidos para {period}. Contacte con un administrador para aumentar el límite.',
    'invalid_reset_token': 'Token de restablecimiento inválido o caducado',
    'modules_no_organization': 'Usuario no asociado a ninguna organización',
    'modules_not_enabled': "El módulo '{module_name}' no está activado para esta organización",
    'invalid_template_module': 'El módulo debe ser "{module}"',
    'purge_blocked_by_audit_links': (
        'El artículo está vinculado a registros de auditoría y no se puede '
        'eliminar de forma permanente.'
    ),
    'permanent_delete_disabled': (
        'La eliminación permanente está desactivada para esta organización.'
    ),
    'documents_approval_workflow_missing': 'Este documento necesita aprobación, pero todavía no hay nadie designado para darla. Pida a su administrador que lo configure.',
    'category_delete_blocked_by_items': (
        'No se puede eliminar la categoría — está en uso ({count}). Mueva primero sus productos a otra categoría.'
    ),
    'category_system_field_label_locked': (
        'El nombre del campo "{field}" pertenece al catálogo de productos y no se puede cambiar.'
    ),
    'storage_delete_blocked_by_movements': (
        'No se puede eliminar la ubicación: {count} movimientos de stock hacen referencia a ella. El historial de movimientos es inmutable — archive esta ubicación en lugar de eliminarla.'
    ),
    'storage_delete_blocked_by_stock': (
        'No se puede eliminar la ubicación: el registro de stock todavía tiene aquí existencias sin ningún registro asociado. Archive esta ubicación o asigne primero esas existencias a un registro.'
    ),
    'storage_name_collision': (
        'Ya existe una ubicación llamada «{name}» en este nivel.'
    ),
    # Built-in pydantic validation errors (RequestValidationError) —
    # chosen by the error's `type`, filled from its `ctx`, by
    # app.i18n._validation.translate_validation_error.
    'validation_missing': 'Este campo es obligatorio',
    'validation_string_too_long': 'Debe tener como máximo {max_length} caracteres',
    'validation_string_too_short': 'Debe tener al menos {min_length} caracteres',
    'validation_pattern': 'No coincide con el formato esperado',
    'validation_greater_than_equal': 'Debe ser mayor o igual que {ge}',
    'validation_greater_than': 'Debe ser mayor que {gt}',
    'validation_less_than_equal': 'Debe ser menor o igual que {le}',
    'validation_less_than': 'Debe ser menor que {lt}',
    'validation_enum': 'Debe ser uno de: {expected}',
    'validation_int': 'Debe ser un número entero',
    'validation_number': 'Debe ser un número',
    'validation_boolean': 'Debe ser verdadero o falso',
    'validation_identifier': 'Debe ser un identificador válido',
    'validation_date': 'Debe ser una fecha válida',
    'document_return_requires_completed': 'Solo se puede crear una devolución a partir de un documento completado',
    'document_return_type_not_eligible': 'Solo se pueden crear devoluciones de entradas, salidas y traslados',
    'document_return_no_lines': 'Una devolución necesita al menos una línea',
    'document_original_line_missing': 'La línea {line} no existe en el documento {number}',
    'document_return_quantity_not_positive': 'La cantidad devuelta en la línea {line} debe ser mayor que cero',
    'document_return_quantity_exceeds_left': 'Una devolución de {quantity} supera lo que queda de la línea {line} ({left} de {done})',
    'document_correction_requires_completed': 'Solo se puede corregir un documento completado',
    'document_correction_no_lines': 'Una corrección necesita al menos una línea',
    'document_correction_below_zero': 'Una corrección de {delta} dejaría la línea {line} por debajo de cero — quedan {left} de {done} por corregir',
    'document_correction_type_not_correctable': 'Los documentos de este tipo no se pueden corregir',
    'document_undo_type_not_supported': 'Solo se puede deshacer una recepción, una salida o un traslado',
    'document_undo_requires_completed': 'Solo se puede deshacer un documento contabilizado',
    'document_undo_nothing_left': 'Todo lo que contabilizó este documento ya se ha revertido',
    'document_undo_blocked': 'No se puede deshacer: {reason} Use «Corregir» para cambiar lo que queda.',
    'document_undo_stock_used': 'No se puede deshacer: movimientos posteriores consumieron el stock contabilizado. Use «Corregir» para cambiar lo que queda.',
    'document_post_already_posted': 'Este documento ya se contabilizó; no se contabilizó nada por segunda vez.',
    'document_post_cancelled': 'Este documento fue cancelado, así que no se puede contabilizar.',
    'document_filter_unknown': 'Este filtro no está disponible: ningún módulo activado lo ofrece ({name}).',
    'document_post_waiting_for_approval': 'Este documento ya espera su aprobación; el stock se moverá cuando se apruebe.',
    'document_type_requires_target_location': 'Este tipo de documento necesita una ubicación de destino',
    'document_type_requires_source_location': 'Este tipo de documento necesita una ubicación de origen',
    'document_partner_must_be_supplier_or_manufacturer': 'El socio de una entrada debe ser un proveedor, un fabricante o un cliente',
    'document_partner_must_be_customer_or_supplier': 'El socio de una salida debe ser un cliente o un proveedor',
    'document_unit_price_required': 'Cada línea necesita un precio unitario — falta en las líneas {lines}',
    'document_preset_unknown': 'No existe ningún preajuste llamado {name}. Disponibles: {available}',
    'putaway_capacity_exists': 'Esta ubicación ya tiene una capacidad para este producto — edite la entrada existente.',
    'putaway_capacity_not_found': 'Entrada de capacidad no encontrada',
    'no_fields_to_update': 'No hay campos que actualizar',
    'putaway_rule_needs_location': 'Una regla de ubicación necesita al menos una ubicación.',
    'putaway_rule_needs_match_key': 'Una regla de ubicación necesita al menos una condición: un producto, una categoría, una etiqueta de contexto o un tipo de ubicación.',
    'document_template_wrong_module': 'Una plantilla de documento pertenece al módulo de documentos',
    'search_query_empty': 'Escriba algo que buscar',
    'document_type_invalid': 'No existe el tipo de documento {type}',
    'settings_payload_not_object': 'Los ajustes deben enviarse como un objeto JSON',
    'settings_field_required': 'El ajuste «{field}» es obligatorio',
    'settings_field_unknown': 'Ajuste desconocido «{field}»',
    'settings_value_not_string': 'El ajuste «{path}» debe ser un texto',
    'settings_value_not_integer': 'El ajuste «{path}» debe ser un número entero',
    'settings_value_not_number': 'El ajuste «{path}» debe ser un número',
    'settings_value_not_boolean': 'El ajuste «{path}» debe ser verdadero o falso',
    'settings_value_not_object': 'El ajuste «{path}» debe ser un objeto',
    'settings_value_not_array': 'El ajuste «{path}» debe ser una lista',
    'settings_text_too_short': 'El ajuste «{path}» debe tener al menos {limit} caracteres',
    'settings_text_too_long': 'El ajuste «{path}» debe tener como máximo {limit} caracteres',
    'settings_number_too_small': 'El ajuste «{path}» debe ser como mínimo {limit}; se recibió {value}',
    'settings_number_too_large': 'El ajuste «{path}» debe ser como máximo {limit}; se recibió {value}',
    'settings_value_not_allowed': 'El ajuste «{path}» debe ser uno de estos valores: {allowed} (se recibió {value})',
    'ai_purpose_unknown': 'Finalidad de IA desconocida «{purpose}»',
    'attachment_file_type_invalid': 'Tipo de archivo no válido: {file_type}',
    'not_an_equipment_model': 'No es un modelo de equipo',
    'bom_line_parent_mismatch': 'El producto padre de la línea no coincide con el producto que fabrica esta fórmula',
    'bom_cycle_detected': 'Ciclo detectado en la fórmula en {template_id}',
    'margin_negative': 'El margen no puede ser negativo',
    'margin_too_high': 'El margen debe ser inferior al 100 % para que el precio sea finito',
    'label_size_invalid': 'El alto y el ancho de una etiqueta deben ser mayores que 0.',
    'recipe_collection_not_found': 'Colección no encontrada',
    'recipe_collection_parent_not_found': 'Colección superior no encontrada',
    'recipe_collection_own_parent': 'Una colección no puede ser su propia colección superior',
    'recipe_collection_under_descendant': 'Una colección no se puede mover bajo una de sus subcolecciones',
    'recipe_scrape_failed': 'No se pudo obtener la receta de la URL',
    'register_date_from_after_date_to': 'La fecha de inicio no puede ser posterior a la de fin',
    'meal_plan_end_before_start': 'La fecha de fin no puede ser anterior a la de inicio',
    'meal_plan_too_long': 'Un plan no puede superar los {days} días',
    'meal_plan_no_slots': 'Activa al menos una comida en el plan',
    'meal_plan_start_in_past': 'La fecha de inicio no puede estar en el pasado',
    'meal_plan_empty': 'No se puede generar una lista de compras a partir de un plan vacío',
    'picking_terminate_reason_invalid': 'Motivo de finalización no válido: {reason}',
    'recipe_import_name_required': 'Los datos de importación deben incluir el nombre de la receta',
    'recipe_import_data_required': 'La importación JSON requiere datos',
    'recipe_import_unit_unknown': "El ingrediente '{ingredient}' usa la unidad '{unit}', que esta instancia no conoce",
    'recipe_import_unit_missing': "El ingrediente '{ingredient}' tiene cantidad pero no unidad",
    'recipe_import_url_required': 'La importación por URL requiere una URL',
    'recipe_scrape_fetch_failed': 'Jina Reader no pudo obtener {url}: {error}',
    'recipe_scrape_encoding_unsupported': 'Jina Reader devolvió contenido comprimido que no se puede leer de forma segura. Prueba otro método de importación.',
    'recipe_scrape_empty': 'Jina Reader no devolvió contenido para {url}',
    'recipe_scrape_no_ingredients': 'La IA no encontró ingredientes: puede que la página no sea una receta',
    'hex_color_invalid': 'Color hexadecimal no válido: {color}. Usa el formato #RGB o #RRGGBB',
    'shopping_list_nothing_to_convert': 'No hay líneas convertibles (ninguna tiene plantilla de producto)',
    'stock_take_bulk_item_id_required': 'El conteo masivo requiere indicar el artículo (item_id)',
    'cycle_count_scope_location_required': 'El alcance del conteo cíclico debe indicar la ubicación de almacenamiento (storage_location_id)',
    'cycle_count_no_matching_items': 'Ningún artículo cumple los criterios de la programación',
    'stock_take_active_for_location': 'Ya hay un inventario en curso para esta ubicación de almacenamiento',
    'category_name_taken': 'Ya existe una categoría con este nombre',
    'invitation_code_invalid': 'Código de invitación no válido o caducado',
    'invitation_other_address': 'Esta invitación se emitió para otra dirección de correo electrónico',
    'role_not_found': 'Rol no encontrado',
    'role_other_organization': 'El rol pertenece a otra organización',
    'user_not_in_organization': 'El usuario no pertenece a esta organización',
    'template_other_organization': 'La plantilla pertenece a otra organización',
    'template_in_use_by_items': 'No se puede eliminar la plantilla: la usan {count} artículo(s)',
    'barcode_already_exists': 'El código de barras {barcode} ya existe',
    'stock_insufficient_for_template': 'Existencias insuficientes para la plantilla {template_id}: solicitado {requested}, disponible {available}',
    'stock_lot_not_consumable': 'El lote {lot} está {status} y no se puede consumir ni reservar',
    'barcode_in_use': 'Código de barras ya en uso: {barcode}',
    'serial_number_exists': 'El número de serie ya existe: {serial_number}',
    'item_currency_mismatch': 'La moneda del artículo ({item_currency}) debe coincidir con la de la organización ({organization_currency})',
    'organization_currency_missing': 'La moneda de la organización no está configurada',
    'item_already_deleted': 'El artículo ya está eliminado',
    'item_not_deleted': 'El artículo no está eliminado',
    'item_restore_quantity_unknown': 'No se puede restaurar el artículo: se desconoce la cantidad original porque el historial de eliminación no la contiene',
    'item_purge_requires_archived': 'Solo se pueden purgar los artículos archivados',
    'item_purge_reason_required': 'Se requiere un motivo para la eliminación permanente en producción',
    'relocation_destination_foreign': 'No se puede mover el artículo: el destino no pertenece a esta organización.',
    'relocation_blocked_by_reservations': 'No se puede mover el artículo: las existencias de origen tienen reservas pendientes. Libéralas o cúmplelas primero.',
    'short_code_invalid_format': 'Formato de código no válido',
    'short_code_duplicate_in_request': 'Código corto duplicado en la solicitud: {short_code}',
    'short_codes_taken': 'Estos códigos cortos ya se usan en la organización: {codes}',
    'onboarding_profile_unknown': "Perfil desconocido: '{profile}'",
    'storage_vanished_during_batch': 'La ubicación de almacenamiento {location} desapareció durante el lote.',
    'storage_archive_blocked_by_items': 'No se puede archivar: aún hay {count} artículo(s) almacenados aquí. Muévelos primero o archiva indicando una ubicación de destino.',
    'storage_archive_target_is_self': 'No se pueden mover artículos a la ubicación que se está archivando.',
    'storage_archive_target_is_descendant': 'No se pueden mover artículos a una ubicación subordinada de la que se está archivando.',
    'storage_archive_target_archived': 'No se pueden mover artículos a una ubicación archivada.',
    'storage_restore_parent_archived': 'No se puede restaurar dentro de una ubicación superior archivada. Restaura primero la superior.',
    'storage_delete_blocked_by_references': 'No se puede eliminar la ubicación: otros registros aún hacen referencia a ella (restricción «{constraint}»). Archívala en su lugar.',
    'storage_delete_concurrent_movements': 'No se puede eliminar la ubicación: una transacción concurrente creó movimientos de stock que hacen referencia a ella. Reintenta para actualizar el recuento. Error original: {error}',
    'sole_administrator_cannot_leave': 'No puedes salir de la organización siendo el único administrador. Primero designa a otro administrador.',
    'sole_administrator_role_locked': 'No se puede cambiar el rol del único administrador. Primero asciende a otro miembro.',
    'organization_member_limit': 'Se alcanzó el límite de miembros de la organización. Pasa a Inventari Cloud para tener más plazas.',
    'registration_failed': 'No se pudo completar el registro. Inténtalo de nuevo o contacta con soporte.',
    'superuser_required': 'Esta acción requiere permisos de superusuario',
    'onboarding_already_completed': 'La configuración inicial ya está completa — usa /switch-profile',
    'module_dependency_cycle': 'Se detectó una dependencia circular que involucra al módulo «{module}»',
    'module_dependency_cycle_among': 'Se detectó una dependencia circular entre los módulos: {modules}',
    'profile_switch_unknown_modules': 'El perfil hace referencia a módulos no registrados: {unknown_modules}',
    'profile_switch_modules_not_allowed': 'Módulos no permitidos para esta organización: {not_allowed_modules}',
    'profile_switch_dependency_unregistered': 'El módulo «{module}» requiere «{missing_dependency}», que no está registrado.',
    'focus_mode_module_always_on': 'El módulo «{module}» está siempre activo y no puede ser el único foco.',
    'focus_mode_module_unregistered': 'El módulo «{module}» no está registrado.',
    'focus_mode_module_not_enabled': 'El módulo «{module}» no está habilitado para esta organización.',
    'focus_mode_already_active': 'La organización ya está centrada en «{module}».',
    'focus_mode_not_active': 'La organización no está en el modo de foco en un solo módulo.',
}
