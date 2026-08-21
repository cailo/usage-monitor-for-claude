/*
 * Small uppercase section heading, matching the Windows popup's sections.
 *
 * The weight is set as `font.bold` rather than by assigning a whole `font`
 * group: doing both in one object is invalid QML and makes the component
 * fail to load without reporting an error.
 */
import QtQuick
import org.kde.plasma.components as PlasmaComponents

PlasmaComponents.Label {
    font.bold: true
    opacity: 0.55
    elide: Text.ElideRight
}
