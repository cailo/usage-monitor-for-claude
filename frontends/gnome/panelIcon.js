/*
 * Usage Monitor for Claude - panel icon.
 *
 * The letter "C" over two usage bars, drawn with Cairo so it follows the
 * shell theme and stays crisp at any scale factor. This is the same 64px
 * design grid the Windows build renders with Pillow and the Plasma applet
 * renders on a QML Canvas: the geometry constants below are that grid,
 * scaled to whatever size the panel allocates.
 *
 * Text goes through Pango rather than Cairo's "toy" text API because the
 * exhausted state draws U+2715 (✕), which needs font fallback to render at
 * all on a system whose default sans has no such glyph.
 */
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import PangoCairo from 'gi://PangoCairo';
import St from 'gi://St';

import {foregroundColor, setSource, themeColor} from './color.js';

// The original 64px design grid - every constant below is expressed in it.
const DESIGN_SIZE = 64;
const BAR_HEIGHT = 9;
const BAR_GAP = 3;
const MARKER_WIDTH = 4;
const NUMBER_ROW_HEIGHT = 32;

const GLYPH_SIZE_LARGE = 42;
const GLYPH_SIZE_PERCENT = 40;
const GLYPH_SIZE_ROW = 34;
const GLYPH_SIZE_ROW_EXHAUSTED = 32;
const GLYPH_SIZE_FAILURE = 46;
const GLYPH_SIZE_AUTH_FAILURE = 34;

// Opacity of the empty part of a bar, matching the Windows and Plasma icons.
const TRACK_ALPHA = 0.35;

const WARN_COLOR_PROPERTY = '-usage-monitor-warn-color';
const WARN_COLOR_FALLBACK = {red: 224, green: 27, blue: 36, alpha: 255};

