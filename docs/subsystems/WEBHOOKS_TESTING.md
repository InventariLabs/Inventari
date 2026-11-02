# Webhooks — Manual Testing Guide

This guide walks you through testing the webhooks subsystem using `curl`
against a running dev stack. There is no standalone test script — all
steps are manual shell commands you can copy-paste.

## Prerequisites

- Dev stack running on port **8005** (`docker compose up -d`)
- Administrator account — `make dev-up` creates it and prints the credentials
  (`DEV_ADMIN_EMAIL` / `DEV_ADMIN_PASSWORD` in the `Makefile`)
- [webhook.site](https://webhook.site) (or any receiver) for inspecting deliveries

## Step 1: Login

OAuth2 password flow — note `x-www-form-urlencoded` body:

```bash
# The credentials `make dev-up` created, straight from the Makefile — no
# second copy of the password to drift out of date.
read -r DEV_ADMIN_EMAIL DEV_ADMIN_PASSWORD <<<"$(make -s print-dev-admin)"

TOKEN=$(curl -s -X POST http://localhost:8005/api/v1/auth/login \
  -d "username=$DEV_ADMIN_EMAIL&password=$DEV_ADMIN_PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo $TOKEN
```

## Step 2: Enable the webhooks module

```bash
curl -s -X POST http://localhost:8005/api/v1/modules/toggle \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"module_name": "webhooks", "enabled": true}'
```

## Step 3: Check available events

```bash
curl -s http://localhost:8005/api/v1/webhooks/events \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

> **Note:** The `webhook.test` event type is **not** listed here. It is a
> synthetic event fired only by the test-ping endpoint
> (`deliver_test_ping` in `webhook_service.py`) and has no real-world trigger.
> It cannot be subscribed to — creating an endpoint with it is refused as an
> unknown event type — and the ping is sent whatever the endpoint subscribes to.

## Step 4: Create an endpoint

Open [webhook.site](https://webhook.site), copy your unique URL, then:

```bash
ENDPOINT_ID=$(curl -s -X POST http://localhost:8005/api/v1/webhooks/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Endpoint",
    "url": "https://webhook.site/YOUR-UUID",
    "secret": "my-secret",
    "event_types": ["item.created", "item.used"]
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Endpoint: $ENDPOINT_ID"
```

## Step 5: Send a test ping

```bash
curl -s -X POST "http://localhost:8005/api/v1/webhooks/endpoints/$ENDPOINT_ID/test" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Check webhook.site — you should receive a `webhook.test` payload.

## Step 6: Trigger a real event

Create an item to fire `item.created`. An item needs a location, so take the
first one the organization has:

```bash
LOCATION_ID=$(curl -s "http://localhost:8005/api/v1/locations" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; d=json.load(sys.stdin); print((d['items'] if isinstance(d, dict) else d)[0]['id'])")

curl -s -X POST http://localhost:8005/api/v1/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Webhook Test Item", "quantity": 1, "location_id": "'"$LOCATION_ID"'"}' | python3 -m json.tool
```

Check webhook.site — you should receive an `item.created` payload.

## Step 7: Verify HMAC signature

The `X-Inventari-Signature-256` header contains an HMAC-SHA256 of the raw
request body using the endpoint's `secret`:

```python
import hmac, hashlib
secret = "my-secret"
body = b'...'  # raw webhook body (the exact bytes received)
sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
print(sig)  # Compare with X-Inventari-Signature-256 header
```

## Step 8: Check delivery logs

```bash
curl -s "http://localhost:8005/api/v1/webhooks/endpoints/$ENDPOINT_ID/deliveries" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

## Networking (Docker on Linux)

The backend runs in a Docker container on the `<project>_app-network`
bridge network (`inventari_app-network` when the checkout directory is
`inventari`, the compose project name by default). If you run a receiver
**on the host**, the container needs to know the host IP to reach it:

```bash
# Gateway IP of the Docker bridge network (usually 172.17.0.1 or similar)
docker network inspect inventari_app-network \
  -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

Use that IP (or `host.docker.internal` on Docker Desktop) as the receiver
URL when creating an endpoint for local testing. A receiver on a private
address is refused by the SSRF guard until you set
`WEBHOOKS_ALLOW_PRIVATE_NETWORKS=true` in `.env` and recreate the backend
(`docker compose up -d backend`) — see *Reaching your own network* in
[WEBHOOKS.md](WEBHOOKS.md).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Cannot connect to backend` | Check `docker compose ps`, port **8005** |
| `Test ping returns success but nothing arrives` | Container can't reach the receiver — use webhook.site (external) or the Docker gateway IP |
| `HTTP 403 on /webhooks/*` | You must be an administrator of the organization, and the Webhooks module must be enabled for it — see Step 2 |
| `HMAC does not match` | Ensure the secret is identical on both sides; use the **raw** body bytes (not re-serialized JSON) |
