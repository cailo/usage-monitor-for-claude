/*
 * Usage Monitor for Claude - GNOME Shell extension.
 *
 * Phase two of the Linux port: the same headless daemon that feeds the Plasma
 * applet feeds this indicator, over the same D-Bus interface and the same
 * fully formatted, already translated snapshot. Everything the extension
 * knows about quotas it was told; it never reads a credential or reaches the
 * network.
 */
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {DaemonClient} from './daemonClient.js';
import {UsageMonitorIndicator} from './indicator.js';

export default class UsageMonitorForClaudeExtension extends Extension {
    enable() {
        // The client is built first so the indicator can call it from the
        // menu it constructs during its own initialisation.
        this._client = new DaemonClient(snapshot => this._onSnapshot(snapshot));
        this._indicator = new UsageMonitorIndicator(this._client, text => this.gettext(text));

        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._client.start();
    }

    /*
     * Everything acquired in enable() is released here: an extension that
     * leaves a bus watch or a timeout behind keeps running after the user
     * disabled it, and locks the screen with a stale indicator on unlock.
     */
    disable() {
        this._client?.stop();
        this._client = null;

        this._indicator?.destroy();
        this._indicator = null;
    }

    _onSnapshot(snapshot) {
        this._indicator?.setSnapshot(snapshot);
    }
}
