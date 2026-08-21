/*
 * Detail popup - the panel anchors and animates it, so nothing here deals
 * with positioning.  That is the whole reason the Linux frontend is a
 * plasmoid rather than a stand-alone window: under Wayland a client cannot
 * place itself next to the tray icon, but code running inside plasmashell
 * gets it for free.
 *
 * The section order mirrors the Windows popup: account, usage, extra usage,
 * Claude Code versions, server status, and a footer carrying the live
 * refresh countdown.
 */
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: popup

    property var snapshot: null
    signal refreshRequested()

    readonly property var labels: snapshot ? snapshot.labels : null
    readonly property var profile: snapshot ? snapshot.profile : null
    readonly property var status: snapshot ? snapshot.status : null
    readonly property var serverStatus: snapshot ? snapshot.anthropic_status : null

    Layout.minimumWidth: Kirigami.Units.gridUnit * 21
    Layout.preferredWidth: Kirigami.Units.gridUnit * 24
    Layout.minimumHeight: Kirigami.Units.gridUnit * 22
    Layout.preferredHeight: Kirigami.Units.gridUnit * 28

    collapseMarginsHint: true

    function label(key) {
        return popup.labels && popup.labels[key] ? popup.labels[key] : '';
    }

    header: PlasmaExtras.PlasmoidHeading {
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            PlasmaExtras.Heading {
                level: 4
                text: popup.label('title')
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            PlasmaComponents.ToolButton {
                icon.name: 'view-refresh'
                display: PlasmaComponents.AbstractButton.IconOnly
                text: popup.label('status_refreshing')
                onClicked: popup.refreshRequested()
            }
        }
    }

    contentItem: PlasmaComponents.ScrollView {
        id: scrollView

        // Cuts the sizing cycle: Page derives its implicitWidth from this item,
        // while the content inside is laid out against this item's width.  With
        // the content also defining the implicit width, the two chase each
        // other.  The popup's real width comes from Layout.preferredWidth above.
        implicitWidth: Kirigami.Units.gridUnit * 24

        contentWidth: availableWidth

        // Without explicit padding the sections sit flush against the popup
        // frame, which the panel does not add any margin of its own to.
        leftPadding: Kirigami.Units.largeSpacing
        rightPadding: Kirigami.Units.largeSpacing
        topPadding: Kirigami.Units.smallSpacing
        bottomPadding: Kirigami.Units.largeSpacing

        ColumnLayout {
            width: scrollView.availableWidth
            spacing: Kirigami.Units.largeSpacing * 1.5

            // Account
            ColumnLayout {
                visible: popup.profile !== null
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                SectionHeading { text: popup.label('account') }

                GridLayout {
                    columns: 2
                    rowSpacing: 0
                    columnSpacing: Kirigami.Units.largeSpacing
                    Layout.fillWidth: true

                    PlasmaComponents.Label {
                        text: popup.label('email')
                        opacity: 0.7
                    }

                    PlasmaComponents.Label {
                        text: popup.profile ? popup.profile.email : ''
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignRight
                        Layout.fillWidth: true
                    }

                    PlasmaComponents.Label {
                        text: popup.label('plan')
                        opacity: 0.7
                    }

                    PlasmaComponents.Label {
                        text: popup.profile ? popup.profile.plan : ''
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignRight
                        Layout.fillWidth: true
                    }
                }
            }

            // Usage
            ColumnLayout {
                visible: popup.snapshot && popup.snapshot.usage.length > 0
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                SectionHeading { text: popup.label('usage') }

                Repeater {
                    model: popup.snapshot ? popup.snapshot.usage : []

                    UsageBar {
                        entry: modelData
                        Layout.fillWidth: true
                    }
                }
            }

            // Paid extra usage, when the account has it enabled
            ColumnLayout {
                visible: popup.snapshot && popup.snapshot.extra !== null
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                SectionHeading { text: popup.label('extra_usage') }

                UsageBar {
                    entry: popup.snapshot && popup.snapshot.extra ? {
                        'label': popup.snapshot.extra.spent_text,
                        'pct_text': popup.snapshot.extra.pct_text,
                        'fill_pct': popup.snapshot.extra.fill_pct,
                        'warn': false,
                        'reset_text': '',
                        'dividers': [],
                        'marker_rel': null
                    } : null
                    Layout.fillWidth: true
                }
            }

            // Installed Claude Code versions
            ColumnLayout {
                visible: popup.snapshot && popup.snapshot.installations.length > 0
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true

                    SectionHeading {
                        text: popup.label('claude_code')
                        Layout.fillWidth: true
                    }

                    PlasmaComponents.Label {
                        text: '<a href="' + (popup.snapshot ? popup.snapshot.links.changelog : '') + '">' + popup.label('changelog') + '</a>'
                        textFormat: Text.RichText
                        onLinkActivated: link => Qt.openUrlExternally(link)

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.NoButton
                            cursorShape: Qt.PointingHandCursor
                        }
                    }
                }

                Repeater {
                    model: popup.snapshot ? popup.snapshot.installations : []

                    RowLayout {
                        Layout.fillWidth: true

                        PlasmaComponents.Label {
                            text: modelData.name
                            opacity: 0.7
                            Layout.fillWidth: true
                        }

                        PlasmaComponents.Label {
                            text: modelData.version
                        }
                    }
                }
            }

            // Anthropic server status
            ColumnLayout {
                visible: popup.serverStatus !== null
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                SectionHeading { text: popup.label('anthropic_status') }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Rectangle {
                        implicitWidth: Kirigami.Units.gridUnit * 0.5
                        implicitHeight: implicitWidth
                        radius: width / 2
                        color: popup.serverStatus && popup.serverStatus.indicator === 'none'
                            ? Kirigami.Theme.positiveTextColor
                            : Kirigami.Theme.neutralTextColor
                    }

                    PlasmaComponents.Label {
                        text: popup.serverStatus ? popup.serverStatus.text : ''
                        elide: Text.ElideRight
                        Layout.fillWidth: true

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Qt.openUrlExternally(popup.snapshot.links.status_page)
                        }
                    }
                }

                PlasmaComponents.Label {
                    visible: text.length > 0
                    text: popup.serverStatus && popup.serverStatus.incident ? popup.serverStatus.incident : ''
                    opacity: 0.7
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Item { Layout.fillHeight: true }
        }
    }

    footer: PlasmaExtras.PlasmoidHeading {
        position: PlasmaExtras.PlasmoidHeading.Position.Footer

        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents.Label {
                id: statusLabel
                color: popup.status && popup.status.is_error ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                opacity: 0.8
                font: Kirigami.Theme.smallFont
                elide: Text.ElideRight
                Layout.fillWidth: true

                text: popup.formatStatus()
            }

            PlasmaComponents.Label {
                text: popup.snapshot ? popup.snapshot.app_version : ''
                opacity: 0.5
                font: Kirigami.Theme.smallFont
            }
        }
    }

    // The footer counts up from the last fetch and down to the next one, so it
    // has to tick locally - the daemon only sends the two timestamps.
    Timer {
        interval: 1000
        running: popup.visible
        repeat: true
        onTriggered: statusLabel.text = popup.formatStatus()
    }

    function formatStatus() {
        if (!popup.status) {
            return '';
        }
        if (popup.status.is_error) {
            return popup.status.text;
        }
        if (popup.status.refreshing && !popup.status.last_success_time) {
            return popup.label('status_refreshing');
        }
        if (popup.status.error) {
            return popup.status.error;
        }

        const now = Date.now() / 1000;
        let text = '';

        if (popup.status.last_success_time) {
            const elapsed = Math.max(0, Math.round(now - popup.status.last_success_time));
            text = elapsed < 60
                ? popup.label('status_updated_s').replace('{s}', elapsed)
                : popup.label('status_updated').replace('{duration}', popup.formatDuration(elapsed));
        }

        if (popup.status.next_poll_time) {
            const remaining = Math.max(0, Math.round(popup.status.next_poll_time - now));
            const next = popup.label('status_next_update').replace('{duration}', popup.formatDuration(remaining));
            text = text ? text + ' · ' + next : next;
        }

        return text;
    }

    function formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);

        if (hours > 0) {
            return popup.label('duration_hm').replace('{h}', hours).replace('{m}', minutes);
        }
        if (minutes > 0) {
            return popup.label('duration_m').replace('{m}', minutes);
        }

        return popup.label('duration_s').replace('{s}', seconds);
    }
}
