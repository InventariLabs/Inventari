from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy import select

from app.models.user import RegistrationRequest
from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def registration_superuser(real_async_db_session, async_test_user):
    """Pending requests span the deployment, so only a superuser handles them."""
    async_test_user.is_superuser = True
    await real_async_db_session.flush()
    return async_test_user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registration_request_flow(
    real_async_client, real_async_db_session, async_test_user, registration_superuser
):
    db = real_async_db_session
    await db.commit()  # commit async_test_user so API can authenticate

    # 1. Create a request (public endpoint)
    email = f'test-{uuid4()}@example.com'
    response = await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'Test User', 'preferred_language': 'pl'},
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()['message'] == 'Request submitted successfully'

    # 2. List requests (as admin)
    headers = _auth(registration_superuser)
    response = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    assert response.status_code == status.HTTP_200_OK
    requests = response.json()['items']
    my_request = next(r for r in requests if r['email'] == email)
    assert my_request['preferred_language'] == 'pl'
    assert my_request['is_rejected'] is False

    # 3. Reject a request
    request_id = my_request['id']
    response = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{request_id}/reject', headers=headers
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['message'] == 'Request rejected'

    # 4. Verify rejection
    result = await db.execute(
        select(RegistrationRequest).where(RegistrationRequest.id == request_id)
    )
    db_request = result.scalars().first()
    assert db_request.is_rejected is True
    assert db_request.rejected_at is not None

    # 5. Create another request and approve it
    email2 = f'test2-{uuid4()}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={
            'email': email2,
            'full_name': 'Approved User',
            'preferred_language': 'en',
        },
    )

    response = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    requests = response.json()['items']
    my_request2 = next(r for r in requests if r['email'] == email2)

    response = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{my_request2["id"]}/approve',
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert 'registration_token' in data

    # Verify approved_by_id
    result2 = await db.execute(
        select(RegistrationRequest).where(RegistrationRequest.id == my_request2['id'])
    )
    db_request2 = result2.scalars().first()
    assert db_request2.approved_by_id == async_test_user.id
    assert db_request2.accepted_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registration_request_answers_the_same_for_known_addresses(
    real_async_client, real_async_db_session, async_test_user
):
    """the public request endpoint must not confirm who has an account.

    A distinct status or message for a taken address (or one with a request
    already pending) turns this into an address oracle for anyone.
    """
    await real_async_db_session.commit()
    new_email = f'fresh-{uuid4()}@example.com'

    fresh = await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': new_email, 'full_name': 'Fresh'},
    )
    repeat_pending = await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': new_email, 'full_name': 'Again'},
    )
    existing_user = await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': async_test_user.email, 'full_name': 'Impostor'},
    )

    assert fresh.status_code == status.HTTP_201_CREATED, fresh.text
    for response in (repeat_pending, existing_user):
        assert response.status_code == fresh.status_code, response.text
        assert response.json() == fresh.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_rejected_person_who_asks_again_reaches_the_queue(
    real_async_client, real_async_db_session, async_test_user, registration_superuser
):
    """The public answer says "submitted", so the request has to exist.

    A rejected row used to keep the unique address and swallow the next
    request: the person waited for an approval that could never come, and no
    screen could reopen the case.
    """
    await real_async_db_session.commit()
    headers = _auth(registration_superuser)
    email = f'again-{uuid4()}@example.com'

    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'First Try'},
    )
    queue = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    request_id = next(r['id'] for r in queue.json()['items'] if r['email'] == email)
    await real_async_client.post(
        f'/api/v1/auth/registration-requests/{request_id}/reject', headers=headers
    )
    queue = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    assert email not in [r['email'] for r in queue.json()['items']]

    again = await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'Second Try'},
    )

    assert again.status_code == status.HTTP_201_CREATED, again.text
    queue = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    (reopened,) = [r for r in queue.json()['items'] if r['email'] == email]
    assert reopened['id'] == request_id
    assert reopened['full_name'] == 'Second Try'
    assert reopened['is_rejected'] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_org_admin_cannot_reach_registration_requests(
    real_async_client, real_async_db_session, async_test_user
):
    """the pending queue is deployment-wide — emails and names of people
    who asked to join any organization. An `admin` inside one organization is
    not the audience for that, and approval mints a registration token.
    """
    await real_async_db_session.commit()
    assert async_test_user.role == 'admin'
    assert not async_test_user.is_superuser
    headers = _auth(async_test_user)

    listing = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    assert listing.status_code == status.HTTP_403_FORBIDDEN, listing.text

    some_id = str(uuid4())
    for action in ('approve', 'reject'):
        response = await real_async_client.post(
            f'/api/v1/auth/registration-requests/{some_id}/{action}', headers=headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_complete_activates_approved_user(
    real_async_client, real_async_db_session, async_test_user, registration_superuser
):
    """A user who completes registration with an approved token must
    land as is_active=True and be able to log in without a second manual
    activation. Before the fix the registration_request path was missing from
    the is_active expression, so the user stayed inactive despite approval."""
    db = real_async_db_session
    await db.commit()  # commit async_test_user so API can authenticate
    headers = _auth(registration_superuser)

    # 1. Request + approve (approval mints the registration token)
    email = f's12-{uuid4()}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'S12 User', 'preferred_language': 'en'},
    )
    resp = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    req_id = next(r['id'] for r in resp.json()['items'] if r['email'] == email)
    approve = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{req_id}/approve', headers=headers
    )
    token = approve.json()['registration_token']

    # 2. Complete registration with the token
    password = 'StrongPass123!'
    complete = await real_async_client.post(
        '/api/v1/auth/register-complete',
        json={'token': token, 'password': password, 'preferred_language': 'en'},
    )
    assert complete.status_code == status.HTTP_200_OK
    assert complete.json()['is_active'] is True

    # 3. The user can log in immediately (no pending-approval rejection)
    login = await real_async_client.post(
        '/api/v1/auth/login',
        data={'username': email, 'password': password},
    )
    assert login.status_code == status.HTTP_200_OK
    assert 'access_token' in login.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_complete_inherits_request_language(
    real_async_client, real_async_db_session, async_test_user, registration_superuser
):
    """the completion form has no language picker — when it does not
    send one, the language captured on the registration request carries over
    instead of silently defaulting to 'en'."""
    db = real_async_db_session
    await db.commit()
    headers = _auth(registration_superuser)

    email = f'gp22-{uuid4()}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'GP22 User', 'preferred_language': 'pl'},
    )
    resp = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    req_id = next(r['id'] for r in resp.json()['items'] if r['email'] == email)
    approve = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{req_id}/approve', headers=headers
    )
    token = approve.json()['registration_token']

    # No preferred_language in the completion payload — the request's 'pl' wins.
    complete = await real_async_client.post(
        '/api/v1/auth/register-complete',
        json={'token': token, 'password': 'StrongPass123!'},
    )
    assert complete.status_code == status.HTTP_200_OK
    assert complete.json()['preferred_language'] == 'pl'

    # An explicit choice on the completion form still wins over the request.
    email2 = f'gp22b-{uuid4()}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email2, 'preferred_language': 'pl'},
    )
    resp = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    req_id2 = next(r['id'] for r in resp.json()['items'] if r['email'] == email2)
    approve2 = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{req_id2}/approve', headers=headers
    )
    token2 = approve2.json()['registration_token']

    complete2 = await real_async_client.post(
        '/api/v1/auth/register-complete',
        json={
            'token': token2,
            'password': 'StrongPass123!',
            'preferred_language': 'de',
        },
    )
    assert complete2.status_code == status.HTTP_200_OK
    assert complete2.json()['preferred_language'] == 'de'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approved_registration_mail_names_the_approving_organization(
    real_async_client,
    real_async_db_session,
    async_test_user,
    registration_superuser,
    monkeypatch,
):
    """The link mailed on approval belongs to the organization that approved it.

    It was queued with no tenant at all, so a link that exhausted its
    retries could not appear on any organization's screen — the durable
    queue held the row and nobody could reach it.
    """
    # The link is mailed only where a mail server exists to take it.
    for name, value in (
        ('SMTP_HOST', 'smtp.test.invalid'),
        ('SMTP_USER', 'queue@test.invalid'),
        ('SMTP_PASSWORD', 'secret'),
    ):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', value)
    db = real_async_db_session
    await db.commit()
    headers = _auth(registration_superuser)

    email = f'tenant-{uuid4()}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'Tenant User', 'preferred_language': 'en'},
    )
    listing = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    req_id = next(r['id'] for r in listing.json()['items'] if r['email'] == email)

    with patch(
        'app.services.email_service.email_service.send_registration_link_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as send:
        approve = await real_async_client.post(
            f'/api/v1/auth/registration-requests/{req_id}/approve', headers=headers
        )

    assert approve.status_code == status.HTTP_200_OK
    send.assert_awaited_once()
    assert send.await_args.kwargs['organization_id'] == async_test_user.organization_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_asking_again_after_approval_or_rejection_answers_201_and_the_link_can_be_reissued(
    real_async_client, real_async_db_session, async_test_user, registration_superuser
):
    await real_async_db_session.commit()
    headers = _auth(registration_superuser)

    def body(e):
        return {'email': e, 'full_name': 'X', 'preferred_language': 'en'}

    approved, rejected = f'a-{uuid4()}@example.com', f'r-{uuid4()}@example.com'
    for email in (approved, rejected):
        r = await real_async_client.post(
            '/api/v1/auth/registration-request', json=body(email)
        )
        assert r.status_code == status.HTTP_201_CREATED
    listed = (
        await real_async_client.get(
            '/api/v1/auth/registration-requests', headers=headers
        )
    ).json()['items']
    ids = {r['email']: r['id'] for r in listed}
    r = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{ids[approved]}/approve', headers=headers
    )
    assert r.status_code == status.HTTP_200_OK
    r = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{ids[rejected]}/reject', headers=headers
    )
    assert r.status_code == status.HTTP_200_OK

    # The requester asks again with the same address: same answer, no 500.
    for email in (approved, rejected):
        r = await real_async_client.post(
            '/api/v1/auth/registration-request', json=body(email)
        )
        assert r.status_code == status.HTTP_201_CREATED

    # After a reload the approved, unfinished request is still listed, and so
    # is the rejected one: asking again put it back in the queue. Approving
    # the first again hands out a fresh link.
    listed = (
        await real_async_client.get(
            '/api/v1/auth/registration-requests', headers=headers
        )
    ).json()['items']
    emails = {r['email'] for r in listed}
    assert approved in emails
    assert rejected in emails
    r = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{ids[approved]}/approve', headers=headers
    )
    assert r.json()['registration_link'].startswith('/register?token=')


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_link_shows_whose_account_it_finishes(
    real_async_client, real_async_db_session, registration_superuser
):
    await real_async_db_session.commit()
    email = f'link-{uuid4()}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'Jan Link'},
    )
    headers = _auth(registration_superuser)
    listed = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=headers
    )
    request_id = next(r['id'] for r in listed.json()['items'] if r['email'] == email)
    approved = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{request_id}/approve', headers=headers
    )
    token = approved.json()['registration_token']

    info = await real_async_client.get(f'/api/v1/auth/registration-link/{token}')
    assert info.status_code == status.HTTP_200_OK
    assert info.json() == {'email': email, 'full_name': 'Jan Link'}

    gone = await real_async_client.get('/api/v1/auth/registration-link/nope')
    assert gone.status_code == status.HTTP_404_NOT_FOUND
