#!/bin/sh
# Install Inventari with one command, on a server with a domain or on a Linux
# computer at home.
#
#   curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/download/install.sh | sh -s -- vps
#   curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/download/install.sh | sh -s -- home
#   curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/download/install.sh | sh -s -- home --local-ca
#
# vps               A server whose domain has an A record pointing at it; Let's
#                   Encrypt issues the certificate (QUICK_DEPLOY.md). It asks for
#                   the domain, the e-mail address for the certificate, and the
#                   administrator's e-mail address and password.
# home              A computer at home, reached through Tailscale: the machine
#                   joins your tailnet and gets a certificate every browser
#                   trusts for its ts.net name, so a phone's camera works with
#                   nothing to install but the Tailscale app
#                   (docs/HOME_INSTALL.md). It asks for the administrator's
#                   e-mail address and password; Tailscale asks you to sign in.
# home --local-ca   The same computer without a Tailscale account: Caddy issues
#                   the certificate from an authority of its own for a name on
#                   the home network, and each device is told once to trust it.
#
# What it does, each step skipped when it is already done: installs Docker
# and git when missing, fetches the release into /opt/inventari (a git
# checkout of its tag, which is what DEPLOYMENT.md's updates move), writes
# .env with scripts/init-env.sh, downloads the release's published images,
# starts everything but the proxy, waits until the backend answers, creates
# the administrator, then starts the proxy, waits until the address answers
# over HTTPS and prints it. The proxy starts last because its certificate is
# published in public logs the moment it is issued, and an installation that
# is reachable before it has an account belongs to whoever registers first.
#
# Run again on a finished installation it changes nothing and says so. After a
# step that failed it continues from that step.
#
# With no terminal to ask on, the answers come from options: --domain and
# --email (vps), --name (home --local-ca), --admin-email, and the password in
# the INVENTARI_ADMIN_PASSWORD environment variable.
#
# INVENTARI_DIR, INVENTARI_REPO and INVENTARI_VERSION replace the directory,
# the repository it clones and the release it installs. That is how a tree is
# tried before its release: a clone that carries the tag, and the images built
# on the machine under their ghcr.io names.
#
# The whole script is functions until the last line: piped into sh, it is read
# to the end before anything runs, so no command it starts can swallow the
# rest of it from standard input.
set -eu

# The release this copy installs. The release workflow
# (.github/workflows/release-installer.yml) writes it in when it attaches the
# script to a published release; a copy taken from the tree names none.
published_release=""

repo_default="https://github.com/InventariLabs/Inventari.git"
guide_vps="https://github.com/InventariLabs/Inventari/blob/main/QUICK_DEPLOY.md"
guide_home="https://github.com/InventariLabs/Inventari/blob/main/docs/HOME_INSTALL.md"
guide_manual="https://github.com/InventariLabs/Inventari/blob/main/DEPLOYMENT.md"

# Docker Compose 2.24.4 is the first that reads the !reset and !override tags
# of docker-compose.images.yml.
compose_needed="2.24.4"

# Seconds each wait gives up after.
backend_wait=900
https_wait=300
tailscale_wait=900

# ASCII ranges in the patterns, whatever the terminal's language: the
# password rule below is the backend's, which is ASCII.
LC_ALL=C
export LC_ALL

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

# fail <what failed> [what to do ...] — stop, saying both, and how to go on.
fail() {
    {
        printf '\nStopped: %s\n' "$1"
        shift
        for line in "$@"; do printf '%s\n' "$line"; done
        printf 'Then run the same command again: it continues from this step.\n'
    } >&2
    exit 1
}

