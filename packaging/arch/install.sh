#!/usr/bin/env bash
#
# Build the Usage Monitor packages and install the ones this machine needs.
#
# `makepkg -si` cannot do this: it installs every package a split PKGBUILD
# produces, so it would pull gnome-shell onto a Plasma machine and
# plasma-workspace onto a GNOME one. The desktop has to be detected where the
# packages are installed, not where they are built - a .pkg.tar.zst is meant
# to be reproducible and installable anywhere, so the PKGBUILD deliberately
# knows nothing about the running session.
#
# Usage:  ./install.sh [--desktop plasma|gnome|both|none] [--rebuild] [--dry-run] [--yes]

set -euo pipefail

readonly DAEMON_PACKAGE='usage-monitor-for-claude-daemon'
readonly PLASMA_PACKAGE='usage-monitor-for-claude-plasma'
readonly GNOME_PACKAGE='usage-monitor-for-claude-gnome'

# Everything the split produces. Used to decide whether a build is needed -
# makepkg builds all of them or none, so a partial set on disk means the build
# still has to run even when the packages being installed are already there.
readonly ALL_PACKAGES=("$DAEMON_PACKAGE" "$PLASMA_PACKAGE" "$GNOME_PACKAGE")

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

desktop_override=''
rebuild=0
dry_run=0
assume_yes=0

# Results of the detection step. They are globals rather than command
# substitution output because a function called as `x="$(fn)"` runs in a
# subshell, where anything it assigns is discarded when the subshell exits.
detected_frontends=''
detection_source=''

usage() {
    cat >&2 <<'USAGE'
Build the Usage Monitor packages and install the ones this machine needs.

    ./install.sh [options]

Options:
    --desktop VALUE   Skip detection: plasma, gnome, both, or none (daemon only)
    --rebuild         Rebuild even when a package of this version already exists
    --dry-run         Print what would happen without building or installing
    --yes             Do not ask for confirmation before installing
    --help            Show this message

With no options the frontends are chosen from the desktop shells installed on
this machine, so a system with both Plasma and GNOME gets both and keeps
working whichever session you log into. The running session is consulted only
when no packaged desktop shell is found.
USAGE
}

die() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

# Colour only when stdout is a terminal: piped into a log or a pager, the
# escape sequences are noise rather than emphasis.
if [ -t 1 ]; then
    readonly PREFIX=$'\033[1;34m::\033[0m'
else
    readonly PREFIX='::'
fi

info() {
    printf '%s %s\n' "$PREFIX" "$1"
}

parse_arguments() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --desktop)
                [ $# -ge 2 ] || die '--desktop needs a value'
                desktop_override="$2"
                shift 2
                ;;
            --desktop=*)
                desktop_override="${1#*=}"
                shift
                ;;
            --rebuild) rebuild=1; shift ;;
            --dry-run) dry_run=1; shift ;;
            --yes|-y) assume_yes=1; shift ;;
            --help|-h) usage; exit 0 ;;
            *) usage; die "unknown option: $1" ;;
        esac
    done

    case "$desktop_override" in
        ''|plasma|gnome|both|none) ;;
        *) die "--desktop must be one of: plasma, gnome, both, none" ;;
    esac
}

# makepkg refuses to run as root, and it is right to: build scripts run
# arbitrary upstream code. Only the pacman call needs privileges.
require_regular_user() {
    [ "$(id -u)" -ne 0 ] || die 'run this as a regular user - it calls sudo only for the install step'
}

privilege_command() {
    if command -v sudo >/dev/null 2>&1; then
        printf 'sudo'
    elif command -v doas >/dev/null 2>&1; then
        printf 'doas'
    else
        die 'neither sudo nor doas is available to install the packages'
    fi
}

# ---------------------------------------------------------------------------
# Desktop detection
# ---------------------------------------------------------------------------

frontends_from_session() {
    # XDG_CURRENT_DESKTOP is colon-separated and vendor-prefixed on some
    # distributions ("ubuntu:GNOME"), so it is matched as a substring rather
    # than compared. The other two are checked because a session started
    # outside a display manager often sets only one of them.
    local haystack
    haystack="$(printf '%s:%s:%s' \
        "${XDG_CURRENT_DESKTOP:-}" "${XDG_SESSION_DESKTOP:-}" "${DESKTOP_SESSION:-}" \
        | tr '[:lower:]' '[:upper:]')"

    detected_frontends=''
    case "$haystack" in *KDE*|*PLASMA*) detected_frontends='plasma' ;; esac
    case "$haystack" in *GNOME*) detected_frontends="${detected_frontends:+$detected_frontends }gnome" ;; esac

    [ -n "$detected_frontends" ]
}

frontends_from_installed_shells() {
    detected_frontends=''

    if pacman -Qq plasma-workspace >/dev/null 2>&1; then
        detected_frontends='plasma'
    fi
    if pacman -Qq gnome-shell >/dev/null 2>&1; then
        detected_frontends="${detected_frontends:+$detected_frontends }gnome"
    fi

    [ -n "$detected_frontends" ]
}

