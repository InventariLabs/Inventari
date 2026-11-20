# caddy-extra

Caddy configuration that belongs to this installation and not to every one,
for example a website served on the main domain while the application runs on
a subdomain. The production stack mounts this directory read-only at
`/etc/caddy/extra`, and the Caddyfile imports every `*.caddy` file in it.

It ships empty. Put a file here, then
`docker compose -f docker-compose.prod.yml up -d caddy` (the first time, for the
mount) or `... exec -T caddy caddy reload --config /etc/caddy/Caddyfile` (after
changing a file). Set `CADDY_EXTRA_DIR` in `.env` to keep the files somewhere
else.

A site block here must not repeat an address the Caddyfile already serves
(`DOMAIN`, `WWW_DOMAIN`, `DEMO_DOMAIN`): Caddy refuses to start with the same
address twice.