usage() {
    cat >&2 <<'USAGE'
usage: install.sh vps  [--domain <name>] [--email <address>] [--admin-email <address>]
       install.sh home [--admin-email <address>]
       install.sh home --local-ca [--name <name>] [--admin-email <address>]

vps    a server with a domain (QUICK_DEPLOY.md)
home   a Linux computer at home, through Tailscale; --local-ca without it
       (docs/HOME_INSTALL.md)

The password comes from the INVENTARI_ADMIN_PASSWORD environment variable
when there is no terminal to ask for it on.
USAGE
    exit 2
}

parse_args() {
    mode=""
    local_ca=""
    domain=""
    cert_email=""
    admin_email=""
    local_name=""
    while [ $# -gt 0 ]; do
        case "$1" in
            vps|home)
                [ -z "$mode" ] || usage
                mode="$1"
                shift ;;
            --local-ca) local_ca=1; shift ;;
            --domain|--email|--admin-email|--name)
                [ $# -ge 2 ] || { say "$1 needs a value." >&2; exit 2; }
                case "$1" in
                    --domain) domain="$2" ;;
                    --email) cert_email="$2" ;;
                    --admin-email) admin_email="$2" ;;
                    --name) local_name="$2" ;;
                esac
                shift 2 ;;
            -h|--help) usage ;;
            *) say "unknown option: $1" >&2; usage ;;
        esac
    done
    [ -n "$mode" ] || usage
    if [ -n "$local_ca" ] && [ "$mode" != home ]; then
        say "--local-ca belongs to the home install: install.sh home --local-ca" >&2
        exit 2
    fi
    if [ "$mode" = vps ] && [ -n "$local_name" ]; then
        say "--name belongs to home --local-ca; a server takes --domain." >&2
        exit 2
    fi
    if [ "$mode" = home ] && [ -n "$domain$cert_email" ]; then
        say "--domain and --email belong to the vps install." >&2
        exit 2
    fi
}

# ── Questions ───────────────────────────────────────────────────────────────
# Piped into sh, the script's standard input is the script itself, so every
# question is asked on the terminal. Each answer is read as
# `x=$(ask ...) || exit 1`: a failure inside $(...) ends only the subshell, and
# a function called after `||` runs without set -e.

have_tty() { (: </dev/tty) 2>/dev/null; }

# tell <line> — to the person answering: the terminal, or standard error.
tell() {
    if have_tty; then say "$*" >/dev/tty; else say "$*" >&2; fi
}

# ask <prompt> -> the answer on stdout
ask() {
    have_tty || fail "There is no terminal to ask on." \
        "Give the answers as options instead (install.sh --help lists them)."
    printf '%s' "$1" >/dev/tty
    IFS= read -r answer </dev/tty || answer=""
    printf '%s' "$answer"
}

# ask_secret <prompt> -> the answer on stdout, typed without echo
ask_secret() {
    have_tty || fail "There is no terminal to ask for the password on." \
        "Pass it in the INVENTARI_ADMIN_PASSWORD environment variable instead."
    printf '%s' "$1" >/dev/tty
    stty -echo </dev/tty 2>/dev/null || true
    IFS= read -r answer </dev/tty || answer=""
    stty echo </dev/tty 2>/dev/null || true
    printf '\n' >/dev/tty
    printf '%s' "$answer"
}

valid_name() {
    case "$1" in
        ""|*[!A-Za-z0-9.-]*|.*|*.|-*|*..*) return 1 ;;
        *.*) return 0 ;;
        *) return 1 ;;
    esac
}

valid_email() {
    case "$1" in
        ""|*[!A-Za-z0-9._%+@-]*|*@*@*|@*|*@|*@.*|*@*.) return 1 ;;
        *@*.*) return 0 ;;
        *) return 1 ;;
    esac
}

# password_problem <password> -> what it lacks, nothing when it will do. The
# rule create-admin applies (backend/app/schemas/user.py), checked here so a
# password it would refuse is caught before the minutes of downloading.
password_problem() {
    bytes=$(printf '%s' "$1" | wc -c)
    if [ "$bytes" -lt 8 ]; then say "at least 8 characters"; return; fi
    if [ "$bytes" -gt 72 ]; then say "at most 72 bytes"; return; fi
    case "$1" in *[a-z]*) ;; *) say "a lowercase letter"; return ;; esac
    case "$1" in *[A-Z]*) ;; *) say "an uppercase letter"; return ;; esac
    case "$1" in *[0-9]*) ;; *) say "a digit"; return ;; esac
}

