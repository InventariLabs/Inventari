"""The quants as the records tell them: a view over the records, not a table.

``stock_quants_from_records`` sums the live records of each
``(organization, product, shelf, batch, owner)`` group, and the reservation
rows of the same group, into the columns the quant table had. The core baseline
migration (``baseline_002``) creates it and says what each column is made of;
its statement is the one that runs.

Its readers take stock from it: ``core_api.stock.list_quants_async``, which
every module asks what stands on a shelf and what of it is free, the recipe
catalog's stock totals, the stock on a date, the reconciliation's shelf
pairs, a batch's numbers (its own screen and the batch list), the shelf
occupancy behind a location delete, the reservation guard inside deleting a
record and the CLI's reservation check; ``docs/subsystems/STOCK.md`` names
where each lives. The quant table it was once read beside is gone
(archived ``quantdrop01``): what the view says is the stock.

It is a ``Table`` on its own ``MetaData``, not a model on ``Base``:
``Base.metadata.create_all`` builds tables, and it would build this one as a
table, empty and written by nobody.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, Numeric, String, Table, Uuid

stock_quants_from_records = Table(
    'stock_quants_from_records',
    MetaData(),
    Column('id', Uuid, primary_key=True),
    Column('organization_id', Uuid, nullable=False),
    Column('product_template_id', Uuid, nullable=False),
    # NULL for records that stand on no shelf, which the quant table never held.
    Column('storage_location_id', Uuid),
    Column('lot_id', Uuid),
    Column('owner_id', Uuid),
    Column('quantity', Numeric(12, 3), nullable=False),
    Column('reserved_quantity', Numeric(12, 3), nullable=False),
    Column('removal_strategy', String(10), nullable=False),
    Column('created_at', DateTime(timezone=True)),
    Column('updated_at', DateTime(timezone=True)),
)
