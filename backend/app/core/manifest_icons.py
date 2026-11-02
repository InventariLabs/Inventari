"""The icon names a module manifest may use.

The catalogue draws a module's ``icon`` through ``DynamicIcon``, which holds a
closed list of Lucide icons rather than the whole Lucide set (the whole set
would ship every icon to every browser). A name outside that list is drawn as a
generic package icon, and the only trace is a console warning in development.
``module validate`` and ``module install`` use this list to tell the author
before that happens.

Mirrors ``ICON_MAP`` in ``frontend/src/components/ui/DynamicIcon.tsx`` —
``DynamicIcon.manifestIcons.test.ts`` fails when the two drift.
"""

MANIFEST_ICONS = frozenset(
    {
        'Apple',
        'Archive',
        'Baby',
        'Backpack',
        'BarChart3',
        'Beef',
        'Beer',
        'BookOpen',
        'Box',
        'Building',
        'Building2',
        'CakeSlice',
        'Camera',
        'Candy',
        'Carrot',
        'CheckCheck',
        'Cheese',
        'ChefHat',
        'Cherry',
        'ClipboardCheck',
        'Coffee',
        'Cookie',
        'CookingPot',
        'CupSoda',
        'Container',
        'Cpu',
        'Cross',
        'Croissant',
        'Dog',
        'Drumstick',
        'Egg',
        'FileCheck',
        'Fish',
        'FlaskConical',
        'GlassWater',
        'Grape',
        'Hammer',
        'Home',
        'IceCream',
        'Key',
        'Landmark',
        'Laptop',
        'Leaf',
        'LeafyGreen',
        'Lock',
        'Milk',
        'Monitor',
        'MonitorSmartphone',
        'Mouse',
        'Package',
        'Pill',
        'Pint',
        'Pizza',
        'Printer',
        'Refrigerator',
        'Sandwich',
        'Server',
        'Settings',
        'Shapes',
        'Shell',
        'ShoppingBag',
        'ShoppingBasket',
        'ShoppingCart',
        'Smartphone',
        'Snowflake',
        'SoapDispenserDroplet',
        'Soup',
        'Stethoscope',
        'Store',
        'Thermometer',
        'Truck',
        'Utensils',
        'Warehouse',
        'Webhook',
        'Wheat',
        'Wifi',
        'Wine',
        'Wrench',
        'Zap',
        'Factory',
        'Move',
    }
)


def _pascal(name: str) -> str:
    """The frontend's lookup: ``shopping-cart`` and ``shopping_cart`` → ``ShoppingCart``."""
    return ''.join(
        segment[:1].upper() + segment[1:].lower()
        for segment in name.replace('_', '-').split('-')
    )


def is_drawable_icon(name: str) -> bool:
    """True when the frontend draws ``name`` rather than its fallback icon."""
    return name in MANIFEST_ICONS or _pascal(name) in MANIFEST_ICONS
