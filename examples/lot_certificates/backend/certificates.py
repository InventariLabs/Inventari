"""The register of certificates: which numbers an organization has on file.

Every query names the organization: a certificate on file at one company is
not on file at another.
"""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LotCertificate


async def numbers_on_file_async(
    db: AsyncSession, org_id: UUID, numbers: Iterable[str]
) -> set[str]:
    """The ones of *numbers* this organization has on file."""
    wanted = sorted(set(numbers))
    if not wanted:
        return set()
    found = await db.scalars(
        select(LotCertificate.number).where(
            LotCertificate.organization_id == org_id,
            LotCertificate.number.in_(wanted),
        )
    )
    return set(found)


async def all_numbers_on_file_async(db: AsyncSession, org_id: UUID) -> list[str]:
    """Every number this organization has on file."""
    found = await db.scalars(
        select(LotCertificate.number)
        .where(LotCertificate.organization_id == org_id)
        .order_by(LotCertificate.number)
    )
    return list(found)


async def file_certificates_async(
    db: AsyncSession, org_id: UUID, numbers: Iterable[str], user_id: UUID
) -> list[str]:
    """Put *numbers* on file; the ones already there stay as they were.

    A number is filed as the line wrote it, the way the receiving rule looks
    it up; a blank one is no number. Returns the numbers this call filed, so a
    second press of the same button files nothing and says so. Flushes; the
    caller commits.
    """
    wanted = sorted({number for number in numbers if number.strip()})
    if not wanted:
        return []
    filed = await db.scalars(
        insert(LotCertificate)
        .values(
            [
                {'organization_id': org_id, 'number': number, 'filed_by': user_id}
                for number in wanted
            ]
        )
        .on_conflict_do_nothing(constraint='uq_lot_certificates_org_number')
        .returning(LotCertificate.number)
    )
    return sorted(filed)