ask_domain() {
    while ! valid_name "$domain"; do
        [ -z "$domain" ] || tell "A bare host name, such as inventari.example.com: no https://, no path."
        domain=$(ask "Domain this installation answers on (e.g. inventari.example.com): ") || exit 1
    done
    if command -v getent >/dev/null 2>&1 && ! getent hosts "$domain" >/dev/null 2>&1; then
        fail "$domain does not resolve to an address yet." \
            "Create an A record for it pointing at this server's address, at your domain's registrar, and wait a few minutes for it to spread."
    fi
}

ask_cert_email() {
    while ! valid_email "$cert_email"; do
        [ -z "$cert_email" ] || tell "That does not look like an e-mail address (you@example.com)."
        cert_email=$(ask "E-mail address for the certificate (Let's Encrypt writes there about it): ") || exit 1
    done
}

ask_local_name() {
    if [ -z "$local_name" ]; then
        suggested="$(uname -n | tr '[:upper:]' '[:lower:]').local"
        tell "The name the household's devices will open: one the home router's DNS answers"
        tell "(inventari.home.arpa), or this computer's own .local name, which Android may"
        tell "not find. docs/HOME_INSTALL.md, \"Without Tailscale\", says how to set up either."
        local_name=$(ask "Name [$suggested]: ") || exit 1
        [ -n "$local_name" ] || local_name="$suggested"
    fi
    while :; do
        case "$local_name" in
            *.home.arpa|*.local|*.internal) ! valid_name "$local_name" || break ;;
        esac
        tell "The name must end in .home.arpa, .local or .internal: only those get a certificate from Caddy's own authority."
        local_name=$(ask "Name: ") || exit 1
    done
    domain="$local_name"
}

ask_admin() {
    while ! valid_email "$admin_email"; do
        [ -z "$admin_email" ] || tell "That does not look like an e-mail address (you@example.com)."
        if [ -n "$cert_email" ]; then
            admin_email=$(ask "Administrator's e-mail address [$cert_email]: ") || exit 1
            [ -n "$admin_email" ] || admin_email="$cert_email"
        else
            admin_email=$(ask "Administrator's e-mail address (you sign in with it): ") || exit 1
        fi
    done
    admin_password="${INVENTARI_ADMIN_PASSWORD:-}"
    if [ -n "$admin_password" ]; then
        problem=$(password_problem "$admin_password")
        [ -z "$problem" ] || fail "The password in INVENTARI_ADMIN_PASSWORD needs $problem."
        return 0
    fi
    while :; do
        admin_password=$(ask_secret "Administrator's password (8 or more characters, with a lowercase letter, an uppercase letter and a digit): ") || exit 1
        problem=$(password_problem "$admin_password")
        if [ -n "$problem" ]; then
            tell "The password needs $problem."
            continue
        fi
        again=$(ask_secret "The same password again: ") || exit 1
        [ "$again" != "$admin_password" ] || break
        tell "The two did not match."
    done
}

# ── Privileges and tools ───────────────────────────────────────────────────

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        fail "This step needs root: $*" "Run the command as root, or install sudo."
    fi
}

# Sets docker to the command that reaches the Docker daemon from here, or
# fails. A user who is not in the docker group yet (the group only applies
# from the next login) reaches it through sudo.
find_docker() {
    docker=""
    command -v docker >/dev/null 2>&1 || return 1
    if docker info >/dev/null 2>&1; then
        docker="docker"
    elif [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
        docker="sudo docker"
    else
        return 1
    fi
}

# version_at_least <have> <need>
version_at_least() {
    printf '%s %s\n' "$1" "$2" | awk '{
        split($1, have, "."); split($2, need, ".")
        for (i = 1; i <= 3; i++) {
            if (have[i] + 0 > need[i] + 0) exit 0
            if (have[i] + 0 < need[i] + 0) exit 1
        }
        exit 0
    }'
}

