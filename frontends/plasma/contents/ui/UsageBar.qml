/*
 * One quota bar: label, percentage, fill, period dividers and time marker.
 *
 * Every number arrives pre-computed from the daemon (fill fraction, divider
 * positions, marker position, reset text), so this file only draws.
 */
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents

ColumnLayout {
    id: usageBar

    property var entry: null

    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents.Label {
            text: usageBar.entry ? usageBar.entry.label : ''
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        PlasmaComponents.Label {
            text: usageBar.entry ? usageBar.entry.pct_text : ''
            font.weight: Font.Bold
            color: usageBar.entry && usageBar.entry.warn ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
        }
    }

    Item {
        Layout.fillWidth: true
        implicitHeight: Kirigami.Units.gridUnit * 0.75

        Rectangle {
            id: track
            anchors.fill: parent
            radius: height / 2
            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.15)

            Rectangle {
                width: parent.width * (usageBar.entry ? usageBar.entry.fill_pct : 0)
                height: parent.height
                radius: parent.radius
                color: usageBar.entry && usageBar.entry.warn ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor

                Behavior on width {
                    NumberAnimation { duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic }
                }
            }

            // Period dividers - one per day/hour boundary inside the window.
            Repeater {
                model: usageBar.entry ? usageBar.entry.dividers : []

                Rectangle {
                    x: track.width * modelData
                    width: 1
                    height: track.height
                    color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.7)
                }
            }

            // Elapsed-time marker: how far through the window we are, so a
            // fill to its left means usage is running ahead of the clock.
            Rectangle {
                visible: usageBar.entry && usageBar.entry.marker_rel !== null && usageBar.entry.marker_rel !== undefined
                x: Math.min(track.width - width, track.width * (usageBar.entry && usageBar.entry.marker_rel ? usageBar.entry.marker_rel : 0))
                width: 2
                height: track.height
                color: Kirigami.Theme.textColor
            }
        }
    }

    PlasmaComponents.Label {
        text: usageBar.entry ? usageBar.entry.reset_text : ''
        visible: text.length > 0
        opacity: 0.7
        elide: Text.ElideRight
        Layout.fillWidth: true
    }
}
