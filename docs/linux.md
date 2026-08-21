# Linux (KDE Plasma and GNOME)

The Linux build splits the application in two: a headless daemon that does all the work, and a
panel frontend that only draws. There are two frontends - a Plasma applet and a GNOME Shell
extension - and they are interchangeable surfaces over the same daemon.

## Why a panel frontend instead of a tray application

Under Wayland a client window cannot place itself, and `QSystemTrayIcon.geometry()` reports nothing
usable over StatusNotifierItem. A stand-alone application therefore *cannot* anchor its popup to
its own tray icon the way the Windows build does. GNOME is stricter still: the shell has had no
system tray since 3.26, so a tray application has nowhere to appear at all.

Code running inside the shell can do both: the panel knows where the widget is and renders the
popup anchored to it, with the desktop's own theme, animation and click-outside dismissal handled
for free. So the frontends live inside `plasmashell` and `gnome-shell`, and everything that is not
drawing stays in Python.

That split has a second benefit. The daemon keeps the OAuth token, so no credential ever enters the
desktop shell process.

## Architecture

```
usage_monitor_for_claude/   shared core + Windows UI (upstream package, reused unchanged)
usage_monitor_linux/        daemon: polling, alerts, event commands, D-Bus service
frontends/plasma/           plasmoid: panel icon and popup (QML)
frontends/gnome/            shell extension: panel icon and menu (GJS)
```

Despite its name, `usage_monitor_for_claude/` is not "the Windows package". It is the shared core
*and* the Windows UI in one directory. The core - `api.py`, `cache.py`, `settings.py`, `i18n.py`,
`formatting.py`, `command.py`, `claude_cli.py`, `anthropic_status.py` - carries the whole
application: reading credentials, talking to the API, poll scheduling and reset alignment,
threshold alerts, label formatting and translation. None of it is tied to Windows. What is tied to
Windows sits next to it and is imported by the Windows entry point only: `app.py`, `tray_icon.py`,
`popup.py`, `notification_identity.py`, `autostart.py`, `idle.py`, `single_instance.py`,
`verbose.py` and `__main__.py`.

`usage_monitor_linux/` reimplements exactly the pieces that have no Windows equivalent - `idle.py`,
`autostart.py`, `single_instance.py`, `notify.py` - and adds what only the daemon needs:
`service.py` (D-Bus), `snapshot.py` (payload) and `cli.py` (entry points). Everything else it
imports; `daemon.py` opens with `UsageCache`, `read_access_token`, `parse_field_name`, `T` and the
settings helpers pulled straight from the core.

The dependency runs one way only: **linux -> core, never core -> linux**. Duplicating the core
instead would leave two copies of `api.py` and `cache.py` drifting apart, and a project whose whole
pitch is "read the code and see it is safe" cannot afford two credential paths to audit.

That rule is also why `platform_support.py` lives in the core rather than here. It is the one file
allowed to branch on platform, and its callers - `settings.py`, `i18n.py`, `command.py`,
`claude_cli.py` - are core modules. Placing it in `usage_monitor_linux/` would make the core import
the Linux package and invert the dependency.

The package is named `usage_monitor_linux` rather than being a `usage_monitor_for_claude.linux`
subpackage on purpose: this repository is a fork that only ever *adds* files, so the diff against
upstream stays readable, and a directory inside the upstream package would be swept into the
Windows PyInstaller build by the spec file.

The daemon publishes on the session bus as `com.github.cailo.UsageMonitor`:

| Member | Signature | Purpose |
|---|---|---|
| `GetSnapshot` | `-> s` | Current snapshot as JSON |
| `Refresh` | `-> b` | Request an out-of-band poll; `false` when declined |
| `RunEventTest` | `s -> b` | Run one configured event command; `false` when none is set |
| `SetAutostart` | `b -> b` | Toggle starting with the session; returns the resulting state |
| `Quit` | | Shut the daemon down |
| `SnapshotChanged` | `s` | Emitted with the new JSON whenever data changes |