need_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        step "Installing Docker (the script Docker publishes at get.docker.com)"
        curl -fsSL https://get.docker.com -o "$tmp/get-docker.sh" \
            || fail "Docker's install script could not be downloaded." "Check this machine's connection to get.docker.com."
        as_root sh "$tmp/get-docker.sh" \
            || fail "Docker could not be installed (its installer's messages are above)." \
                "Install it by hand with: curl -fsSL https://get.docker.com | sudo sh"
    fi
    find_docker || fail "Docker is installed, but its service does not answer." \
        "Start it with: sudo systemctl enable --now docker"
    have=$($docker compose version --short 2>/dev/null | sed 's/^v//; s/[^0-9.].*//')
    [ -n "$have" ] || fail "Docker Compose v2 is missing." \
        "Install it with Docker's own packages: curl -fsSL https://get.docker.com | sudo sh"
    version_at_least "$have" "$compose_needed" \
        || fail "Docker Compose $have is older than $compose_needed, which this installation needs." \
            "Update Docker with: curl -fsSL https://get.docker.com | sudo sh"
    # Reached through sudo: the guides' later `docker compose` commands run
    # without it once the user is in the docker group, from the next login.
    if [ "$docker" = "sudo docker" ]; then
        as_root usermod -aG docker "$(id -un)"
        joined_docker_group=1
    fi
}

need_git() {
    command -v git >/dev/null 2>&1 && return 0
    step "Installing git"
    if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update -qq && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git
    elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y -q git
    else
        false
    fi || fail "git could not be installed." "Install it with this system's package manager."
}

# ── Tailscale ──────────────────────────────────────────────────────────────

# tailscale_field <key> -> the first string of that key in `tailscale status
# --json`. BackendState and CertDomains are top-level keys that occur once.
tailscale_field() {
    tailscale status --json 2>/dev/null | tr -d '\n\r\t ' \
        | sed -n "s/.*\"$1\":\[\{0,1\}\"\([^\"]*\)\".*/\1/p"
}

need_tailscale() {
    if ! command -v tailscale >/dev/null 2>&1; then
        step "Installing Tailscale (the script Tailscale publishes at tailscale.com/install.sh)"
        curl -fsSL https://tailscale.com/install.sh -o "$tmp/tailscale.sh" \
            || fail "Tailscale's install script could not be downloaded." "Check this machine's connection to tailscale.com."
        as_root sh "$tmp/tailscale.sh" \
            || fail "Tailscale could not be installed (its installer's messages are above)." \
                "Install it by hand: https://tailscale.com/download/linux"
    fi
    if [ "$(tailscale_field BackendState)" != Running ]; then
        step "Signing this computer in to Tailscale"
        say "Open the address Tailscale prints below in any browser and sign in, or create a free account."
        say "The phones that will use Inventari sign in to the same account later."
        as_root tailscale up \
            || fail "The Tailscale sign-in did not finish." "Check that Tailscale's service runs: sudo systemctl status tailscaled"
    fi
    domain=$(tailscale_field CertDomains)
    if [ -z "$domain" ]; then
        step "Turning on HTTPS for your tailnet"
        say "Tailscale issues the certificate only once HTTPS is on for your tailnet. In a browser:"
        say "  1. open https://login.tailscale.com/admin/dns"
        say "  2. under MagicDNS, press Enable MagicDNS if it is not on yet"
        say "  3. under HTTPS Certificates, press Enable HTTPS"
        say "Waiting for it to be on (this continues by itself)..."
        waited=0
        while domain=$(tailscale_field CertDomains); [ -z "$domain" ]; do
            [ "$waited" -lt "$tailscale_wait" ] \
                || fail "HTTPS is still off for your tailnet." "Turn it on at https://login.tailscale.com/admin/dns (MagicDNS and HTTPS Certificates)."
            sleep 5
            waited=$((waited + 5))
        done
    fi
    valid_name "$domain" || fail "Tailscale names this computer '$domain', which is not a host name the installation can use."
    say "This computer is $domain on your tailnet."
}

