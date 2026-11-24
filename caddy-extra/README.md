# caddy-extra

Caddy configuration that belongs to this installation and not to every one,
for example a website served on the main domain while the application runs on
a subdomain. The production stack mounts this directory read-only at
`/etc/caddy/extra`, and the Caddyfile imports every `*.caddy` file in it.

It ships empty. Put a file named `<something>.caddy` here — in this directory
of the checkout, next to `docker-compose.prod.yml`, or in the one
`CADDY_EXTRA_DIR` names — then
`docker compose -f docker-compose.prod.yml up -d caddy` (the first time, for the
mount) or `... exec -T caddy caddy reload --config /etc/caddy/Caddyfile` (after
changing a file). Set `CADDY_EXTRA_DIR` in `.env` to keep the files somewhere
else.

The Caddy container sees only this directory, as `/etc/caddy/extra`. A site's
own files therefore go inside it — `root * /etc/caddy/extra/site` serves
`caddy-extra/site/` — or the block uses `reverse_proxy` to a container on a
network Caddy joins; a path of the host such as `/var/www/site` serves nothing.
Git ignores everything here but this file, so the directory belongs in the
installation's backup (DEPLOYMENT.md, *What the nightly backup does not
cover*).

A site block here must not repeat an address the Caddyfile already serves
(`DOMAIN`, `WWW_DOMAIN`, `DEMO_DOMAIN`): Caddy refuses to start with the same
address twice.
