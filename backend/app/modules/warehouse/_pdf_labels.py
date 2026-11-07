"""i18n labels, status maps, and type-title resolution for PDF generation.

Extracted from ``document_pdf_service`` — pure data dicts with no DB access.
All dictionaries are keyed by display-slot → localized string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from app.core.utils import pick_by_lang

if TYPE_CHECKING:
    from .models import DocumentProfile


# ---------------------------------------------------------------------------
# Labels (i18n-lite — English default, Polish overrides)
# ---------------------------------------------------------------------------

_LABELS_EN = {
    'document_details': 'Document Details',
    'reference': 'Reference',
    'scheduled': 'Scheduled',
    'document_date': 'Document date',
    'from_location': 'From',
    'to_location': 'To',
    'partner': 'Partner',
    'name': 'Name',
    'tax_id': 'Tax ID',
    'address': 'Address',
    'line_items': 'Line Items',
    'item': 'Item',
    'expected': 'Expected',
    'done': 'Done',
    'delta': 'Delta',
    'unit': 'Unit',
    'unit_price': 'Unit Price',
    'line_gross': 'Gross',
    'vat': 'VAT%',
    'status': 'Status',
    'batch': 'Lot',
    'expiry': 'Exp.',
    'total_net': 'Net Total',
    'total_tax': 'Tax Total',
    'total_gross': 'Gross Total',
    'tax_by_rate': 'Tax by rate',
    'total_due': 'Amount Due',
    'notes': 'Notes',
    'sig_prepared': 'Prepared by',
    'sig_checked': 'Checked by',
    'sig_approved': 'Approved by',
    'sig_received': 'Received by',
    'sig_issued': 'Issued by',
    'sig_carrier': 'Carrier / Driver',
    'sig_hint': 'Name, date, signature',
    'created': 'Created',
    'confirmed': 'Confirmed',
    'completed': 'Completed',
    'correction_of': 'Correction of document',
    'backorder_of': 'Backorder of',
    'return_of': 'Return of',
    'corrected_document': 'Corrected document',
    'responsible': 'Responsible person',
    'supplier': 'Supplier',
    'customer': 'Customer',
    'warehouse': 'Warehouse',
    'location_from': 'From location',
    'location_to': 'To location',
    'financial_impact': 'Financial Impact',
    'scrap_reason': 'Reason for scrapping',
    'scrap_cost': 'Cost of the write-off',
    'packing_slip': 'Packing Slip',
    'pick_list': 'Pick List',
    'shelf': 'Shelf',
    'document': 'Document',
    'package': 'Package',
    'package_of': 'of',
    'weight': 'Weight',
    'quantity': 'Quantity',
    'package_contents': 'Contents',
    'footer': 'Internal warehouse document — not a tax invoice or accounting document.',
}

_LABELS_PL = {
    'document_details': 'Dane dokumentu',
    'reference': 'Referencja / powiązany dokument',
    'scheduled': 'Planowana data',
    'document_date': 'Data dokumentu',
    'from_location': 'Z miejsca',
    'to_location': 'Do miejsca',
    'partner': 'Kontrahent',
    'name': 'Nazwa',
    'tax_id': 'NIP',
    'address': 'Adres',
    'line_items': 'Pozycje dokumentu',
    'item': 'Towar',
    'expected': 'Zamówiono',
    'done': 'Przyjęto',
    'delta': 'Delta (+/-)',
    'unit': 'J.m.',
    'unit_price': 'Cena jedn.',
    'line_gross': 'Wart. brutto',
    'vat': 'VAT%',
    'status': 'Status',
    'batch': 'Partia',
    'expiry': 'Termin',
    'total_net': 'Wartość netto',
    'total_tax': 'Kwota VAT',
    'total_gross': 'Wartość brutto',
    'tax_by_rate': 'VAT według stawek',
    'total_due': 'Do zapłaty',
    'notes': 'Uwagi',
    'sig_prepared': 'Sporządził',
    'sig_checked': 'Sprawdził',
    'sig_approved': 'Zatwierdził',
    'sig_received': 'Towar przyjął',
    'sig_issued': 'Towar wydał',
    'sig_carrier': 'Dostawca / Kierowca',
    'sig_hint': 'Imię, nazwisko, data, podpis',
    'created': 'Wystawiono',
    'confirmed': 'Potwierdzono',
    'completed': 'Zakończono',
    'correction_of': 'Korekta dokumentu',
    'backorder_of': 'Dostawa uzupełniająca do',
    'return_of': 'Zwrot do',
    'corrected_document': 'Korygowany dokument',
    'responsible': 'Osoba odpowiedzialna',
    'supplier': 'Dostawca',
    'customer': 'Odbiorca',
    'warehouse': 'Magazyn',
    'location_from': 'Z miejsca',
    'location_to': 'Do miejsca',
    'packing_slip': 'List pakowy',
    'pick_list': 'Lista kompletacji',
    'shelf': 'Półka',
    'document': 'Dokument',
    'package': 'Paczka',
    'package_of': 'z',
    'weight': 'Waga',
    'quantity': 'Ilość',
    'package_contents': 'Zawartość',
    'footer': 'Dokument wewnętrzny — nie stanowi faktury VAT ani innego dokumentu księgowego w rozumieniu ustawy o rachunkowości.',
    'financial_impact': 'Skutek finansowy',
    'scrap_reason': 'Powód złomowania',
    'scrap_cost': 'Koszt odpisu',
}


_LABELS_DE: dict[str, str] = {
    'document_details': 'Dokumentdetails',
    'reference': 'Referenz',
    'scheduled': 'Geplant',
    'document_date': 'Belegdatum',
    'from_location': 'Von Lagerort',
    'to_location': 'Zum Lagerort',
    'partner': 'Partner',
    'tax_id': 'Steuer-ID',
    'line_items': 'Positionen',
    'item': 'Artikel',
    'expected': 'Erwartet',
    'done': 'Erledigt',
    'delta': 'Differenz (+/-)',
    'unit': 'Einheit',
    'unit_price': 'Einzelpreis',
    'line_gross': 'Brutto',
    'vat': 'MwSt.%',
    'status': 'Status',
    'batch': 'Charge',
    'expiry': 'Verfällt',
    'total_net': 'Nettosumme',
    'total_tax': 'MwSt.-Summe',
    'total_gross': 'Bruttosumme',
    'tax_by_rate': 'Steuer nach Steuersätzen',
    'total_due': 'Fälliger Betrag',
    'sig_prepared': 'Erstellt von',
    'sig_checked': 'Geprüft von',
    'sig_approved': 'Genehmigt von',
    'sig_received': 'Empfangen von',
    'sig_issued': 'Ausgestellt von',
    'sig_carrier': 'Fahrer / Spediteur',
    'sig_hint': 'Name, Datum, Unterschrift',
    'created': 'Erstellt',
    'confirmed': 'Bestätigt',
    'completed': 'Abgeschlossen',
    'correction_of': 'Korrektur von Dokument',
    'backorder_of': 'Restlieferung von',
    'return_of': 'Rückgabe von',
    'corrected_document': 'Korrigiertes Dokument',
    'responsible': 'Verantwortliche Person',
    'supplier': 'Lieferant',
    'customer': 'Kunde',
    'warehouse': 'Lager',
    'location_from': 'Von Lagerort',
    'location_to': 'Zu Lagerort',
    'name': 'Name',
    'address': 'Adresse',
    'notes': 'Anmerkungen',
    'financial_impact': 'Finanzielle Auswirkung',
    'scrap_reason': 'Grund der Verschrottung',
    'scrap_cost': 'Kosten der Ausbuchung',
    'packing_slip': 'Packliste',
    'pick_list': 'Pickliste',
    'shelf': 'Regal',
    'document': 'Dokument',
    'package': 'Paket',
    'package_of': 'von',
    'weight': 'Gewicht',
    'quantity': 'Menge',
    'package_contents': 'Inhalt',
    'footer': 'Internes Lagerdokument — keine Rechnung und kein Buchungsbeleg.',
}

_LABELS_FR: dict[str, str] = {
    'document_details': 'Détails du document',
    'reference': 'Référence',
    'scheduled': 'Planifié',
    'document_date': 'Date du document',
    'from_location': "Depuis l'emplacement",
    'to_location': "Vers l'emplacement",
    'partner': 'Partenaire',
    'tax_id': 'N° de TVA',
    'line_items': 'Lignes du document',
    'item': 'Article',
    'expected': 'Attendu',
    'done': 'Reçu',
    'delta': 'Écart (+/-)',
    'unit': 'Unité',
    'unit_price': 'Prix unitaire',
    'line_gross': 'Brut',
    'vat': 'TVA%',
    'status': 'Statut',
    'batch': 'Lot',
    'expiry': 'Péremption',
    'total_net': 'Total net',
    'total_tax': 'Total TVA',
    'total_gross': 'Total brut',
    'tax_by_rate': 'TVA par taux',
    'total_due': 'Montant dû',
    'sig_prepared': 'Établi par',
    'sig_checked': 'Vérifié par',
    'sig_approved': 'Approuvé par',
    'sig_received': 'Reçu par',
    'sig_issued': 'Émis par',
    'sig_carrier': 'Transporteur / Chauffeur',
    'sig_hint': 'Nom, date, signature',
    'created': 'Créé',
    'confirmed': 'Confirmé',
    'completed': 'Terminé',
    'correction_of': 'Correction du document',
    'backorder_of': 'Reliquat de',
    'return_of': 'Retour de',
    'corrected_document': 'Document corrigé',
    'responsible': 'Personne responsable',
    'supplier': 'Fournisseur',
    'customer': 'Client',
    'warehouse': 'Entrepôt',
    'location_from': 'Emplacement source',
    'location_to': 'Emplacement cible',
    'name': 'Nom',
    'address': 'Adresse',
    'notes': 'Remarques',
    'financial_impact': 'Impact financier',
    'scrap_reason': 'Motif de la mise au rebut',
    'scrap_cost': 'Coût de la mise au rebut',
    'packing_slip': 'Bordereau de colisage',
    'pick_list': 'Bon de préparation',
    'shelf': 'Étagère',
    'document': 'Document',
    'package': 'Colis',
    'package_of': 'sur',
    'weight': 'Poids',
    'quantity': 'Quantité',
    'package_contents': 'Contenu',
    'footer': 'Document interne d’entrepôt — ne constitue ni une facture ni une pièce comptable.',
}

_LABELS_ES: dict[str, str] = {
    'document_details': 'Detalles del documento',
    'reference': 'Referencia',
    'scheduled': 'Programado',
    'document_date': 'Fecha del documento',
    'from_location': 'Desde ubicación',
    'to_location': 'Hasta ubicación',
    'partner': 'Socio',
    'tax_id': 'NIF',
    'line_items': 'Líneas del documento',
    'item': 'Artículo',
    'expected': 'Esperado',
    'done': 'Recibido',
    'delta': 'Diferencia (+/-)',
    'unit': 'Unidad',
    'unit_price': 'Precio unitario',
    'line_gross': 'Bruto',
    'vat': 'IVA%',
    'status': 'Estado',
    'batch': 'Lote',
    'expiry': 'Caducidad',
    'total_net': 'Total neto',
    'total_tax': 'Total IVA',
    'total_gross': 'Total bruto',
    'tax_by_rate': 'IVA por tipo',
    'total_due': 'Importe debido',
    'sig_prepared': 'Preparado por',
    'sig_checked': 'Verificado por',
    'sig_approved': 'Aprobado por',
    'sig_received': 'Recibido por',
    'sig_issued': 'Emitido por',
    'sig_carrier': 'Transportista / Conductor',
    'sig_hint': 'Nombre, fecha, firma',
    'created': 'Creado',
    'confirmed': 'Confirmado',
    'completed': 'Completado',
    'correction_of': 'Corrección del documento',
    'backorder_of': 'Pendiente de entrega de',
    'return_of': 'Devolución de',
    'corrected_document': 'Documento corregido',
    'responsible': 'Persona responsable',
    'supplier': 'Proveedor',
    'customer': 'Cliente',
    'warehouse': 'Almacén',
    'location_from': 'Ubicación origen',
    'location_to': 'Ubicación destino',
    'name': 'Nombre',
    'address': 'Dirección',
    'notes': 'Notas',
    'financial_impact': 'Impacto financiero',
    'scrap_reason': 'Motivo de la baja',
    'scrap_cost': 'Coste de la baja',
    'packing_slip': 'Lista de embalaje',
    'pick_list': 'Lista de picking',
    'shelf': 'Estante',
    'document': 'Documento',
    'package': 'Bulto',
    'package_of': 'de',
    'weight': 'Peso',
    'quantity': 'Cantidad',
    'package_contents': 'Contenido',
    'footer': 'Documento interno de almacén — no es una factura ni un documento contable.',
}


# ---------------------------------------------------------------------------
# Status display labels
# ---------------------------------------------------------------------------

_LINE_STATUS_LABELS_EN: dict[str, str] = {
    'DONE': 'Done',
    'PARTIAL': 'Partial',
    'EXCEPTION': 'Exception',
    'PENDING': 'Pending',
}

_LINE_STATUS_LABELS_PL: dict[str, str] = {
    'DONE': 'Wykonano',
    'PARTIAL': 'Cząstkowo',
    'EXCEPTION': 'Wyjątek',
    'PENDING': 'Oczekuje',
}


_LINE_STATUS_LABELS_DE: dict[str, str] = {
    'DONE': 'Erledigt',
    'PARTIAL': 'Teilweise',
    'EXCEPTION': 'Ausnahme',
    'PENDING': 'Ausstehend',
}

_LINE_STATUS_LABELS_FR: dict[str, str] = {
    'DONE': 'Terminé',
    'PARTIAL': 'Partiel',
    'EXCEPTION': 'Exception',
    'PENDING': 'En attente',
}

_LINE_STATUS_LABELS_ES: dict[str, str] = {
    'DONE': 'Completado',
    'PARTIAL': 'Parcial',
    'EXCEPTION': 'Excepción',
    'PENDING': 'Pendiente',
}


def _get_line_status_map(lang: str) -> dict[str, str]:
    return pick_by_lang(
        lang,
        _LINE_STATUS_LABELS_EN,
        pl=_LINE_STATUS_LABELS_PL,
        de=_LINE_STATUS_LABELS_DE,
        fr=_LINE_STATUS_LABELS_FR,
        es=_LINE_STATUS_LABELS_ES,
    )


# ---------------------------------------------------------------------------
# Document title resolution
# ---------------------------------------------------------------------------

_DEFAULT_TYPE_TITLES_EN = {
    'IN': 'Goods Receipt Note',
    'OUT': 'Goods Dispatch Note',
    'INT': 'Internal Transfer',
    'INTERNAL_IN': 'Internal Production Receipt',
    'INTERNAL_OUT': 'Internal Consumption Note',
    'CORRECTION': 'Correction',
    'SCRAP': 'Scrap Note',
    # Legacy
    'PZ': 'Goods Receipt Note',
    'WZ': 'Goods Dispatch Note',
    'MM': 'Internal Transfer',
}

_DEFAULT_TYPE_TITLES_PL = {
    'IN': 'Przyjęcie Zewnętrzne',
    'OUT': 'Wydanie Zewnętrzne',
    'INT': 'Przesunięcie Magazynowe',
    'INTERNAL_IN': 'Przyjęcie wewnętrzne',
    'INTERNAL_OUT': 'Rozchód wewnętrzny',
    'CORRECTION': 'Korekta',
    'SCRAP': 'Złomowanie',
    'PZ': 'Przyjęcie Zewnętrzne',
    'WZ': 'Wydanie Zewnętrzne',
    'MM': 'Przesunięcie Magazynowe',
}


_DEFAULT_TYPE_TITLES_DE: dict[str, str] = {
    'IN': 'Wareneingang',
    'OUT': 'Warenausgang',
    'INT': 'Interne Umbuchung',
    'INTERNAL_IN': 'Interner Produktionszugang',
    'INTERNAL_OUT': 'Interner Verbrauch',
    'CORRECTION': 'Korrektur',
    'SCRAP': 'Ausschussbeleg',
    'PZ': 'Wareneingang',
    'WZ': 'Warenausgang',
    'MM': 'Interne Umbuchung',
}

_DEFAULT_TYPE_TITLES_FR: dict[str, str] = {
    'IN': 'Bon de réception',
    'OUT': 'Bon de livraison',
    'INT': 'Transfert interne',
    'INTERNAL_IN': 'Réception de production',
    'INTERNAL_OUT': 'Note de consommation',
    'CORRECTION': 'Correction',
    'SCRAP': 'Bon de mise au rebut',
    'PZ': 'Bon de réception',
    'WZ': 'Bon de livraison',
    'MM': 'Transfert interne',
}

_DEFAULT_TYPE_TITLES_ES: dict[str, str] = {
    'IN': 'Nota de recepción',
    'OUT': 'Nota de expedición',
    'INT': 'Transferencia interna',
    'INTERNAL_IN': 'Recepción de producción',
    'INTERNAL_OUT': 'Nota de consumo',
    'CORRECTION': 'Corrección',
    'SCRAP': 'Nota de desecho',
    'PZ': 'Nota de recepción',
    'WZ': 'Nota de expedición',
    'MM': 'Transferencia interna',
}


def _resolve_doc_title(
    doc_type: str,
    profile: DocumentProfile | None,
    lang: str,
) -> str:
    """Return the display title for the document type.

    Priority: profile.type_labels → language-specific default → raw type code.
    """
    if profile and profile.type_labels:
        label = profile.type_labels.get(doc_type)
        if label:
            return cast(str, label)

    defaults = pick_by_lang(
        lang,
        _DEFAULT_TYPE_TITLES_EN,
        pl=_DEFAULT_TYPE_TITLES_PL,
        de=_DEFAULT_TYPE_TITLES_DE,
        fr=_DEFAULT_TYPE_TITLES_FR,
        es=_DEFAULT_TYPE_TITLES_ES,
    )
    return cast(str, defaults.get(doc_type, doc_type))


# ---------------------------------------------------------------------------
# Discrepancy codes
# ---------------------------------------------------------------------------
#
# The printout used to carry the stored constant — "SHORTAGE" — to a supplier
# or a driver who has no reason to know it, followed by a colon with nothing
# after it whenever the optional reason was left blank. The wording matches
# what the screens show for the same code.

_DISCREPANCY_LABELS_EN: dict[str, str] = {
    'SHORTAGE': 'Shortage',
    'DAMAGE': 'Damage',
    'QUALITY_HOLD': 'Quality hold',
    'COUNT_VARIANCE': 'Count variance',
    'SURPLUS': 'Surplus from supplier',
    'OTHER': 'Other',
}

_DISCREPANCY_LABELS_PL: dict[str, str] = {
    'SHORTAGE': 'Brak ilości',
    'DAMAGE': 'Uszkodzenie',
    'QUALITY_HOLD': 'Blokada jakościowa',
    'COUNT_VARIANCE': 'Różnica inwentaryzacyjna',
    'SURPLUS': 'Nadwyżka od dostawcy',
    'OTHER': 'Inne',
}

_DISCREPANCY_LABELS_DE: dict[str, str] = {
    'SHORTAGE': 'Fehlmenge',
    'DAMAGE': 'Beschädigung',
    'QUALITY_HOLD': 'Qualitätssperre',
    'COUNT_VARIANCE': 'Zähldifferenz',
    'SURPLUS': 'Überlieferung vom Lieferanten',
    'OTHER': 'Sonstige',
}

_DISCREPANCY_LABELS_FR: dict[str, str] = {
    'SHORTAGE': 'Manquant',
    'DAMAGE': 'Dommage',
    'QUALITY_HOLD': 'Blocage qualité',
    'COUNT_VARIANCE': "Écart d'inventaire",
    'SURPLUS': 'Excédent du fournisseur',
    'OTHER': 'Autre',
}

_DISCREPANCY_LABELS_ES: dict[str, str] = {
    'SHORTAGE': 'Faltante',
    'DAMAGE': 'Daño',
    'QUALITY_HOLD': 'Retención de calidad',
    'COUNT_VARIANCE': 'Variación de conteo',
    'SURPLUS': 'Excedente del proveedor',
    'OTHER': 'Otro',
}


def _get_discrepancy_map(lang: str) -> dict[str, str]:
    """Discrepancy code -> label a reader of the printout can act on."""
    return pick_by_lang(
        lang,
        _DISCREPANCY_LABELS_EN,
        pl=_DISCREPANCY_LABELS_PL,
        de=_DISCREPANCY_LABELS_DE,
        fr=_DISCREPANCY_LABELS_FR,
        es=_DISCREPANCY_LABELS_ES,
    )


# ---------------------------------------------------------------------------
# Scrap reasons
# ---------------------------------------------------------------------------
#
# The binder copy of a write-off says why, in the words the document page
# uses for the same code, not the stored constant.

_SCRAP_REASON_LABELS_EN: dict[str, str] = {
    'DAMAGED': 'Damaged',
    'EXPIRED': 'Expired',
    'QUALITY': 'Quality problem',
    'OTHER': 'Other',
}

_SCRAP_REASON_LABELS_PL: dict[str, str] = {
    'DAMAGED': 'Uszkodzenie',
    'EXPIRED': 'Przeterminowanie',
    'QUALITY': 'Problem z jakością',
    'OTHER': 'Inny',
}

_SCRAP_REASON_LABELS_DE: dict[str, str] = {
    'DAMAGED': 'Beschädigt',
    'EXPIRED': 'Abgelaufen',
    'QUALITY': 'Qualitätsproblem',
    'OTHER': 'Sonstiges',
}

_SCRAP_REASON_LABELS_FR: dict[str, str] = {
    'DAMAGED': 'Endommagé',
    'EXPIRED': 'Périmé',
    'QUALITY': 'Problème de qualité',
    'OTHER': 'Autre',
}

_SCRAP_REASON_LABELS_ES: dict[str, str] = {
    'DAMAGED': 'Dañado',
    'EXPIRED': 'Caducado',
    'QUALITY': 'Problema de calidad',
    'OTHER': 'Otro',
}


def _get_scrap_reason_map(lang: str) -> dict[str, str]:
    """Scrap reason code -> the label the document page shows for it."""
    return pick_by_lang(
        lang,
        _SCRAP_REASON_LABELS_EN,
        pl=_SCRAP_REASON_LABELS_PL,
        de=_SCRAP_REASON_LABELS_DE,
        fr=_SCRAP_REASON_LABELS_FR,
        es=_SCRAP_REASON_LABELS_ES,
    )