# ── The installation ───────────────────────────────────────────────────────

dc() { (cd "$dir" && $docker compose "$@"); }

env_value() { sed -n "s/^$1=//p" "$dir/.env" | tail -n 1; }

# The route an installation took, from the name it answers on.
route_of() {
    case "$1" in
        *.ts.net) say tailscale ;;
        *.home.arpa|*.local|*.internal) say local-ca ;;
        *) say vps ;;
    esac
}

caddy_running() { dc ps --status running --services 2>/dev/null | grep -qx caddy; }

https_answers() {
    if [ "$route" = local-ca ]; then
        [ -f "$dir/inventari-root.crt" ] || return 1
        curl -sf -o /dev/null --max-time 10 --cacert "$dir/inventari-root.crt" \
            --resolve "$domain:443:127.0.0.1" "https://$domain/"
    else
        curl -sf -o /dev/null --max-time 10 --resolve "$domain:443:127.0.0.1" "https://$domain/"
    fi
}

fetch_release() {
    if [ -d "$dir/.git" ]; then
        say "$dir already holds the files of a release; they stay as they are."
        return 0
    fi
    step "Fetching Inventari $version into $dir"
    if [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
        fail "$dir exists, is not empty and holds no installation." \
            "Move it away, or empty it, if nothing in it is needed."
    fi
    if ! mkdir -p "$dir" 2>/dev/null || [ ! -w "$dir" ]; then
        as_root mkdir -p "$dir"
        as_root chown "$(id -u):$(id -g)" "$dir"
    fi
    git -c advice.detachedHead=false clone --quiet --branch "v$version" "$repo" "$dir" \
        || fail "Release $version could not be fetched from $repo." "Check this machine's connection to github.com."
    [ -f "$dir/scripts/init-env.sh" ] && [ -f "$dir/docker-compose.images.yml" ] \
        || fail "Release $version predates this installer: it has no scripts/init-env.sh to write .env with." \
            "Install a newer release, or follow $guide_manual by hand."
}

write_env() {
    if [ -f "$dir/.env" ]; then
        say "$dir/.env is there already; it stays as it is."
        return 0
    fi
    step "Writing $dir/.env"
    sh "$dir/scripts/init-env.sh" --domain "$domain" --email "$cert_email" \
        || fail "scripts/init-env.sh could not write .env (its message is above)."
    files="docker-compose.prod.yml:docker-compose.images.yml"
    [ "$route" != tailscale ] || files="$files:docker-compose.tailscale.yml"
    {
        printf '\n# The files that make this installation (written by scripts/install.sh):\n'
        printf '# the release'\''s published images, so every docker compose command runs\n'
        printf '# here without -f.\n'
        printf 'COMPOSE_FILE=%s\n' "$files"
    } >>"$dir/.env"
}

pull_images() {
    step "Downloading the images (the first time, a few minutes)"
    dc pull && return 0
    # A machine that already holds every image (a run after a lost connection,
    # or a release tried before its images are published) goes on with them.
    images=$(dc config --images) || fail "docker compose cannot read the installation's files (its message is above)."
    for image in $images; do
        $docker image inspect "$image" >/dev/null 2>&1 \
            || fail "The images could not be downloaded (Docker's message is above)." \
                "Check this machine's connection. A release's images are published within an hour of its tag; a release that new may not have them yet."
    done
    say "Using the images already on this machine."
}

start_without_proxy() {
    step "Starting everything but the proxy"
    dc up -d --pull never --scale caddy=0 \
        || fail "The services could not be started (Docker's message is above)." "This shows their state: cd $dir && $docker compose ps"
}

wait_for_backend() {
    step "Waiting for the backend (the first start sets up the database: about a minute)"
    waited=0
    until dc exec -T backend curl -sf http://localhost:8000/health/ready >/dev/null 2>&1; do
        [ "$waited" -lt "$backend_wait" ] \
            || fail "The backend did not answer within $((backend_wait / 60)) minutes." "Its log says why: cd $dir && $docker compose logs backend"
        sleep 5
        waited=$((waited + 5))
    done
}

create_admin() {
    step "Creating the administrator"
    status=$(dc exec -T backend curl -sf http://localhost:8000/api/v1/auth/init-status) \
        || fail "The backend did not say whether an account exists." "Its log says why: cd $dir && $docker compose logs backend"
    case "$status" in
        *'"is_initialized":true'*)
            say "The installation has an account already; none is created."
            return 0 ;;
    esac
    if [ -z "${admin_password:-}" ]; then
        ask_admin
    fi
    # The password goes in on standard input, never on a command line: sudo
    # logs the commands it runs, arguments included, and a command line is
    # readable by every user of the machine while it runs.
    printf '%s\n' "$admin_password" | dc exec -T backend sh -c \
        'IFS= read -r password && exec python manage.py user create-admin --email "$1" --password "$password"' \
        create-admin "$admin_email" \
        || fail "The administrator could not be created (the reason is above)."
}

start_proxy() {
    step "Starting the proxy"
    dc up -d --pull never \
        || fail "The proxy could not be started (Docker's message is above)." \
            "Ports 80 and 443 must be free; this shows who holds them: sudo ss -ltnp 'sport = :80 or sport = :443'"
}

copy_root_certificate() {
    waited=0
    until dc cp caddy:/data/caddy/pki/authorities/local/root.crt "$dir/inventari-root.crt" >/dev/null 2>&1; do
        [ "$waited" -lt 60 ] || fail "Caddy has not made its certificate authority." "Its log says why: cd $dir && $docker compose logs caddy"
        sleep 2
        waited=$((waited + 2))
    done
    # Copied through sudo, the file is root's; the reader shares it from here.
    [ -w "$dir/inventari-root.crt" ] || as_root chown "$(id -u):$(id -g)" "$dir/inventari-root.crt"
}

wait_for_https() {
    case "$route" in
        vps) step "Waiting for the certificate from Let's Encrypt (a minute or two)" ;;
        tailscale) step "Waiting for the certificate from Tailscale" ;;
        local-ca) step "Waiting for the certificate from Caddy's own authority"; copy_root_certificate ;;
    esac
    waited=0
    until https_answers; do
        if [ "$waited" -ge "$https_wait" ]; then
            if [ "$route" = vps ]; then
                fail "https://$domain does not answer yet." \
                    "Caddy's log says why: cd $dir && $docker compose logs caddy" \
                    "Most often the A record of $domain points elsewhere, or a firewall closes ports 80 and 443 (sudo ufw allow 80,443/tcp, and the provider's own firewall)."
            fi
            fail "https://$domain does not answer yet." \
                "Caddy's log says why: cd $dir && $docker compose logs caddy"
        fi
        sleep 5
        waited=$((waited + 5))
    done
}