The payload is **fully formatted and translated**. Labels, percentages, reset texts, divider
positions and the time marker are all computed in Python, so neither frontend reimplements a
formatting rule and the 13 locale files stay the only source of translations. `tests/test_gnome_frontend.py`
compares the interface the GNOME extension declares against the daemon's own decorators, so a
method added on one side cannot quietly go missing on the other.

Which of those files is loaded follows the gettext precedence rather than `locale.getlocale()`:
`LANGUAGE` first, then `LC_ALL`, `LC_MESSAGES` and `LANG`. KDE Plasma and GNOME keep the
interface language and the regional formats apart - Plasma writes them to `[Translations]` and
`[Formats]` in `~/.config/plasma-localerc` - so an English desktop used in Argentina runs with
`LANGUAGE=en_US` next to `LANG=es_AR.UTF-8`. Reading only the formats would render the widget in
Spanish on an English desktop. A language with no locale file falls back to English, and the
`language` setting still overrides the whole lookup. The detection lives in
`platform_support.desktop_ui_language()`; on Windows it reports nothing and the original
`locale.getlocale()` path is used unchanged.

### How each frontend reads the snapshot

The two differ only here, and only because their languages do.

QML has no D-Bus binding, so the **Plasma applet** reads the snapshot by running
`usage-monitor-for-claude-client --snapshot` through Plasma's `executable` data engine. It does not
poll on a cadence of its own: each snapshot carries `next_poll_time`, so the widget schedules its
next read for just after the daemon's next API poll - roughly one short-lived client process per
poll.

GJS does have one, so the **GNOME extension** talks to the daemon directly through
`Gio.DBusProxy` and subscribes to `SnapshotChanged`. Data arrives when the daemon has it instead of
being polled for, which removes the client process entirely; `next_poll_time` is then only used to
tick the popup's countdown. Every call uses the async form - a synchronous D-Bus round trip from an
extension blocks the compositor's main loop and freezes the whole desktop while the daemon answers.

The extension watches the bus name rather than binding the proxy once, so stopping and restarting
the daemon - which its own menu offers - reconnects instead of leaving a dead indicator behind.

## Install

```sh
cd packaging/arch
./install.sh
```

The script builds, then installs the daemon plus a frontend for **every desktop shell installed on
this machine** - so a system carrying both Plasma and GNOME gets both frontends and keeps working
whichever session you log into. The frontend for the desktop you are not in is inert: files the
other shell never reads.

Detection goes by what is installed rather than by `XDG_CURRENT_DESKTOP` for exactly that reason.
Reading the running session would install one frontend and leave the panel empty after the next
switch. The session is consulted only when no packaged desktop shell is found at all.

`--dry-run` shows what it would do, `--desktop plasma|gnome|both|none` skips detection, and
`--help` lists the rest.

### Adding a desktop later

Install the second desktop, then run the script again:

```sh
./install.sh
```

It costs seconds, not a rebuild. A split PKGBUILD always produces *every* package it declares - the
first run already built the frontend you did not install - so the script finds the artifact on disk,
skips `makepkg` entirely and hands the new package straight to pacman. `--rebuild` forces a real
rebuild when you actually want one.

Three packages are produced:

- `usage-monitor-for-claude-daemon` - the daemon, client, systemd unit, `.desktop` and icon
- `usage-monitor-for-claude-plasma` - the Plasma panel widget
- `usage-monitor-for-claude-gnome` - the GNOME Shell extension

### Why a script and not `makepkg -si`

`makepkg -si` installs **every** package a split PKGBUILD produces, so it would pull
`plasma-workspace` onto a GNOME machine and `gnome-shell` onto a Plasma one - the exact thing the
split exists to avoid. Only a selective `pacman -U` gets that right.

The detection cannot move into the PKGBUILD either. `package()` runs on the machine doing the
*build*, while the question that matters is what the machine doing the *install* runs. Baking the
builder's desktop into a `.pkg.tar.zst` would make it unreproducible and wrong the moment it is
copied to another machine - so the PKGBUILD stays environment-blind, and install.sh does the
detection at the only point where the answer is meaningful.

Prefer to do it by hand? Build without installing and pick:

```sh
makepkg -s
sudo pacman -U usage-monitor-for-claude-daemon-*.pkg.tar.zst \
                usage-monitor-for-claude-plasma-*.pkg.tar.zst
```

Then start the daemon so it runs at login:

```sh
mkdir -p ~/.config/autostart
cp /usr/share/usage-monitor-for-claude/autostart/usage-monitor-for-claude.desktop ~/.config/autostart/
/usr/bin/usage-monitor-for-claude-daemon &
```

### Autostart: why XDG and not systemd

The package also ships a systemd user unit, but **XDG autostart is the mechanism to use** unless
your session is systemd-managed.

The daemon has to sit on the *same* session bus as the panel, the notification server and the
screen locker. A session started the classic way - the default for Plasma on Arch - runs a
`dbus-launch` bus under `/tmp/dbus-*`, while `systemd --user` services get the standard
`$XDG_RUNTIME_DIR/bus`. Those are two different buses: a daemon started by systemd would come up
healthy, own its name on the wrong bus, and stay invisible to the widget.

You can tell which case you are in:

```sh
systemctl --user is-active graphical-session.target
```

`active` means the session is systemd-managed and the unit is the better option
(`systemctl --user enable --now usage-monitor-for-claude`), because it adds restart-on-failure and
journal integration. `inactive` means XDG autostart is the only mechanism that reaches the right
bus.

### Enabling the frontend

**Plasma.** The widget declares itself a notification-area item, so Plasma offers it in the system
tray automatically. If it does not appear, add it from *System Tray Settings → Entries*.

**GNOME.** The extension is installed system-wide but starts disabled, because GNOME never enables
an extension on the user's behalf:

```sh
gnome-extensions enable usage-monitor-for-claude@cailo.github.com
```

On Xorg press `Alt+F2`, type `r` and press Enter to reload the shell. On Wayland the shell cannot
be reloaded in place - log out and back in. If the indicator does not appear, `gnome-extensions
info usage-monitor-for-claude@cailo.github.com` reports the state, and `journalctl --user -f -o cat
/usr/bin/gnome-shell` shows anything the extension logged while loading.

## Panel menu

The panel icon offers the same actions as the Windows tray menu: toggle **Start with session**, run
any configured event command as a test, restart or quit the daemon, and open the project page. Test
entries for an event with no command configured are hidden rather than greyed out.

The two desktops arrange them differently, because their panels work differently. Plasma has two
surfaces - the popup on left click and a context menu on right click - so the actions live in the
context menu. A GNOME panel button has a single menu, so the detail sections and the actions share
it, separated by a rule, and the event tests are grouped into a submenu to keep it short. GNOME has
no equivalent of the Plasma tooltip either: the same information is one click away in the menu.

The Windows build runs `on_double_click_command` on a double click. Neither panel can claim that
gesture without delaying every single click, so on both it moves to the **middle button**.

## Configuration

Identical to Windows, through `usage-monitor-settings.json`. The Linux build adds one search
location: `$XDG_CONFIG_HOME/usage-monitor-for-claude/`. See [configuration.md](configuration.md).

## Differences from the Windows build

| Behavior | Windows | Linux |
|---|---|---|
| Popup anchoring | Win32 positioning | Anchored by the shell's own panel |
| Autostart | `HKCU\...\Run` | `~/.config/autostart/` (or a systemd user unit) |
| Single instance | Named mutex + shared memory | D-Bus name ownership |
| Notification icon | AppUserModelID registration | `desktop-entry` hint |
| Idle detection | `GetLastInputInfo` | Desktop-dependent (see below) |
| Multiple accounts | One instance per `--config-dir` | Daemon only; the frontends show the default instance |

### Idle detection

`idle.py` asks `org.gnome.Mutter.IdleMonitor` for the real idle time and falls back to lock
detection through `org.freedesktop.ScreenSaver`, which both KWin and GNOME Shell implement. What
that yields depends on the desktop:

- **GNOME** answers the idle query, so `idle_pause` behaves as it does on Windows: polling pauses
  once you actually stop typing.
