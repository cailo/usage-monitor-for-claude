/*
 * Panel icon: the letter "C" over two usage bars.
 *
 * A direct port of the tray icon the Windows build renders with Pillow,
 * drawn here on a Canvas so it follows the Plasma colour scheme and stays
 * crisp at any panel height.  The geometry constants are the 64px design
 * grid of the original, scaled to whatever size the panel hands us.
 */
import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: compactIcon

    property var snapshot: null

    // The original 64px design grid - every constant below is expressed in it.
    readonly property int designSize: 64
    readonly property int barHeight: 9
    readonly property int barGap: 3
    readonly property int markerWidth: 4
    readonly property int numberRowHeight: 32

    readonly property var iconData: snapshot ? snapshot.icon : null
    readonly property var bars: iconData ? iconData.bars : []
    readonly property real pctTop: bars.length > 0 ? bars[0].pct : 0
    readonly property real pctBottom: bars.length > 1 ? bars[1].pct : 0
    readonly property bool extraAvailable: iconData ? iconData.extra_usage_available : false
    readonly property bool numbersStyle: iconData ? iconData.style === 'numbers' : false
    readonly property bool failed: iconData ? iconData.failed : false
    readonly property bool authError: iconData ? iconData.auth_error : false

    readonly property color foreground: Kirigami.Theme.textColor
    readonly property color foregroundWarn: Kirigami.Theme.negativeTextColor
    readonly property color foregroundHalf: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.35)

    onSnapshotChanged: canvas.requestPaint()
    onForegroundChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        onPaint: {
            const ctx = getContext('2d');
            ctx.reset();

            const scale = Math.min(width, height) / compactIcon.designSize;
            ctx.scale(scale, scale);
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            if (compactIcon.failed) {
                compactIcon.paintFailure(ctx);
            } else if (compactIcon.numbersStyle) {
                compactIcon.paintNumbers(ctx);
            } else {
                compactIcon.paintClassic(ctx);
            }
        }
    }

    /*
     * A failed poll replaces the whole icon: keeping the last percentages on
     * screen would present stale numbers as current.  An authentication
     * failure keeps the "C" so it reads as "this app needs a login" rather
     * than "your quota broke".
     */
    function paintFailure(ctx) {
        drawGlyph(ctx, authError ? 'C!' : '!', authError ? 34 : 46, designSize / 2, designSize / 2);
    }

    /*
     * Two states collapse both rows into one full-size glyph: idle shows the
     * single "C", and both quotas exhausted shows one large glyph - extra
     * usage applies account-wide, so two rows would repeat the same symbol.
     */
    function paintNumbers(ctx) {
        const size = designSize;
        if (pctTop >= 100 && pctBottom >= 100) {
            drawGlyph(ctx, extraAvailable ? '$' : '✕', 42, size / 2, size / 2);
            return;
        }
        if (pctTop <= 0 && pctBottom <= 0) {
            drawGlyph(ctx, 'C', 42, size / 2, size / 2);
            return;
        }

        drawNumberRow(ctx, 0, pctTop);
        drawNumberRow(ctx, numberRowHeight, pctBottom);
    }

    function drawNumberRow(ctx, rowTop, pct) {
        const centerY = rowTop + numberRowHeight / 2;
        if (pct >= 100) {
            drawGlyph(ctx, extraAvailable ? '$' : '✕', 32, designSize / 2, centerY);
            return;
        }

        // Clamp to 99: values in [99.5, 100) would round to a three-digit
        // '100' that overflows the canvas and reads as exhausted.
        drawGlyph(ctx, Math.round(Math.min(pct, 99)).toString(), 34, designSize / 2, centerY);
    }

    /*
     * Top glyph: "✕" when any quota is exhausted and no extra credits remain,
     * "$" when exhausted but paid extra usage is still available, "C" while
     * usage is still zero, otherwise the percentage.
     */
    function paintClassic(ctx) {
        const size = designSize;
        const barBottomY = size - barHeight;
        const barTopY = barBottomY - barGap - barHeight;
        const anyExhausted = pctTop >= 100 || pctBottom >= 100;

        let glyph = 'C';
        let glyphSize = 42;
        if (anyExhausted) {
            glyph = extraAvailable ? '$' : '✕';
        } else if (pctTop > 0) {
            glyph = Math.round(Math.min(pctTop, 99)).toString();
            glyphSize = 40;
        }

        drawGlyph(ctx, glyph, glyphSize, size / 2, barTopY / 2);
        drawBar(ctx, barTopY, bars.length > 0 ? bars[0] : null);
        drawBar(ctx, barBottomY, bars.length > 1 ? bars[1] : null);
    }

    function drawGlyph(ctx, text, pixelSize, centerX, centerY) {
        ctx.fillStyle = foreground;
        ctx.font = 'bold ' + pixelSize + 'px sans-serif';
        ctx.fillText(text, centerX, centerY);
    }

    /*
     * In 'utilization' mode the bar fills linearly and shows a reset-time
     * marker; the fill turns to the warning colour when usage is ahead of
     * elapsed time.  In 'overage' mode the bar fills as usage exceeds the
     * time marker and no marker is drawn - elapsed time is already in the fill.
     */
    function drawBar(ctx, y, bar) {
        const size = designSize;
        ctx.fillStyle = foregroundHalf;
        ctx.fillRect(0, y, size, barHeight);

        if (!bar) {
            return;
        }

        const pct = bar.pct;
        const timePct = bar.time_pct;

        if (bar.mode === 'overage' && timePct !== null && timePct !== undefined) {
            if (timePct >= 100) {
                // End state for a stale window: an exhausted quota keeps the
                // bar full, usage within budget leaves it empty.
                if (pct >= 100) {
                    ctx.fillStyle = foreground;
                    ctx.fillRect(0, y, size, barHeight);
                }
                return;
            }

            const overage = Math.max(0, pct - timePct);
            const fillRatio = Math.min(1, overage / (100 - timePct));
            if (fillRatio > 0) {
                ctx.fillStyle = foreground;
                ctx.fillRect(0, y, size * fillRatio, barHeight);
            }
            return;
        }

        const fillWidth = Math.max(0, Math.min(size, size * pct / 100));
        if (fillWidth > 0) {
            const warn = pct >= 100 || (timePct !== null && timePct !== undefined && pct > timePct);
            ctx.fillStyle = warn ? foregroundWarn : foreground;
            ctx.fillRect(0, y, fillWidth, barHeight);
        }

        if (bar.mode !== 'utilization' || timePct === null || timePct === undefined) {
            return;
        }

        const markerX = Math.min(size - markerWidth, Math.max(0, size * timePct / 100 - markerWidth / 2));
        ctx.fillStyle = foreground;
        ctx.fillRect(markerX, y, markerWidth, barHeight);
    }
}
