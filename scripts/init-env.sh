#!/bin/sh
# scripts/init-env.sh — write the production .env: every secret generated.
#
#   ./scripts/init-env.sh [--domain inventari.example.com] [--email you@example.com]
#
# It asks for the two things only the installer knows — the domain the
# installation answers on and the e-mail address Let's Encrypt writes to — and
# fills the rest of .env.production.example: the five hex secrets
# (DB_PASSWORD, DB_APP_PASSWORD, REDIS_PASSWORD, SECRET_KEY, FERNET_SALT) and
# ENCRYPTION_KEY. Hex, because two of them are interpolated into connection
# URLs verbatim, where base64's + / = would corrupt them.
#
# It also appends INVENTARI_VERSION, the version of the files it was run in,
# which docker-compose.images.yml reads to name the release whose images to
# pull; an installation that builds from source ignores it.
#
# It never overwrites an existing .env: replacing FERNET_SALT or ENCRYPTION_KEY
# leaves every secret already stored unreadable for good. Nothing but sh, awk
# and the kernel's random source is needed, so it runs on a server that has no
# make and no openssl.
set -eu

here="$(cd "$(dirname "$0")/.." && pwd)"
example="$here/.env.production.example"
target="$here/.env"

domain=""
email=""
while [ $# -gt 0 ]; do
    case "$1" in
        --domain|--email)
            # Under dash a failed `shift 2` ends the shell before any `|| shift`
            # runs, so the missing value is checked for instead.
            [ $# -ge 2 ] || { echo "$1 needs a value." >&2; exit 2; }
            if [ "$1" = "--domain" ]; then domain="$2"; else email="$2"; fi
            shift 2 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -e "$target" ]; then
    echo "$target already exists, and a new one would replace secrets that may already protect stored data." >&2
    echo "Edit it by hand, or move it away first if you mean to start over." >&2
    exit 1
fi
[ -f "$example" ] || { echo "$example is missing: run this from a release's files." >&2; exit 1; }

ask() { # ask <prompt> -> the answer, or failure at end of input
    printf '%s' "$1" >&2
    IFS= read -r answer || return 1
    printf '%s' "$answer"
}

[ -n "$domain" ] || domain="$(ask 'Domain this installation answers on (e.g. inventari.example.com): ')" || domain=""
[ -n "$email" ] || email="$(ask 'E-mail address for the certificate (Let'\''s Encrypt notices): ')" || email=""

case "$domain" in
    ""|*[!A-Za-z0-9.-]*|.*|*.|-*) echo "The domain must be a bare host name such as inventari.example.com (no https://, no path)." >&2; exit 1 ;;
esac
bad_email() { echo "The e-mail address must look like you@example.com." >&2; exit 1; }
case "$email" in
    ""|*[!A-Za-z0-9._%+@-]*|*@*@*|@*|*@|*@.*|*@*.) bad_email ;;
    *@*.*) ;;
    *) bad_email ;;
esac

secret() { head -c 32 /dev/urandom | od -An -vtx1 | tr -d ' \n'; }

version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$here/backend/pyproject.toml" 2>/dev/null | head -n 1)"

# umask first: the file must never exist with wider rights than 0600, not even
# for the moment between its creation and a chmod.
umask 077
# noclobber makes the write itself the check: a file that appeared after the one
# at the top is refused by the shell instead of truncated.
set -C
DOMAIN="$domain" ACME_EMAIL="$email" INVENTARI_VERSION="$version"
DB_PASSWORD="$(secret)" DB_APP_PASSWORD="$(secret)" REDIS_PASSWORD="$(secret)"
SECRET_KEY="$(secret)" FERNET_SALT="$(secret)" ENCRYPTION_KEY="$(secret)"
export DOMAIN ACME_EMAIL INVENTARI_VERSION DB_PASSWORD DB_APP_PASSWORD REDIS_PASSWORD SECRET_KEY FERNET_SALT ENCRYPTION_KEY
awk '
    BEGIN {
        n = split("DOMAIN ACME_EMAIL DB_PASSWORD DB_APP_PASSWORD REDIS_PASSWORD SECRET_KEY FERNET_SALT ENCRYPTION_KEY", names, " ")
        for (i = 1; i <= n; i++) fill[names[i]] = ENVIRON[names[i]]
    }
    {
        eq = index($0, "=")
        key = eq ? substr($0, 1, eq - 1) : ""
        if (key in fill && substr($0, eq + 1) == "") print key "=" fill[key]
        else print
    }
    END {
        print ""
        print "# The release whose images docker-compose.images.yml pulls (written by"
        print "# scripts/init-env.sh; an installation that builds from source ignores it)."
        print "INVENTARI_VERSION=" ENVIRON["INVENTARI_VERSION"]
    }
' "$example" > "$target" || {
    echo "$target appeared while this ran; it was left as it is." >&2
    exit 1
}
set +C

cat >&2 <<MSG
Wrote $target (mode 600): domain, e-mail and six generated secrets.

Keep a copy of it off this server, in your password manager. No backup holds
it, and without its ENCRYPTION_KEY and FERNET_SALT a restored database cannot
read the secrets organizations stored in it.
MSG