detect_frontends() {
    # What is installed decides, not what is currently running. A machine with
    # both desktop shells boots into either one, and detecting from the session
    # would install only the frontend for whichever desktop happened to be
    # logged in - leaving the panel empty after the next switch. The unused
    # frontend is inert files the other shell never reads, so installing both
    # costs nothing but a few kilobytes.
    if frontends_from_installed_shells; then
        detection_source='the installed desktop shells'
        return
    fi

    # No packaged desktop shell found: a shell installed outside pacman, or a
    # build host with none at all. Fall back to what the session claims to be.
    if frontends_from_session; then
        detection_source='the running session'
        return
    fi

    detection_source='nothing - no desktop shell found'
    detected_frontends=''
}

resolve_frontends() {
    detection_source='the --desktop option'

    case "$desktop_override" in
        plasma) detected_frontends='plasma' ;;
        gnome)  detected_frontends='gnome' ;;
        both)   detected_frontends='plasma gnome' ;;
        none)   detected_frontends='' ;;
        *)      detect_frontends ;;
    esac
}

# ---------------------------------------------------------------------------
# Package resolution
# ---------------------------------------------------------------------------

# makepkg --packagelist resolves the version and honours PKGDEST, so the built
# files are located without globbing or parsing a version out of a filename.
# It also lists a -debug package that an `any` build never produces, which is
# why each wanted name is matched exactly.
package_path() {
    local wanted="$1" line

    while IFS= read -r line; do
        case "$(basename "$line")" in
            "$wanted"-*) printf '%s' "$line"; return 0 ;;
        esac
    done < <(makepkg --packagelist)

    die "makepkg does not produce a package named $wanted"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    parse_arguments "$@"
    require_regular_user

    cd "$SCRIPT_DIR"
    [ -f PKGBUILD ] || die "no PKGBUILD next to this script ($SCRIPT_DIR)"

    resolve_frontends
    local frontends="$detected_frontends"

    local packages=("$DAEMON_PACKAGE")
    case " $frontends " in
        *" plasma "*) packages+=("$PLASMA_PACKAGE") ;;
    esac
    case " $frontends " in
        *" gnome "*) packages+=("$GNOME_PACKAGE") ;;
    esac

    if [ -n "$frontends" ]; then
        info "Detected from $detection_source: ${frontends// /, }"
    else
        info "Detected from $detection_source"
        info 'No panel frontend will be installed - the daemon runs headless.'
        info "Add one later with: $0 --desktop plasma   (or gnome, or both)"
    fi

    # Resolved before anything happens: --packagelist runs pkgver(), so the
    # paths it prints already carry the version this build would produce.
    local paths=() name
    for name in "${packages[@]}"; do
        paths+=("$(package_path "$name")")
    done

    # The build decision looks at EVERY package the split declares, not just
    # the ones being installed. makepkg builds all of them whenever it runs, so
    # "are all the artifacts present?" is the question that matters - asking
    # only about the selected ones would skip the build on a Plasma machine and
    # leave the GNOME package never built, so adding that desktop later would
    # pay for a full rebuild instead of the promised seconds.
    #
    # It also keeps makepkg from being called once every artifact exists, which
    # it refuses outright ("The package group has already been built").
    local needs_build=0 path
    for name in "${ALL_PACKAGES[@]}"; do
        path="$(package_path "$name")"
        if [ ! -f "$path" ]; then
            needs_build=1
        fi
    done

    printf '\nWill install:\n'
    printf '  - %s\n' "${packages[@]}"
    if [ "$rebuild" -eq 1 ] || [ "$needs_build" -eq 1 ]; then
        printf '\nBuilding first (the PKGBUILD runs the test suite in check()).\n\n'
    else
        printf '\nAlready built for this version - installing without rebuilding.\n\n'
    fi

    if [ "$dry_run" -eq 1 ]; then
        info 'Dry run - nothing was built or installed.'
        return 0
    fi

    if [ "$assume_yes" -eq 0 ]; then
        local reply
        read -r -p 'Proceed? [y/N] ' reply
        case "$reply" in
            [yY]|[yY][eE][sS]) ;;
            *) info 'Aborted.'; return 1 ;;
        esac
    fi

    if [ "$rebuild" -eq 1 ] || [ "$needs_build" -eq 1 ]; then
        local makepkg_flags=(--syncdeps --noconfirm)
        [ "$rebuild" -eq 1 ] && makepkg_flags+=(--force)

        info 'Building...'
        makepkg "${makepkg_flags[@]}"
    fi

    info 'Installing...'
    $(privilege_command) pacman -U "${paths[@]}"

    printf '\n'
    info 'Installed. Start the daemon and have it run at login:'
    cat <<'NEXT'

    mkdir -p ~/.config/autostart
    cp /usr/share/usage-monitor-for-claude/autostart/usage-monitor-for-claude.desktop ~/.config/autostart/
    /usr/bin/usage-monitor-for-claude-daemon &
NEXT

    case " $frontends " in
        *" gnome "*)
            cat <<'GNOME_NEXT'
Then enable the GNOME extension (GNOME never enables one on your behalf):

    gnome-extensions enable usage-monitor-for-claude@cailo.github.com

On Xorg press Alt+F2, type r and press Enter. On Wayland, log out and back in.
GNOME_NEXT
            ;;
    esac

    case " $frontends " in
        *" plasma "*)
            cat <<'PLASMA_NEXT'
The Plasma widget appears in the system tray on its own. If it does not, add it
from System Tray Settings -> Entries.
PLASMA_NEXT
            ;;
    esac
}

main "$@"
