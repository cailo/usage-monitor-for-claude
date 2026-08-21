/*
 * Usage Monitor for Claude - Plasma applet.
 *
 * The applet is a drawing surface: the daemon owns polling, formatting,
 * translation, alerts and the credentials.  Nothing here talks to the
 * Anthropic API, so no token ever enters the plasmashell process.
 */
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    // Installed by the -daemon package; QML has no D-Bus binding, so the
    // snapshot is read by running this client and parsing its stdout.
    readonly property string clientCommand: 'usage-monitor-for-claude-client'

    // Fallback cadence used until the daemon reports when it will poll next.
    readonly property int fallbackIntervalMs: 30000
    readonly property int minimumIntervalMs: 5000

    property var snapshot: null
    property bool daemonAvailable: false

    // No preferredRepresentation: pinning it to the compact form is exactly
    // what stops the panel from ever opening the popup on click.

    toolTipMainText: 'Usage Monitor for Claude'
    toolTipSubText: {
        if (!daemonAvailable) {
            return i18n('The Usage Monitor daemon is not running.');
        }
        if (!snapshot || !snapshot.tooltip) {
            return '';
        }
        // The daemon's tooltip repeats the app name on its first line, which
        // the panel already shows as the tooltip title.
        const lines = snapshot.tooltip.split('\n');
        return lines.slice(1).join('\n');
    }

    compactRepresentation: CompactIcon {
        snapshot: root.snapshot

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton

            onClicked: mouse => {
                // The Windows build runs the double-click command on a double
                // click.  A panel widget cannot take that gesture without
                // delaying every single click, so it moves to the middle
                // button, which the panel does not use.
                if (mouse.button === Qt.MiddleButton) {
                    root.runDoubleClickCommand();
                    return;
                }
                root.expanded = !root.expanded;
            }
        }
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: root.menuLabel('menu_show')
            icon.name: 'view-visible'
            onTriggered: root.expanded = true
        },
        PlasmaCore.Action {
            text: root.menuLabel('autostart')
            icon.name: 'system-run'
            checkable: true
            checked: root.snapshot ? root.snapshot.autostart : false
            onTriggered: root.setAutostart(!checked)
        },
        PlasmaCore.Action {
            text: root.menuLabel('test_reset_5h')
            icon.name: 'media-playback-start'
            visible: root.eventConfigured('reset')
            onTriggered: root.runEventTest('reset_5h')
        },
        PlasmaCore.Action {
            text: root.menuLabel('test_reset_7d')
            icon.name: 'media-playback-start'
            visible: root.eventConfigured('reset')
            onTriggered: root.runEventTest('reset_7d')
        },
        PlasmaCore.Action {
            text: root.menuLabel('test_threshold_5h')
            icon.name: 'media-playback-start'
            visible: root.eventConfigured('threshold')
            onTriggered: root.runEventTest('threshold_5h')
        },
        PlasmaCore.Action {
            text: root.menuLabel('test_threshold_7d')
            icon.name: 'media-playback-start'
            visible: root.eventConfigured('threshold')
            onTriggered: root.runEventTest('threshold_7d')
        },
        PlasmaCore.Action {
            text: root.menuLabel('test_startup')
            icon.name: 'media-playback-start'
            visible: root.eventConfigured('startup')
            onTriggered: root.runEventTest('startup')
        },
        PlasmaCore.Action {
            text: root.menuLabel('test_double_click')
            icon.name: 'media-playback-start'
            visible: root.eventConfigured('double_click')
            onTriggered: root.runEventTest('double_click')
        },
        PlasmaCore.Action {
            text: root.menuLabel('restart')
            icon.name: 'system-reboot'
            onTriggered: root.restartDaemon()
        },
        PlasmaCore.Action {
            text: root.menuLabel('menu_project')
            icon.name: 'internet-web-browser'
            onTriggered: Qt.openUrlExternally(root.snapshot ? root.snapshot.links.project : '')
        },
        PlasmaCore.Action {
            text: root.menuLabel('quit')
            icon.name: 'application-exit'
            onTriggered: root.quitDaemon()
        }
    ]

    fullRepresentation: Popup {
        snapshot: root.snapshot
        onRefreshRequested: root.requestRefresh()
    }

    Plasma5Support.DataSource {
        id: client
        engine: 'executable'
        connectedSources: []

        onNewData: (sourceName, data) => {
            disconnectSource(sourceName);
            root.handleClientOutput(sourceName, data['stdout']);
        }

        function run(command) {
            connectSource(command);
        }
    }

    Timer {
        id: pollTimer
        interval: root.fallbackIntervalMs
        repeat: false
        running: false
        onTriggered: root.readSnapshot()
    }

    Component.onCompleted: readSnapshot()

    // Opening the popup should show current numbers, not whatever the last
    // scheduled read happened to leave behind.
    onExpandedChanged: {
        // root.expanded, not the bare name: a property-change handler injects
        // the new value under the property's own name, and relying on that
        // injection is deprecated in Qt 6.
        if (root.expanded) {
            root.readSnapshot();
        }
    }

    function readSnapshot() {
        client.run(root.clientCommand + ' --snapshot');
    }

    function requestRefresh() {
        client.run(root.clientCommand + ' --refresh');
    }

    function menuLabel(key) {
        return root.snapshot && root.snapshot.labels[key] ? root.snapshot.labels[key] : '';
    }

    function eventConfigured(name) {
        return root.snapshot ? root.snapshot.events[name] === true : false;
    }

    function runEventTest(name) {
        client.run(root.clientCommand + ' --run-event ' + name);
    }

    function runDoubleClickCommand() {
        if (root.eventConfigured('double_click')) {
            client.run(root.clientCommand + ' --run-event double_click');
        }
    }

    function setAutostart(enabled) {
        client.run(root.clientCommand + ' --set-autostart ' + (enabled ? '1' : '0'));
    }

    function quitDaemon() {
        client.run(root.clientCommand + ' --quit');
    }

    /*
     * There is no Restart method on the bus: the daemon cannot outlive its own
     * shutdown to relaunch itself, so the widget asks it to quit and starts a
     * fresh one detached from the shell.
     */
    function restartDaemon() {
        client.run('sh -c "' + root.clientCommand + ' --quit; sleep 1; setsid usage-monitor-for-claude-daemon"');
    }

    function handleClientOutput(sourceName, stdout) {
        if (sourceName.indexOf('--run-event') !== -1 || sourceName.indexOf('--set-autostart') !== -1) {
            // Both change state the next snapshot has to reflect.
            pollTimer.interval = root.minimumIntervalMs;
            pollTimer.restart();
            return;
        }

        if (sourceName.indexOf('--refresh') !== -1) {
            // The daemon performs the fetch on its poll thread; read the
            // result shortly after instead of blocking on it.
            pollTimer.interval = root.minimumIntervalMs;
            pollTimer.restart();
            return;
        }

        let parsed = null;
        try {
            parsed = JSON.parse(stdout);
        } catch (error) {
            parsed = null;
        }

        if (!parsed || parsed.error) {
            root.daemonAvailable = false;
            pollTimer.interval = root.fallbackIntervalMs;
            pollTimer.restart();
            return;
        }

        root.daemonAvailable = true;
        root.snapshot = parsed;
        scheduleNextRead();
    }

    /*
     * The daemon already decided when it will next hit the API, so the applet
     * waits for that moment instead of polling on a cadence of its own.  In
     * practice that is one short-lived client process per daemon poll - the
     * countdown and reset texts in between are static until new data lands.
     */
    function scheduleNextRead() {
        let delay = root.fallbackIntervalMs;
        const status = root.snapshot ? root.snapshot.status : null;

        if (status && status.next_poll_time) {
            const msUntilPoll = (status.next_poll_time * 1000) - Date.now() + 2000;
            delay = Math.max(root.minimumIntervalMs, msUntilPoll);
        }

        pollTimer.interval = delay;
        pollTimer.restart();
    }
}