export const PanelIcon = GObject.registerClass(
class PanelIcon extends St.DrawingArea {
    _init() {
        super._init({
            style_class: 'usage-monitor-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._snapshot = null;
        this._daemonAvailable = false;

        this.connect('repaint', () => this._repaint());
        // The panel foreground changes with the theme and with the overview
        // opening; without this the icon keeps the colour it was born with.
        this.connect('style-changed', () => this.queue_repaint());
    }

    setState(snapshot, daemonAvailable) {
        this._snapshot = snapshot;
        this._daemonAvailable = daemonAvailable;
        this.queue_repaint();
    }

    _repaint() {
        const cr = this.get_context();

        try {
            const [width, height] = this.get_surface_size();
            const scale = Math.min(width, height) / DESIGN_SIZE;

            cr.scale(scale, scale);
            this._paint(cr);
        } finally {
            // GJS does not free the Cairo context on garbage collection; a
            // missed dispose leaks a surface on every single repaint.
            cr.$dispose();
        }
    }

    _paint(cr) {
        const icon = this._snapshot ? this._snapshot.icon : null;

        // A stopped daemon reads as a failure rather than as zero usage:
        // drawing empty bars would claim the quotas are untouched.
        if (!this._daemonAvailable || !icon) {
            this._drawGlyph(cr, '!', GLYPH_SIZE_FAILURE, DESIGN_SIZE / 2, DESIGN_SIZE / 2, this._foreground());
            return;
        }

        if (icon.failed) {
            this._paintFailure(cr, icon);
            return;
        }

        if (icon.style === 'numbers') {
            this._paintNumbers(cr, icon);
            return;
        }

        this._paintClassic(cr, icon);
    }

    /*
     * A failed poll replaces the whole icon: keeping the last percentages on
     * screen would present stale numbers as current. An authentication
     * failure keeps the "C" so it reads as "this app needs a login" rather
     * than "your quota broke".
     */
    _paintFailure(cr, icon) {
        const text = icon.auth_error ? 'C!' : '!';
        const size = icon.auth_error ? GLYPH_SIZE_AUTH_FAILURE : GLYPH_SIZE_FAILURE;
        this._drawGlyph(cr, text, size, DESIGN_SIZE / 2, DESIGN_SIZE / 2, this._foreground());
    }

    /*
     * Two states collapse both rows into one full-size glyph: idle shows the
     * single "C", and both quotas exhausted shows one large glyph - extra
     * usage applies account-wide, so two rows would repeat the same symbol.
     */
    _paintNumbers(cr, icon) {
        const top = this._percent(icon, 0);
        const bottom = this._percent(icon, 1);

        if (top >= 100 && bottom >= 100) {
            this._drawGlyph(cr, icon.extra_usage_available ? '$' : '✕', GLYPH_SIZE_LARGE,
                DESIGN_SIZE / 2, DESIGN_SIZE / 2, this._foreground());
            return;
        }

        if (top <= 0 && bottom <= 0) {
            this._drawGlyph(cr, 'C', GLYPH_SIZE_LARGE, DESIGN_SIZE / 2, DESIGN_SIZE / 2, this._foreground());
            return;
        }

        this._drawNumberRow(cr, 0, top, icon.extra_usage_available);
        this._drawNumberRow(cr, NUMBER_ROW_HEIGHT, bottom, icon.extra_usage_available);
    }

    _drawNumberRow(cr, rowTop, pct, extraAvailable) {
        const centerY = rowTop + NUMBER_ROW_HEIGHT / 2;

        if (pct >= 100) {
            this._drawGlyph(cr, extraAvailable ? '$' : '✕', GLYPH_SIZE_ROW_EXHAUSTED,
                DESIGN_SIZE / 2, centerY, this._foreground());
            return;
        }

        // Clamp to 99: values in [99.5, 100) would round to a three-digit
        // '100' that overflows the icon and reads as exhausted.
        const text = Math.round(Math.min(pct, 99)).toString();
        this._drawGlyph(cr, text, GLYPH_SIZE_ROW, DESIGN_SIZE / 2, centerY, this._foreground());
    }

    /*
     * Top glyph: "✕" when any quota is exhausted and no extra credits remain,
     * "$" when exhausted but paid extra usage is still available, "C" while
     * usage is still zero, otherwise the percentage.
     */
    _paintClassic(cr, icon) {
        const bars = icon.bars || [];
        const top = this._percent(icon, 0);
        const bottom = this._percent(icon, 1);

        const barBottomY = DESIGN_SIZE - BAR_HEIGHT;
        const barTopY = barBottomY - BAR_GAP - BAR_HEIGHT;
        const anyExhausted = top >= 100 || bottom >= 100;

        let glyph = 'C';
        let glyphSize = GLYPH_SIZE_LARGE;

        if (anyExhausted) {
            glyph = icon.extra_usage_available ? '$' : '✕';
        } else if (top > 0) {
            glyph = Math.round(Math.min(top, 99)).toString();
            glyphSize = GLYPH_SIZE_PERCENT;
        }

        this._drawGlyph(cr, glyph, glyphSize, DESIGN_SIZE / 2, barTopY / 2, this._foreground());
        this._drawBar(cr, barTopY, bars[0] || null);
        this._drawBar(cr, barBottomY, bars[1] || null);
    }

    /*
     * In 'utilization' mode the bar fills linearly and shows a reset-time
     * marker; the fill turns to the warning colour when usage is ahead of
     * elapsed time. In 'overage' mode the bar fills as usage exceeds the time
     * marker and no marker is drawn - elapsed time is already in the fill.
     */
    _drawBar(cr, y, bar) {
        const foreground = this._foreground();

        this._fillRect(cr, 0, y, DESIGN_SIZE, BAR_HEIGHT, foreground, TRACK_ALPHA);

        if (!bar) {
            return;
        }

        const pct = bar.pct;
        const timePct = bar.time_pct;
        const hasTime = timePct !== null && timePct !== undefined;

        if (bar.mode === 'overage' && hasTime) {
            if (timePct >= 100) {
                // End state for a stale window: an exhausted quota keeps the
                // bar full, usage within budget leaves it empty.
                if (pct >= 100) {
                    this._fillRect(cr, 0, y, DESIGN_SIZE, BAR_HEIGHT, foreground);
                }
                return;
            }

            const overage = Math.max(0, pct - timePct);
            const fillRatio = Math.min(1, overage / (100 - timePct));
            if (fillRatio > 0) {
                this._fillRect(cr, 0, y, DESIGN_SIZE * fillRatio, BAR_HEIGHT, foreground);
            }
            return;
        }

        const fillWidth = Math.max(0, Math.min(DESIGN_SIZE, DESIGN_SIZE * pct / 100));
        if (fillWidth > 0) {
            const warn = pct >= 100 || (hasTime && pct > timePct);
            this._fillRect(cr, 0, y, fillWidth, BAR_HEIGHT, warn ? this._warning() : foreground);
        }

        if (bar.mode !== 'utilization' || !hasTime) {
            return;
        }

        const markerX = Math.min(DESIGN_SIZE - MARKER_WIDTH, Math.max(0, DESIGN_SIZE * timePct / 100 - MARKER_WIDTH / 2));
        this._fillRect(cr, markerX, y, MARKER_WIDTH, BAR_HEIGHT, foreground);
    }

    _drawGlyph(cr, text, pixelSize, centerX, centerY, color) {
        const layout = PangoCairo.create_layout(cr);
        const description = Pango.FontDescription.from_string('Sans Bold');

        // Absolute size, not set_size(): the context is already scaled to the
        // panel, so the glyph must be expressed in the same 64px grid as the
        // bars rather than in points.
        description.set_absolute_size(pixelSize * Pango.SCALE);
        layout.set_font_description(description);
        layout.set_text(text, -1);

        const [width, height] = layout.get_pixel_size();
        setSource(cr, color);
        cr.moveTo(centerX - width / 2, centerY - height / 2);
        PangoCairo.show_layout(cr, layout);
    }

    _fillRect(cr, x, y, width, height, color, alphaScale = 1) {
        setSource(cr, color, alphaScale);
        cr.rectangle(x, y, width, height);
        cr.fill();
    }

    _percent(icon, index) {
        const bars = icon.bars || [];
        return bars.length > index ? bars[index].pct : 0;
    }

    _foreground() {
        return foregroundColor(this.get_theme_node());
    }

    _warning() {
        return themeColor(this.get_theme_node(), WARN_COLOR_PROPERTY, WARN_COLOR_FALLBACK);
    }
});
