from typing import Any

from app.core.modules import (
    CategoryDeclaration,
    LocalizedText,
    ModuleMetadata,
    StorageLocationDeclaration,
    StorageTypeDeclaration,
)

_CATEGORY_VISIBLE = [
    {'key': 'category_id', 'label': 'Category', 'visible': True},
]

_COMMON_EQUIPMENT_FIELDS = [
    {
        'key': 'serial_number',
        'type': 'text',
        'label': 'Serial Number',
        'visible': True,
        'required': False,
    },
    {
        'key': 'asset_tag',
        'type': 'text',
        'label': 'Asset Tag',
        'visible': True,
        'required': False,
    },
    {
        'key': 'manufacturer',
        'type': 'text',
        'label': 'Manufacturer',
        'visible': True,
        'required': False,
    },
    {
        'key': 'model',
        'type': 'text',
        'label': 'Model',
        'visible': True,
        'required': False,
    },
]

_COMMON_EQUIPMENT_TAIL = [
    {
        'key': 'group_tag',
        'type': 'text',
        'label': 'Group / Kit Tag',
        'visible': True,
        'required': False,
    },
    {
        'key': 'purchase_date',
        'type': 'date',
        'label': 'Purchase Date',
        'visible': True,
        'required': False,
    },
    {
        'key': 'warranty_until',
        'type': 'date',
        'label': 'Warranty Until',
        'visible': True,
        'required': False,
    },
    {
        'key': 'equipment_status',
        'type': 'select',
        'label': 'Status',
        'visible': True,
        'required': False,
        'options': ['AVAILABLE', 'DEPLOYED', 'MAINTENANCE', 'RETIRED'],
        # This module already names the four states for its own screens, so
        # the core form is pointed at the same keys. Two spellings of one
        # status on two screens is the defect the naming rules exist to stop.
        'options_i18n': {
            'AVAILABLE': 'equipment:status.available',
            'DEPLOYED': 'equipment:status.deployed',
            'MAINTENANCE': 'equipment:status.maintenance',
            'RETIRED': 'equipment:status.retired',
        },
    },
]

# Depreciation period per asset, with a sensible default
# per category — a server must not amortize at the same 5-year rate as a
# cordless drill. The asset-level meta value wins over this default.
_USEFUL_LIFE_YEARS_DEFAULT: dict[str, int] = {
    'LAPTOP': 5,
    'DESKTOP': 5,
    'MONITOR': 7,
    'PHONE': 3,
    'NETWORK_DEVICE': 8,
    'PERIPHERAL': 4,
    'SERVER': 10,
    'OTHER_EQUIPMENT': 5,
}


def _useful_life_field(code: str) -> dict[str, Any]:
    return {
        'key': 'useful_life_years',
        'type': 'number',
        'label': 'Useful Life (years)',
        'visible': True,
        'required': False,
        'default': _USEFUL_LIFE_YEARS_DEFAULT[code],
    }


