/*
 * Usage Monitor for Claude - panel indicator.
 *
 * The indicator is a drawing surface: the daemon owns polling, formatting,
 * translation, alerts and the credentials. Nothing here talks to the
 * Anthropic API, so no token ever enters the gnome-shell process.
 *
 * The Plasma applet splits its interface in two - a popup on left click and a
 * context menu on right click. A GNOME panel button has one menu, so the
 * detail sections and the actions share it, separated by a rule.
 */
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {PanelIcon} from './panelIcon.js';
import {UsageBar} from './usageBar.js';
import {horizontalBox, verticalBox} from './layout.js';
import {formatStatus} from './statusText.js';

export const UsageMonitorIndicator = GObject.registerClass(
class UsageMonitorIndicator extends PanelMenu.Button {
    _init(client, gettext) {
        super._init(0.5, 'Usage Monitor for Claude');

        this._client = client;
        this._ = gettext;
        this._snapshot = null;
        this._statusLabel = null;
        this._tickSourceId = 0;

        this._icon = new PanelIcon();
        this.add_child(this._icon);

        this.menu.actor.add_style_class_name('usage-monitor-popup');
        this.menu.connect('open-state-changed', (menu, isOpen) => this._onOpenStateChanged(isOpen));

        this._rebuild();
    }

    setSnapshot(snapshot) {
        this._snapshot = snapshot;
        this._icon.setState(snapshot, this._client.available);
        this._rebuild();
    }

    /*
     * The Windows build runs the double-click command on a double click. A
     * panel button cannot take that gesture without delaying every single
     * click, so it moves to the middle button, which the shell does not use.
     */
    vfunc_event(event) {
        const isMiddlePress = event.type() === Clutter.EventType.BUTTON_PRESS
            && event.get_button() === Clutter.BUTTON_MIDDLE;

        if (isMiddlePress && this._eventConfigured('double_click')) {
            this._client.runEvent('double_click');
            return Clutter.EVENT_STOP;
        }

        return super.vfunc_event(event);
    }

    destroy() {
        this._stopTicking();
        super.destroy();
    }

    // ------------------------------------------------------------------
    // Menu construction
    // ------------------------------------------------------------------

    _rebuild() {
        this.menu.removeAll();
        this._statusLabel = null;

        if (!this._snapshot) {
            this.menu.addAction(this._('The Usage Monitor daemon is not running.'), () => this._client.restart());
            return;
        }

        this._addHeader();
        this._addDetails();
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._addActions();
    }

    _addHeader() {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        const row = horizontalBox({style_class: 'usage-monitor-header', x_expand: true});

        row.add_child(new St.Label({
            style_class: 'usage-monitor-title',
            text: this._label('title'),
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));

        const refresh = new St.Button({
            style_class: 'usage-monitor-refresh',
            can_focus: true,
            child: new St.Icon({icon_name: 'view-refresh-symbolic', icon_size: 16}),
        });
        refresh.connect('clicked', () => this._client.refresh());
        row.add_child(refresh);

        item.add_child(row);
        this.menu.addMenuItem(item);
    }

    _addDetails() {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        const content = verticalBox({style_class: 'usage-monitor-content', x_expand: true});

        this._addAccountSection(content);
        this._addUsageSection(content);
        this._addExtraSection(content);
        this._addInstallationsSection(content);
        this._addServerStatusSection(content);
        this._addFooter(content);

        item.add_child(content);
        this.menu.addMenuItem(item);
    }

    _addAccountSection(content) {
        const profile = this._snapshot.profile;
        if (!profile) {
            return;
        }

        const section = this._section(content, this._label('account'));
        section.add_child(this._detailRow(this._label('email'), profile.email));
        section.add_child(this._detailRow(this._label('plan'), profile.plan));
    }

    _addUsageSection(content) {
        const usage = this._snapshot.usage || [];
        if (usage.length === 0) {
            return;
        }

        const section = this._section(content, this._label('usage'));
        for (const entry of usage) {
            section.add_child(new UsageBar(entry));
        }
    }

    _addExtraSection(content) {
        const extra = this._snapshot.extra;
        if (!extra) {
            return;
        }

        const section = this._section(content, this._label('extra_usage'));

        // The spending text takes the label slot: uncapped extra usage has no
        // percentage, so the amount spent is the only meaningful caption.
        section.add_child(new UsageBar({
            label: extra.spent_text,
            pct_text: extra.pct_text,
            fill_pct: extra.fill_pct,
            warn: false,
            reset_text: '',
            dividers: [],
            marker_rel: null,
        }));
    }

    _addInstallationsSection(content) {
        const installations = this._snapshot.installations || [];
        if (installations.length === 0) {
            return;
        }

        const section = this._section(content, this._label('claude_code'), this._label('changelog'),
            () => this._openUri(this._snapshot.links.changelog));

        for (const installation of installations) {
            section.add_child(this._detailRow(installation.name, installation.version));
        }
    }

    _addServerStatusSection(content) {
        const status = this._snapshot.anthropic_status;
        if (!status) {
            return;
        }

        const section = this._section(content, this._label('anthropic_status'));
        const row = horizontalBox({style_class: 'usage-monitor-status-row', x_expand: true});

        row.add_child(new St.Widget({
            style_class: status.indicator === 'none' ? 'usage-monitor-dot-ok' : 'usage-monitor-dot-warn',
            y_align: Clutter.ActorAlign.CENTER,
        }));

        const button = new St.Button({
            style_class: 'usage-monitor-status-button',
            x_expand: true,
            child: new St.Label({text: status.text, x_expand: true}),
        });
        button.connect('clicked', () => this._openUri(this._snapshot.links.status_page));
        row.add_child(button);

        section.add_child(row);

        if (status.incident) {
            section.add_child(new St.Label({
                style_class: 'usage-monitor-incident',
                text: status.incident,
                x_expand: true,
            }));
        }
    }

    /*
     * The footer counts up from the last fetch and down to the next one, so it
     * has to tick locally - the daemon only sends the two timestamps.
     */
    _addFooter(content) {
        const row = horizontalBox({style_class: 'usage-monitor-footer', x_expand: true});
        const status = this._snapshot.status || {};

        this._statusLabel = new St.Label({
            style_class: status.is_error ? 'usage-monitor-footer-error' : 'usage-monitor-footer-text',
            text: this._formatStatus(),
            x_expand: true,
        });

        row.add_child(this._statusLabel);
        row.add_child(new St.Label({
            style_class: 'usage-monitor-version',
            text: this._snapshot.app_version || '',
        }));

        content.add_child(row);
    }

    _addActions() {
        const autostart = new PopupMenu.PopupSwitchMenuItem(this._label('autostart'), Boolean(this._snapshot.autostart));
        autostart.connect('toggled', (item, state) => this._client.setAutostart(state));
        this.menu.addMenuItem(autostart);

        this._addEventTests();

        this.menu.addAction(this._label('restart'), () => this._client.restart());
        this.menu.addAction(this._label('menu_project'), () => this._openUri(this._snapshot.links.project));
        this.menu.addAction(this._label('quit'), () => this._client.quit());
    }

    _addEventTests() {
        const tests = [
            ['reset', 'reset_5h', 'test_reset_5h'],
            ['reset', 'reset_7d', 'test_reset_7d'],
            ['threshold', 'threshold_5h', 'test_threshold_5h'],
            ['threshold', 'threshold_7d', 'test_threshold_7d'],
            ['startup', 'startup', 'test_startup'],
            ['double_click', 'double_click', 'test_double_click'],
        ];

        const available = tests.filter(([configuredAs]) => this._eventConfigured(configuredAs));
        if (available.length === 0) {
            return;
        }

        const submenu = new PopupMenu.PopupSubMenuMenuItem(this._label('test_commands'));
        for (const [, eventName, labelKey] of available) {
            submenu.menu.addAction(this._label(labelKey), () => this._client.runEvent(eventName));
        }

        this.menu.addMenuItem(submenu);
    }

    // ------------------------------------------------------------------
    // Building blocks
    // ------------------------------------------------------------------

    _section(content, heading, linkText = null, onLinkClicked = null) {
        const section = verticalBox({style_class: 'usage-monitor-section', x_expand: true});
        const headingRow = horizontalBox({x_expand: true});

        headingRow.add_child(new St.Label({
            style_class: 'usage-monitor-heading',
            text: heading,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));

        if (linkText) {
            const link = new St.Button({
                style_class: 'usage-monitor-link',
                can_focus: true,
                label: linkText,
            });
            link.connect('clicked', onLinkClicked);
            headingRow.add_child(link);
        }

        section.add_child(headingRow);
        content.add_child(section);

        return section;
    }

    _detailRow(name, value) {
        const row = horizontalBox({style_class: 'usage-monitor-row', x_expand: true});

        row.add_child(new St.Label({style_class: 'usage-monitor-row-name', text: name, x_expand: true}));
        row.add_child(new St.Label({style_class: 'usage-monitor-row-value', text: value || ''}));

        return row;
    }

    // ------------------------------------------------------------------
    // Footer clock
    // ------------------------------------------------------------------

    _onOpenStateChanged(isOpen) {
        if (!isOpen) {
            this._stopTicking();
            return;
        }

        // Opening the menu should show current numbers, not whatever the last
        // pushed snapshot left behind.
        this._client.refresh();
        this._startTicking();
    }

    _startTicking() {
        this._stopTicking();

        this._tickSourceId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            if (this._statusLabel) {
                this._statusLabel.text = this._formatStatus();
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopTicking() {
        if (this._tickSourceId) {
            GLib.Source.remove(this._tickSourceId);
            this._tickSourceId = 0;
        }
    }

    // The arithmetic and template substitution live in statusText.js, which
    // has no gi:// import and is therefore executable under plain Node - see
    // tests/test_gnome_js.py. This end only supplies the snapshot and clock.
    _formatStatus() {
        const status = this._snapshot ? this._snapshot.status : null;
        const labels = this._snapshot ? this._snapshot.labels : null;

        return formatStatus(status, labels, Date.now() / 1000);
    }

    // ------------------------------------------------------------------
    // Snapshot helpers
    // ------------------------------------------------------------------

    _label(key) {
        const labels = this._snapshot ? this._snapshot.labels : null;
        return labels && labels[key] ? labels[key] : '';
    }

    _eventConfigured(name) {
        return this._snapshot ? this._snapshot.events[name] === true : false;
    }

    _openUri(uri) {
        if (!uri) {
            return;
        }

        this.menu.close();

        // A machine with no registered http handler throws here, and an
        // exception raised inside a shell signal handler is reported to the
        // user as a shell error - the failed click is not worth that.
        try {
            Gio.AppInfo.launch_default_for_uri(uri, null);
        } catch (error) {
            logError(error, `usage-monitor: could not open ${uri}`);
        }
    }
});
