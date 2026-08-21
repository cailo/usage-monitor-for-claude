/*
 * Usage Monitor for Claude - one quota bar.
 *
 * Label and percentage on top, the bar itself, and the reset text below.
 * Every number arrives pre-computed from the daemon (fill fraction, divider
 * positions, marker position, reset text), so this file only draws - the
 * same contract the Plasma applet's UsageBar.qml works under.
 */
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {foregroundColor, setSource, themeColor} from './color.js';
import {horizontalBox} from './layout.js';

const BAR_HEIGHT = 10;
const MARKER_WIDTH = 2;
const DIVIDER_WIDTH = 1;

const TRACK_ALPHA = 0.15;

const ACCENT_COLOR_PROPERTY = '-usage-monitor-accent-color';
const WARN_COLOR_PROPERTY = '-usage-monitor-warn-color';
const DIVIDER_COLOR_PROPERTY = '-usage-monitor-divider-color';

const ACCENT_COLOR_FALLBACK = {red: 53, green: 132, blue: 228, alpha: 255};
const WARN_COLOR_FALLBACK = {red: 224, green: 27, blue: 36, alpha: 255};
const DIVIDER_COLOR_FALLBACK = {red: 0, green: 0, blue: 0, alpha: 115};

export const UsageBar = GObject.registerClass(
class UsageBar extends St.BoxLayout {
    _init(entry) {
        super._init({
            style_class: 'usage-monitor-bar',
            x_expand: true,
        });

        // Set after construction rather than as a `vertical` construct
        // property - see layout.js for why the two APIs have to coexist.
        if (typeof this.set_orientation === 'function') {
            this.set_orientation(Clutter.Orientation.VERTICAL);
        } else {
            this.vertical = true;
        }

        this._entry = entry;

        this.add_child(this._buildHeader());
        this.add_child(this._buildTrack());

        if (entry.reset_text) {
            this.add_child(new St.Label({
                style_class: 'usage-monitor-bar-reset',
                text: entry.reset_text,
                x_expand: true,
            }));
        }
    }

    _buildHeader() {
        const row = horizontalBox({style_class: 'usage-monitor-bar-header', x_expand: true});

        row.add_child(new St.Label({
            style_class: 'usage-monitor-bar-label',
            text: this._entry.label,
            x_expand: true,
        }));

        row.add_child(new St.Label({
            style_class: this._entry.warn ? 'usage-monitor-bar-percent-warn' : 'usage-monitor-bar-percent',
            text: this._entry.pct_text,
        }));

        return row;
    }

    _buildTrack() {
        const area = new St.DrawingArea({
            style_class: 'usage-monitor-bar-track',
            height: BAR_HEIGHT,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        area.connect('repaint', () => this._repaintTrack(area));

        return area;
    }

    _repaintTrack(area) {
        const cr = area.get_context();

        try {
            const [width, height] = area.get_surface_size();
            const radius = height / 2;
            const node = area.get_theme_node();

            this._roundedRect(cr, 0, 0, width, height, radius);
            setSource(cr, foregroundColor(node), TRACK_ALPHA);
            cr.fill();

            const fillWidth = width * Math.max(0, Math.min(1, this._entry.fill_pct));
            if (fillWidth > 0) {
                // The fill is clipped to the track's rounded outline instead of
                // being rounded itself: a short fill rounded on both ends turns
                // into a pill floating inside the track.
                cr.save();
                this._roundedRect(cr, 0, 0, width, height, radius);
                cr.clip();
                setSource(cr, this._entry.warn
                    ? themeColor(node, WARN_COLOR_PROPERTY, WARN_COLOR_FALLBACK)
                    : themeColor(node, ACCENT_COLOR_PROPERTY, ACCENT_COLOR_FALLBACK));
                cr.rectangle(0, 0, fillWidth, height);
                cr.fill();
                cr.restore();
            }

            this._drawDividers(cr, node, width, height);
            this._drawMarker(cr, node, width, height);
        } finally {
            cr.$dispose();
        }
    }

    // One notch per day or hour boundary inside the window, so a long bar
    // reads as a calendar rather than as one undifferentiated stretch.
    _drawDividers(cr, node, width, height) {
        const dividers = this._entry.dividers || [];

        setSource(cr, themeColor(node, DIVIDER_COLOR_PROPERTY, DIVIDER_COLOR_FALLBACK));
        for (const position of dividers) {
            cr.rectangle(width * position, 0, DIVIDER_WIDTH, height);
        }
        cr.fill();
    }

    // How far through the window we are: a fill reaching past the marker
    // means usage is running ahead of the clock.
    _drawMarker(cr, node, width, height) {
        const marker = this._entry.marker_rel;
        if (marker === null || marker === undefined) {
            return;
        }

        const x = Math.min(width - MARKER_WIDTH, Math.max(0, width * marker));
        setSource(cr, foregroundColor(node));
        cr.rectangle(x, 0, MARKER_WIDTH, height);
        cr.fill();
    }

    _roundedRect(cr, x, y, width, height, radius) {
        const limit = Math.min(radius, width / 2, height / 2);

        cr.newSubPath();
        cr.arc(x + width - limit, y + limit, limit, -Math.PI / 2, 0);
        cr.arc(x + width - limit, y + height - limit, limit, 0, Math.PI / 2);
        cr.arc(x + limit, y + height - limit, limit, Math.PI / 2, Math.PI);
        cr.arc(x + limit, y + limit, limit, Math.PI, 1.5 * Math.PI);
        cr.closePath();
    }
});
