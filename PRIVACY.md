# Privacy Policy

**Usage Monitor for Claude** is a local desktop application that monitors your Claude API usage.

## Data Collection

This application does **not** collect, store, or transmit any personal data.

## Network Communication

The application communicates with two hosts:

- `api.anthropic.com` - retrieves your current API usage data, authenticated with your OAuth token
- `status.anthropic.com` - retrieves the public Anthropic service status; this endpoint is read-only,
  involves no credentials, and is not contacted at all when the `status_enabled` setting is `false`

No other network connections are made.

## Credentials

The application reads your existing Claude OAuth token from the local Claude CLI configuration file
(`~/.claude/.credentials.json`). This token is:

- Used solely in HTTP Authorization headers to authenticate with the Anthropic API
- Never logged, stored elsewhere, copied, or transmitted to any third party

## Local Storage

The application does not write any files. All usage data is kept in memory only and discarded when
the application closes. An optional settings file (`usage-monitor-settings.json`) is read-only.

Two values are written to the Windows registry, both under `HKEY_CURRENT_USER`:

- `Software\Classes\AppUserModelId\JensDuttke.UsageMonitorForClaude` - the display name and icon
  shown in the header of the application's notifications. Re-registered on every start.
- `Software\Microsoft\Windows\CurrentVersion\Run` - the autostart entry. Written only when you
  enable autostart from the tray menu, removed when you disable it again.

On Linux there is no registry, and the notification identity comes from the `.desktop` file
installed by the package. The single-instance lock is the D-Bus name itself, so not even a lock
file is created. Exactly one file is ever written, and only on your explicit command:

- `~/.config/autostart/usage-monitor-for-claude.desktop` - the autostart entry, the direct
  counterpart of the Windows `Run` registry value. Written when you enable "Start with session"
  from the widget menu, removed when you disable it again.

## Claude Code Installation

When the OAuth token has expired, the application runs `claude update` so that the Claude Code CLI
renews the token in its own credentials file. As a side effect of that command, a newer Claude Code
version may be installed. No other software on your system is modified.

## Third-Party Services

The application does not integrate with any analytics, tracking, advertising, or telemetry services.

## Contact

For questions about this privacy policy, please open an issue at
https://github.com/jens-duttke/usage-monitor-for-claude/issues
