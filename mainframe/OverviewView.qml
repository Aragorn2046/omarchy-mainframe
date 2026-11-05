import QtQuick
import QtQuick.Layouts
import "lib/agents.js" as Agents

Item {
  id: root
  property alias flick: scrollView
  property var rows: []
  property color ink; property color mutedInk; property color accent; property color secondary
  property color cardColor; property color borderColor; property color track
  signal openMachine(int index)
  function checkLayout() {
    var failures = 0
    for (var i = 0; i < repeater.count; i++) { var c = repeater.itemAt(i); if (c && (c.width > width + 1 || c.height < c.minimumHeight - 1)) failures++ }
    return failures
  }
  Flickable {
    id: scrollView
    anchors.fill: parent
    contentWidth: width
    contentHeight: Math.max(height, column.implicitHeight)
    clip: true
    ColumnLayout {
      id: column
      width: parent.width
      spacing: 10
      Repeater {
        id: repeater
        model: root.rows
        delegate: Rectangle {
          id: card
          objectName: "overview-machine-card"
          required property var modelData
          readonly property var v: modelData.view || null
          readonly property var cpu: v && v.cpu ? v.cpu : null
          readonly property var mem: v && v.mem ? v.mem : null
          readonly property real minimumHeight: 134
          Layout.fillWidth: true
          Layout.preferredHeight: Math.max(minimumHeight, (root.height - Math.max(0, root.rows.length - 1) * 10) / Math.max(1, root.rows.length))
          radius: 10; color: root.cardColor; border.color: root.borderColor; clip: true
          ColumnLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 7
            RowLayout {
              Layout.fillWidth: true
              Rectangle { width: 8; height: 8; radius: 4; color: card.modelData.status === 'connected' ? root.accent : root.mutedInk }
              Text { text: Agents.safeHelp(card.modelData.name); color: root.ink; textFormat: Text.PlainText; font.family: 'monospace'; font.pixelSize: 15; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
              Text { textFormat: Text.PlainText; text: card.modelData.badge; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }
              Text { textFormat: Text.PlainText; text: card.modelData.status || 'idle'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }
            }
            RowLayout {
              Layout.fillWidth: true; Layout.fillHeight: true; spacing: 20
              ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 4
                Text { textFormat: Text.PlainText; text: 'CPU  ' + (card.cpu ? card.cpu.percentText : '—'); color: root.ink; font.family: 'monospace'; font.pixelSize: 14 }
                Sparkline { objectName: "overview-cpu-sparkline"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 20; samples: card.cpu ? card.cpu.history : []; strokeColor: root.accent; ink: root.ink; mutedInk: root.mutedInk; tooltipBg: root.cardColor; yMax: 100 }
                Row {
                  Layout.fillWidth: true; spacing: 2; clip: true
                  Repeater {
                    model: card.cpu ? card.cpu.cores : []
                    delegate: Rectangle {
                      required property var modelData
                      width: Math.max(1, Math.min(10, (parent.width - Math.max(0, (card.cpu ? card.cpu.cores.length : 0) - 1) * 2) / Math.max(1, card.cpu ? card.cpu.cores.length : 1)))
                      height: 7; color: root.accent; opacity: Math.max(0.15, Math.min(1, (Number(modelData.percent) || 0) / 100))
                    }
                  }
                }
              }
              ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: 'MEM  ' + (card.mem ? card.mem.usedText : '—'); color: root.ink; font.family: 'monospace'; font.pixelSize: 14; elide: Text.ElideRight }
                Text { textFormat: Text.PlainText; text: card.mem && card.mem.usedText !== '—' && card.mem.usedText !== 'n/a' ? Math.round(card.mem.fraction * 100) + '%' : '—'; color: root.ink; font.family: 'monospace'; font.pixelSize: 14 }
                Meter { Layout.fillWidth: true; implicitHeight: 7; fraction: card.mem ? card.mem.fraction : 0; fill: root.secondary; track: root.track; critical: false }
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: 'swap  ' + (card.mem ? card.mem.swapText : '—'); color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight }
              }
            }
          }
          MouseArea { anchors.fill: parent; z: -1; onClicked: root.openMachine(card.modelData.index) }
          TapHandler { onTapped: root.openMachine(card.modelData.index) }
        }
      }
    }
  }
}