- **Plasma on Wayland** has no public idle API - the information lives in the compositor behind
  `ext-idle-notify-v1`, which is not reachable over D-Bus. `idle_pause` degrades to pausing when
  the session **locks**.

## Development

```sh
# Run the daemon from the checkout
python -m usage_monitor_linux

# Inspect the service
busctl --user introspect com.github.cailo.UsageMonitor /com/github/cailo/UsageMonitor
busctl --user monitor --match "type='signal',interface='com.github.cailo.UsageMonitor'"

# Iterate on the Plasma widget without restarting plasmashell
kpackagetool6 -t Plasma/Applet -i ./frontends/plasma
plasmoidviewer -a org.kde.usagemonitorforclaude
```

A widget installed with `kpackagetool6` lands in `~/.local/share/plasma/plasmoids/` and **shadows**
the packaged one. Remove it before relying on the package:

```sh
kpackagetool6 -t Plasma/Applet -r org.kde.usagemonitorforclaude
```

### GNOME extension

```sh
# Install the checkout for the current user
uuid=usage-monitor-for-claude@cailo.github.com
mkdir -p ~/.local/share/gnome-shell/extensions/$uuid
cp frontends/gnome/* ~/.local/share/gnome-shell/extensions/$uuid/
gnome-extensions enable $uuid

# Watch what the extension logs
journalctl --user -f -o cat /usr/bin/gnome-shell
```

The same shadowing rule applies: `~/.local/share/gnome-shell/extensions/` wins over
`/usr/share/gnome-shell/extensions/`, so remove the local copy before testing the package.

There is no `plasmoidviewer` equivalent - a GNOME extension only runs inside a live shell. On Xorg,
`Alt+F2` → `r` reloads it in seconds; on Wayland every change needs a fresh session, so a nested
shell (`dbus-run-session -- gnome-shell --nested --wayland`) is the faster loop.

### What is verified, and what is not

Three levels, and it is worth knowing which one a given part of the extension sits at.

**Contract-verified.** `tests/test_gnome_frontend.py` compares the D-Bus interface the extension
declares against the daemon's own decorators, checks the manifest, and checks every
`labels`/`events` key the extension reads against the keys `build_snapshot()` produces. It also
holds a set of compatibility guards: no `Clutter.Color` (removed in 47), no `vertical:` construct
property (deprecated in 48), colour reading only through `color.js`, and a `$dispose()` for every
Cairo context.

**Executed.** `tests/test_gnome_js.py` runs the modules that have no `gi://` import under plain
Node, importing the real source file rather than a copy - the same trick `tests/test_popup_js.py`
uses for the Windows popup, skipped when Node is absent. That covers `color.js` against every
colour representation the shell can hand it, and `statusText.js` against the real locale
templates. Keeping logic that can fail on a boundary out of the gi-importing modules is what
makes this possible, so new pure logic belongs in a module of its own rather than inside an
indicator method.

**Unverified.** Everything that touches Cairo or St: whether the icon draws the right pixels and
whether the menu lays out correctly. No amount of offline testing settles that - only a session
does:

```sh
gnome-extensions info usage-monitor-for-claude@cailo.github.com
journalctl --user -f -o cat /usr/bin/gnome-shell
```

Three files exist to keep the first two levels reachable, and new code should route through them
rather than growing its own branch:

- `layout.js` - `St.BoxLayout` became `Clutter.Orientable` in 47, so orientation is set through
  whichever API the running shell exposes
- `color.js` - `Clutter.Color` was removed in 47 and merged into `Cogl.Color`, which uses 0-1
  floats where the old type used 0-255 bytes, and the components reach JavaScript as struct
  fields on some builds and only as getters on others. An unreadable component would yield `NaN`,
  which Cairo draws as nothing and logs as nothing, so every read goes through one accessor that
  falls back to the getter and then to an obvious magenta rather than propagating `NaN`
- `statusText.js` - the footer's time arithmetic and template substitution, which tick once a
  second while the menu is open. An unresolved placeholder is dropped rather than printed, so a
  snapshot from an older daemon shortens a sentence instead of showing a raw `{duration}`