# ── What the reader is told ────────────────────────────────────────────────

closing() {
    who="${admin_email:-the administrator}"
    printf '\nInventari %s is running at\n\n    https://%s\n\n' "$(env_value INVENTARI_VERSION)" "$domain"
    case "$route" in
        vps)
            say "Open it and sign in as $who: the first screens ask what the"
            say "installation is for and name the organization." ;;
        tailscale)
            say "It answers on the devices of your tailnet, at home and away. On each phone"
            say "or computer: install Tailscale (App Store, Google Play, tailscale.com/download),"
            say "sign in with the account you just used, then open the address and sign in"
            say "as $who." ;;
        local-ca)
            say "Each device needs two things before it opens the address: the name must"
            say "lead to this computer (the router's DNS, or mDNS for a .local name), and"
            say "the device must trust $dir/inventari-root.crt, the certificate"
            say "of Caddy's authority. Both are in $guide_home"
            say "under \"Without Tailscale\". Then sign in as $who." ;;
    esac
    say ""
    say "Keep a copy of $dir/.env off this machine, in your password manager:"
    say "no backup holds it, and a restored database needs its keys."
    say "Every later command runs in $dir as \`docker compose ...\`."
    if [ -n "${joined_docker_group:-}" ]; then
        say "You are now in the docker group: log out and back in before running them without sudo."
    fi
}

