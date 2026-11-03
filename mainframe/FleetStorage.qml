import QtQuick
import QtQuick.Layouts
import "lib/metrics.js" as Metrics
import "lib/agents.js" as Agents
import "lib/fleet_storage.js" as StorageModel

Item {
  id: root
  property var rows: []
  property color ink; property color mutedInk; property color accent; property color warning; property color critical
  property color cardColor; property color borderColor; property color track
  function checkLayout() { return column.width > width + 1 ? 1 : 0 }
  Flickable {
    anchors.fill: parent; clip: true; contentWidth: width; contentHeight: column.implicitHeight
    ColumnLayout {
      id: column; width: parent.width; spacing: 8
      Repeater {
        model: root.rows
        delegate: Rectangle {
          required property var modelData
          readonly property var disks: modelData.view && modelData.view.filesystems ? modelData.view.filesystems : []
          Layout.fillWidth: true; Layout.preferredHeight: body.implicitHeight + 20
          radius: 10; color: root.cardColor; border.color: root.borderColor
          ColumnLayout {
            id: body; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 5
            RowLayout {
              Layout.fillWidth: true
              Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Agents.safeHelp(modelData.name); color: root.ink; font.family: 'monospace'; font.bold: true; font.pixelSize: 14; elide: Text.ElideRight }
              Text { textFormat: Text.PlainText; text: modelData.status || 'idle'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11 }
            }
            Text { textFormat: Text.PlainText; visible: disks.length === 0; text: 'No storage data'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11 }
            Repeater {
              model: disks
              delegate: RowLayout {
                required property var modelData
                readonly property var cue: StorageModel.cue(modelData.used, modelData.total)
                readonly property real fraction: cue.fraction
                Layout.fillWidth: true; spacing: 10
                RowLayout {
                  Layout.preferredWidth: Math.min(220, root.width * 0.23); spacing: 5
                  Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Agents.safeHelp(StorageModel.rowLabel(modelData)); color: root.ink; font.family: 'monospace'; font.pixelSize: 12; elide: Text.ElideMiddle }
                  Text { textFormat: Text.PlainText; visible: !!modelData.bus && modelData.bus !== 'Internal'; text: Agents.safeHelp(modelData.bus || ''); color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10 }
                }
                Meter { Layout.fillWidth: true; implicitHeight: 7; fraction: parent.fraction; fill: parent.fraction >= 0.95 ? root.critical : parent.fraction >= 0.85 ? root.warning : root.accent; track: root.track; critical: parent.fraction >= 0.95; warningInk: root.ink }
                Text { textFormat: Text.PlainText; Layout.preferredWidth: 190; horizontalAlignment: Text.AlignRight; text: Metrics.formatUsage(modelData.used, modelData.total) + '  ' + Math.round(parent.fraction * 100) + '%' + (parent.cue.symbol ? ' ' + parent.cue.symbol : ''); color: root.ink; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideLeft }
              }
            }
          }
        }
      }
    }
  }
}
