"""
Creates test users for k6 load tests.

Usage (from the backend directory inside the container or locally):
    docker compose exec backend uv run python seed_load_test_users.py
    docker compose exec backend uv run python seed_load_test_users.py --count 200
    docker compose exec backend uv run python seed_load_test_users.py --clean

    # Password via environment variable (recommended — does not appear in shell history):
    K6_PASSWORD='MySecret123!' docker compose exec -e K6_PASSWORD backend \
        uv run python seed_load_test_users.py --count 100 --stdout > load_tests/users.csv

    # Password via flag (visible in ps output and shell history):
    docker compose exec backend uv run python seed_load_test_users.py \
        --count 100 --password 'MySecret123!'

Options:
    --count N     Number of users to create (default: 100)
    --prefix      Email prefix (default: k6user)
    --password    Shared password for all users
                  (falls back to K6_PASSWORD env var; required if neither is set)
    --clean       Delete all existing k6 users before creating new ones
    --dry-run     Show what would be created without saving anything

Outputs a CSV file ready for use with k6:
    load_tests/users.csv
"""

import argparse
import csv
import os
import sys
import uuid

# Ensure we run with backend on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.module_registry import module_registry
from app.database import SessionLocal
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash

# Standalone seeders bypass app.main startup, so module models — which core
# models reference via SQLAlchemy relationships — are never imported. Discover
# modules now so the mapper can resolve every relationship before the first query
# (otherwise the first query raises a mapper-configuration error).
module_registry.discover_modules()

DEFAULT_COUNT = 100
DEFAULT_PREFIX = 'k6user'
CSV_OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'load_tests', 'users.csv')


def clean_k6_users(db, prefix: str, info=print):
    users = (
        db.query(User)
        .filter(User.email.like(f'{prefix}%@loadtest.inventari.app'))
        .all()
    )
    if not users:
        info(f'No users with prefix {prefix} found to delete.')
        return 0

    orgs: dict[uuid.UUID, Organization] = {}
    for user in users:
        # Delete organisation if it was created only for this user
        if user.organization_id:
            org = (
                db.query(Organization)
                .filter(Organization.id == user.organization_id)
                .first()
            )
            if org and org.name.startswith('LoadTest Org'):
                orgs[org.id] = org

    # users.organization_id and organizations.created_by reference each other,
    # so the ORM cannot order deleting both in one flush — it aborts with
    # "Circular dependency detected". Clear the users' side first, then delete
    # the organizations, then the users: an organization must go before the
    # user its created_by still points at.
    for user in users:
        user.organization_id = None
    db.flush()

    for org in orgs.values():
        db.delete(org)
    db.flush()

    for user in users:
        db.delete(user)

    db.commit()
    info(f'Deleted {len(users)} k6 users.')
    return len(users)


def create_k6_users(
    db, count: int, prefix: str, password: str, dry_run: bool, info=print
):
    created = []
    skipped = 0
    hashed = get_password_hash(password)

    for i in range(1, count + 1):
        email = f'{prefix}{i:04d}@loadtest.inventari.app'

        existing = db.query(User).filter(User.email == email).first()
        if existing:
            skipped += 1
            created.append({'email': email, 'password': password})
            continue

        if dry_run:
            info(f'  [dry-run] Would create: {email}')
            created.append({'email': email, 'password': password})
            continue

        # Each user gets their own organisation — simulates isolated home users
        user = User(
            email=email,
            hashed_password=hashed,
            full_name=f'Load Test User {i:04d}',
            role='user',
            is_active=True,
        )
        db.add(user)
        db.flush()

        org = Organization(
            name=f'LoadTest Org {i:04d}',
            created_by=user.id,
        )
        db.add(org)
        db.flush()

        user.organization_id = org.id
        created.append({'email': email, 'password': password})

        if i % 10 == 0:
            db.commit()
            info(f'  Created {i}/{count}...', end='\r')

    if not dry_run:
        db.commit()

    return created, skipped


def write_csv(users: list[dict], path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['email', 'password'])
        writer.writeheader()
        writer.writerows(users)
    print(f'\n✅ CSV saved: {os.path.abspath(path)}')
    print('   Use in k6: -e USERS_CSV=/users.csv')


def write_csv_stdout(users: list[dict]):
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=['email', 'password'])
    writer.writeheader()
    writer.writerows(users)
    sys.stdout.write(buf.getvalue())


def main():
    parser = argparse.ArgumentParser(description='Seed k6 load test users')
    parser.add_argument(
        '--count',
        type=int,
        default=DEFAULT_COUNT,
        help=f'Number of users to create (default: {DEFAULT_COUNT})',
    )
    parser.add_argument(
        '--prefix',
        default=DEFAULT_PREFIX,
        help=f'Email prefix (default: {DEFAULT_PREFIX})',
    )
    parser.add_argument(
        '--password',
        default=None,
        help='Shared password for all users (or set K6_PASSWORD env var)',
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='Delete existing k6 users before creating new ones',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be created without saving',
    )
    parser.add_argument(
        '--stdout',
        action='store_true',
        help='Print CSV to stdout (pipe to host: ... --stdout > load_tests/users.csv)',
    )
    args = parser.parse_args()

    password = args.password or os.environ.get('K6_PASSWORD')
    if not password:
        parser.error(
            'Password is required. Pass --password <pwd> or set the K6_PASSWORD environment variable.'
        )

    # When --stdout is used, print goes to stderr to keep the CSV clean
    def _stderr_print(*a, **kw):
        return print(*a, **{**kw, 'file': sys.stderr})

    info = _stderr_print if args.stdout else print

    info(f'{"[DRY RUN] " if args.dry_run else ""}Creating {args.count} test users...')
    info(
        f'  Email pattern: {args.prefix}0001@loadtest.inventari.app ... {args.prefix}{args.count:04d}@loadtest.inventari.app'
    )
    info(
        f'  Password: {"(from K6_PASSWORD)" if not args.password else "(from --password)"}'
    )

    db = SessionLocal()
    try:
        if args.clean and not args.dry_run:
            clean_k6_users(db, args.prefix, info)

        users, skipped = create_k6_users(
            db, args.count, args.prefix, password, args.dry_run, info
        )

        info(f'\n✅ Done: {len(users) - skipped} new, {skipped} already existed')

        if not args.dry_run:
            if args.stdout:
                write_csv_stdout(users)
            else:
                write_csv(users, CSV_OUTPUT)

    except Exception as e:  # noqa: BLE001 — top-level script handler; prints the traceback
        db.rollback()
        print(f'\n❌ Error: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
