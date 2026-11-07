"""Labels for the partner types, per language.

A refusal that names a partner's type has to name it the way the screen does:
the stored value is ``SUPPLIER``, the reader picked "Supplier". The frontend
keeps those words in ``types.*`` of the partners module's locales; the backend
composes sentences of its own and cannot reach a browser bundle, so they are
mirrored here, word for word (see :func:`app.i18n.service.get_partner_type_label`).
"""

from app.i18n._types import Language

PARTNER_TYPE_LABELS: dict[Language, dict[str, str]] = {
    'en': {
        'SUPPLIER': 'Supplier',
        'CUSTOMER': 'Customer',
        'BOTH': 'Supplier & Customer',
        'SERVICE_PROVIDER': 'Service Provider',
        'MANUFACTURER': 'Manufacturer',
        'EMPLOYEE': 'Employee',
    },
    'pl': {
        'SUPPLIER': 'Dostawca',
        'CUSTOMER': 'Klient',
        'BOTH': 'Dostawca i Klient',
        'SERVICE_PROVIDER': 'Usługodawca',
        'MANUFACTURER': 'Producent',
        'EMPLOYEE': 'Pracownik',
    },
    'de': {
        'SUPPLIER': 'Lieferant',
        'CUSTOMER': 'Kunde',
        'BOTH': 'Lieferant & Kunde',
        'SERVICE_PROVIDER': 'Dienstleister',
        'MANUFACTURER': 'Hersteller',
        'EMPLOYEE': 'Mitarbeiter',
    },
    'fr': {
        'SUPPLIER': 'Fournisseur',
        'CUSTOMER': 'Client',
        'BOTH': 'Fournisseur & Client',
        'SERVICE_PROVIDER': 'Prestataire de services',
        'MANUFACTURER': 'Fabricant',
        'EMPLOYEE': 'Employé',
    },
    'es': {
        'SUPPLIER': 'Proveedor',
        'CUSTOMER': 'Cliente',
        'BOTH': 'Proveedor y Cliente',
        'SERVICE_PROVIDER': 'Prestador de servicios',
        'MANUFACTURER': 'Fabricante',
        'EMPLOYEE': 'Empleado',
    },
    'pt': {
        'SUPPLIER': 'Fornecedor',
        'CUSTOMER': 'Cliente',
        'BOTH': 'Fornecedor e cliente',
        'SERVICE_PROVIDER': 'Prestador de serviço',
        'MANUFACTURER': 'Fabricante',
        'EMPLOYEE': 'Funcionário',
    },
}