def build_equipment_metadata() -> ModuleMetadata:
    return ModuleMetadata(
        name='equipment',
        version='0.9.0',
        display_name='Equipment',
        description='Track IT assets and physical equipment: check-out/check-in, maintenance logs, and warranty alerts.',
        icon='monitor',
        category='business',
        module_type='official',
        requires=['items'],
        categories=[
            CategoryDeclaration(
                code='LAPTOP',
                name='Laptop',
                icon='laptop',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    {
                        'key': 'ram_gb',
                        'type': 'number',
                        'label': 'RAM (GB)',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'storage_gb',
                        'type': 'number',
                        'label': 'Storage (GB)',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'os',
                        'type': 'text',
                        'label': 'Operating System',
                        'visible': True,
                        'required': False,
                    },
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('LAPTOP'),
                ],
            ),
            CategoryDeclaration(
                code='DESKTOP',
                name='Desktop Computer',
                icon='monitor',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    {
                        'key': 'ram_gb',
                        'type': 'number',
                        'label': 'RAM (GB)',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'storage_gb',
                        'type': 'number',
                        'label': 'Storage (GB)',
                        'visible': True,
                        'required': False,
                    },
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('DESKTOP'),
                ],
            ),
            CategoryDeclaration(
                code='MONITOR',
                name='Monitor / Display',
                icon='monitor-smartphone',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    {
                        'key': 'size_inches',
                        'type': 'number',
                        'label': 'Screen Size (inches)',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'resolution',
                        'type': 'text',
                        'label': 'Resolution',
                        'visible': True,
                        'required': False,
                    },
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('MONITOR'),
                ],
            ),
            CategoryDeclaration(
                code='PHONE',
                name='Phone / Tablet',
                icon='smartphone',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    {
                        'key': 'imei',
                        'type': 'text',
                        'label': 'IMEI',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'phone_number',
                        'type': 'text',
                        'label': 'Phone Number',
                        'visible': True,
                        'required': False,
                    },
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('PHONE'),
                ],
            ),
            CategoryDeclaration(
                code='NETWORK_DEVICE',
                name='Network Device',
                icon='wifi',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    {
                        'key': 'ip_address',
                        'type': 'text',
                        'label': 'IP Address',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'mac_address',
                        'type': 'text',
                        'label': 'MAC Address',
                        'visible': True,
                        'required': False,
                    },
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('NETWORK_DEVICE'),
                ],
            ),
            CategoryDeclaration(
                code='PERIPHERAL',
                name='Peripheral',
                icon='mouse',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('PERIPHERAL'),
                ],
            ),
            CategoryDeclaration(
                code='SERVER',
                name='Server',
                icon='server',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    {
                        'key': 'ip_address',
                        'type': 'text',
                        'label': 'IP Address',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'rack_position',
                        'type': 'text',
                        'label': 'Rack Position',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'ram_gb',
                        'type': 'number',
                        'label': 'RAM (GB)',
                        'visible': True,
                        'required': False,
                    },
                    {
                        'key': 'cpu',
                        'type': 'text',
                        'label': 'CPU',
                        'visible': True,
                        'required': False,
                    },
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('SERVER'),
                ],
            ),
            CategoryDeclaration(
                code='OTHER_EQUIPMENT',
                name='Other Equipment',
                icon='package',
                context_tag='equipment',
                field_definitions=[
                    *_CATEGORY_VISIBLE,
                    *_COMMON_EQUIPMENT_FIELDS,
                    *_COMMON_EQUIPMENT_TAIL,
                    _useful_life_field('OTHER_EQUIPMENT'),
                ],
            ),
        ],
        storage_types=[
            StorageTypeDeclaration(
                code='SERVER_ROOM',
                name='Server Room',
                icon='server',
                context_schema=[
                    'serial_number',
                    'manufacturer',
                    'model',
                    'ip_address',
                    'equipment_status',
                ],
                behavior_mode='NONE',
                translations={
                    'pl': LocalizedText(name='Serwerownia'),
                    'de': LocalizedText(name='Serverraum'),
                    'fr': LocalizedText(name='Salle des serveurs'),
                    'es': LocalizedText(name='Sala de servidores'),
                },
            ),
            StorageTypeDeclaration(
                code='IT_STORAGE',
                name='IT Storage / Warehouse',
                icon='warehouse',
                context_schema=[
                    'serial_number',
                    'manufacturer',
                    'model',
                    'equipment_status',
                ],
                behavior_mode='NONE',
                translations={
                    'pl': LocalizedText(name='Magazyn IT'),
                    'de': LocalizedText(name='IT-Lager'),
                    'fr': LocalizedText(name='Stockage informatique'),
                    'es': LocalizedText(name='Almacén informático'),
                },
            ),
        ],
        # Default locations are declared rather than written in
        # ``on_enable``: ``system_on_enable`` seeds them on every enable path.
        default_storage_locations=[
            # Untagged on purpose: the document picker offers unclaimed
            # locations only, and a fresh install whose every room carries
            # the equipment tag had nowhere to land a receipt. Once goods
            # stand here, the module's own screens still see the location —
            # module_scope counts the ones holding its records.
            StorageLocationDeclaration(
                code='MAIN_WAREHOUSE',
                name='Main Warehouse',
                description='Receiving and dispatch — shared by every module',
                behavior_mode='STOCK',
                translations={
                    'pl': LocalizedText(
                        name='Magazyn główny',
                        description='Przyjęcia i wydania — wspólne dla wszystkich modułów',
                    ),
                    'de': LocalizedText(
                        name='Hauptlager',
                        description='Warenannahme und Versand — von allen Modulen gemeinsam genutzt',
                    ),
                    'fr': LocalizedText(
                        name='Entrepôt principal',
                        description='Réception et expédition — partagé par tous les modules',
                    ),
                    'es': LocalizedText(
                        name='Almacén principal',
                        description='Recepción y envío — compartido por todos los módulos',
                    ),
                },
            ),
            StorageLocationDeclaration(
                code='SERVER_ROOM',
                name='Server Room',
                description='Primary server room / data center',
                behavior_mode='NONE',
                context_tag='equipment',
                translations={
                    'pl': LocalizedText(
                        name='Serwerownia',
                        description='Główna serwerownia / centrum danych',
                    ),
                    'de': LocalizedText(
                        name='Serverraum',
                        description='Hauptserverraum / Rechenzentrum',
                    ),
                    'fr': LocalizedText(
                        name='Salle des serveurs',
                        description='Salle des serveurs principale / centre de données',
                    ),
                    'es': LocalizedText(
                        name='Sala de servidores',
                        description='Sala de servidores principal / centro de datos',
                    ),
                },
            ),
            StorageLocationDeclaration(
                code='IT_STORAGE',
                name='IT Storage',
                description='IT equipment storage and logistics warehouse',
                behavior_mode='NONE',
                context_tag='equipment',
                translations={
                    'pl': LocalizedText(
                        name='Magazyn IT',
                        description='Magazyn sprzętu IT i logistyki',
                    ),
                    'de': LocalizedText(
                        name='IT-Lager',
                        description='Lager für IT-Ausstattung und Logistik',
                    ),
                    'fr': LocalizedText(
                        name='Magasin informatique',
                        description='Stockage du matériel informatique et logistique',
                    ),
                    'es': LocalizedText(
                        name='Almacén de TI',
                        description='Almacén de equipos de TI y logística',
                    ),
                },
            ),
        ],
    )