report_installed() {
    installed=$(env_value INVENTARI_VERSION)
    if https_answers; then
        say "Inventari $installed is installed in $dir and answers at https://$domain."
        say "Nothing was changed."
        if [ -n "$version" ] && [ "$version" != "$installed" ]; then
            say "This installer is for $version; an update follows \"Updating\" in $guide_manual"
        fi
        return 0
    fi
    say "Inventari $installed is installed in $dir and its proxy runs, but https://$domain"
    say "does not answer from this machine. Nothing was changed."
    say "Caddy's log says why: cd $dir && $docker compose logs caddy"
    return 1
}

main() {
    parse_args "$@"
    [ "$(uname -s)" = Linux ] \
        || fail "This installer runs on Linux only; macOS and Windows are untested." "$guide_manual describes the installation by hand."
    case "$(uname -m)" in
        x86_64|amd64|aarch64|arm64) ;;
        *) fail "The published images are for amd64 and arm64, and this machine is $(uname -m)." \
            "$guide_manual builds the images from source." ;;
    esac

    dir="${INVENTARI_DIR:-/opt/inventari}"
    repo="${INVENTARI_REPO:-$repo_default}"
    version="${INVENTARI_VERSION:-$published_release}"
    tmp=$(mktemp -d)
    trap 'stty echo </dev/tty 2>/dev/null || true; rm -rf "$tmp"' EXIT
    trap 'exit 130' INT TERM

    if [ -f "$dir/.env" ]; then
        domain=$(env_value DOMAIN)
        route=$(route_of "$domain")
        if find_docker && caddy_running; then
            report_installed
            return
        fi
        say "The installation in $dir (https://$domain) stopped before it finished; it continues."
    else
        case "$version" in
            ""|*[!0-9A-Za-z.-]*) fail "This copy of the installer names no release to install." \
                "Use the one each release publishes: $guide_vps" ;;
        esac
        if [ "$mode" = vps ]; then
            route=vps
            ask_domain
            ask_cert_email
        elif [ -n "$local_ca" ]; then
            route=local-ca
            ask_local_name
        else
            route=tailscale
        fi
        ask_admin
        # Caddy cannot start on a port another program holds, and by then the
        # administrator exists and half the stack runs.
        if command -v ss >/dev/null 2>&1 && [ -n "$(ss -Hltn 'sport = :80 or sport = :443' 2>/dev/null)" ]; then
            fail "Ports 80 and 443 must be free for the proxy, and a program holds one of them." \
                "This shows which: sudo ss -ltnp 'sport = :80 or sport = :443'"
        fi
        [ -n "$cert_email" ] || cert_email="$admin_email"
    fi

    need_docker
    need_git
    if [ "$route" = tailscale ] && [ ! -f "$dir/.env" ]; then
        need_tailscale
    fi
    fetch_release
    write_env
    pull_images
    start_without_proxy
    wait_for_backend
    create_admin
    start_proxy
    wait_for_https
    closing
}

main "$@"
