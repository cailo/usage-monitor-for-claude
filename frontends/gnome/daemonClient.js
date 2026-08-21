/*
 * Usage Monitor for Claude - D-Bus client.
 *
 * GJS has a real D-Bus binding, so unlike the Plasma applet - which has to
 * shell out to `usage-monitor-for-claude-client` because QML has none - the
 * extension talks to the daemon directly and subscribes to SnapshotChanged.
 * Data arrives when the daemon has it instead of being polled for, which
 * removes one short-lived process per poll.
 *
 * Every call uses the async ("Remote") form: a synchronous D-Bus round trip
 * from an extension blocks the compositor's main loop, which freezes the
 * whole desktop when the daemon is slow to answer.
 */
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

// The daemon appends a per-instance suffix derived from --config-dir. The
// extension targets the default instance; a second Claude account runs a
// second daemon under a suffixed name, which the shell has no way to know.
const BUS_NAME = 'com.github.cailo.UsageMonitor';
const OBJECT_PATH = '/com/github/cailo/UsageMonitor';

const DAEMON_COMMAND = 'usage-monitor-for-claude-daemon';

// Seconds to let the old process release the bus name before the new one
// claims it. The daemon cannot outlive its own shutdown to relaunch itself,
// so a restart is a quit followed by a detached start.
const RESTART_DELAY = 1;

const IFACE_XML = `
<node>
  <interface name="com.github.cailo.UsageMonitor">
    <method name="GetSnapshot">
      <arg type="s" direction="out" name="payload"/>
    </method>
    <method name="Refresh">
      <arg type="b" direction="out" name="started"/>
    </method>
    <method name="RunEventTest">
      <arg type="s" direction="in" name="event"/>
      <arg type="b" direction="out" name="ran"/>
    </method>
    <method name="SetAutostart">
      <arg type="b" direction="in" name="enabled"/>
      <arg type="b" direction="out" name="state"/>
    </method>
    <method name="Quit"/>
    <signal name="SnapshotChanged">
      <arg type="s" name="payload"/>
    </signal>
  </interface>
</node>`;

const UsageMonitorProxy = Gio.DBusProxy.makeProxyWrapper(IFACE_XML);

export class DaemonClient {
    /*
     * @param {function(object|null): void} onSnapshot - called with the parsed
     *     snapshot, or null when the daemon went away.
     */
    constructor(onSnapshot) {
        this._onSnapshot = onSnapshot;
        this._proxy = null;
        this._signalId = 0;
        this._watchId = 0;
        this._restartSourceId = 0;
    }

    get available() {
        return this._proxy !== null;
    }

    /*
     * Watching the name rather than constructing the proxy once means the
     * extension survives the daemon being stopped and started again - the
     * usual case, since the panel menu itself offers Restart and Quit.
     */
    start() {
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => this._onNameAppeared(),
            () => this._onNameVanished(),
        );
    }

    stop() {
        if (this._restartSourceId) {
            GLib.Source.remove(this._restartSourceId);
            this._restartSourceId = 0;
        }

        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = 0;
        }

        this._disconnectProxy();
    }

    refresh() {
        // The daemon fetches on its own poll thread and emits SnapshotChanged
        // when the result lands, so there is nothing to do with the reply.
        this._call('RefreshRemote');
    }

    runEvent(name) {
        this._call('RunEventTestRemote', name);
    }

    setAutostart(enabled) {
        this._call('SetAutostartRemote', enabled);
    }

    quit() {
        this._call('QuitRemote');
    }

    restart() {
        this.quit();

        this._restartSourceId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, RESTART_DELAY, () => {
            this._restartSourceId = 0;
            this._spawnDaemon();
            return GLib.SOURCE_REMOVE;
        });
    }

    _call(method, ...args) {
        if (!this._proxy) {
            return;
        }

        // Errors are reported as data, not thrown: a daemon that died between
        // the menu opening and the click landing must not raise inside the
        // shell's main loop.
        this._proxy[method](...args, (result, error) => {
            if (error) {
                logError(error, `usage-monitor: ${method} failed`);
            }
        });
    }

    _onNameAppeared() {
        new UsageMonitorProxy(Gio.DBus.session, BUS_NAME, OBJECT_PATH, (proxy, error) => {
            if (error) {
                logError(error, 'usage-monitor: could not reach the daemon');
                return;
            }

            this._proxy = proxy;
            this._signalId = proxy.connectSignal('SnapshotChanged', (_proxy, _sender, [payload]) => {
                this._deliver(payload);
            });

            // The signal only fires on the next change, which can be a full
            // poll interval away - ask for the current state right now.
            proxy.GetSnapshotRemote((result, callError) => {
                if (callError) {
                    logError(callError, 'usage-monitor: GetSnapshot failed');
                    return;
                }
                this._deliver(result[0]);
            });
        });
    }

    _onNameVanished() {
        this._disconnectProxy();
        this._onSnapshot(null);
    }

    _disconnectProxy() {
        if (this._proxy && this._signalId) {
            this._proxy.disconnectSignal(this._signalId);
        }

        this._signalId = 0;
        this._proxy = null;
    }

    _deliver(payload) {
        let parsed = null;

        try {
            parsed = JSON.parse(payload);
        } catch (error) {
            logError(error, 'usage-monitor: malformed snapshot');
            return;
        }

        if (!parsed || parsed.error) {
            this._onSnapshot(null);
            return;
        }

        this._onSnapshot(parsed);
    }

    _spawnDaemon() {
        try {
            // Detached from the shell: an extension being disabled, or the
            // shell restarting, must not take the daemon down with it.
            GLib.spawn_async(
                null, ['/bin/sh', '-c', `setsid ${DAEMON_COMMAND}`], null,
                GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.STDOUT_TO_DEV_NULL | GLib.SpawnFlags.STDERR_TO_DEV_NULL,
                null,
            );
        } catch (error) {
            logError(error, 'usage-monitor: could not start the daemon');
        }
    }
}
