import QtQuick
import QtQuick.Layouts
import "cyber" as Cyber
import "lib/agents.js" as Agents
import "lib/metrics.js" as Metrics

Item {
  id: root
  property var cyberStyle: null
  property alias flick: scrollView
  property var rows: []
  property color ink; property color mutedInk; property color accent; property color secondary
  property color cardColor; property color borderColor; property color track
  property color warning; property color critical
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
        objectName: "overview-repeater"
        model: root.rows.length
        delegate: Rectangle {
          id: card
          objectName: "overview-machine-card"
          required property int index
          readonly property var modelData: root.rows[index] || ({})
          readonly property var v: modelData.view || null
          readonly property var cpu: v && v.cpu ? v.cpu : null
          readonly property var cores: (cpu && cpu.cores) || []
          readonly property var mem: v && v.mem ? v.mem : null
          readonly property real minimumHeight: 134
          Layout.fillWidth: true
          Layout.preferredHeight: Math.max(minimumHeight, (root.height - Math.max(0, root.rows.length - 1) * 10) / Math.max(1, root.rows.length))
          radius: root.cyberStyle && root.cyberStyle.hudFrames ? 0 : 10; color: root.cardColor; border.width: root.cyberStyle && root.cyberStyle.hudFrames ? 0 : 1; border.color: root.borderColor; clip: true
          Loader { objectName: "cyber-hud-loader"; anchors.fill: parent; active: root.cyberStyle && root.cyberStyle.hudFrames; sourceComponent: Cyber.HudFrame { accent: root.accent } }
          ColumnLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 7
            RowLayout {
              Layout.fillWidth: true
              Rectangle {
                width: 8; height: 8; radius: 4; color: card.modelData.status === 'connected' ? root.accent : root.mutedInk
                opacity: pulse.item ? pulse.item.opacity : 1
                Loader { id: pulse; objectName: "cyber-dot-loader"; active: root.visible && root.cyberStyle && root.cyberStyle.windowActive && root.cyberStyle.pulsingStatusDots; sourceComponent: Cyber.Pulse { sampleTick: root.cyberStyle.sampleTick } }
              }
              Text { objectName: 'overview-title'; text: Agents.safeHelp(card.modelData.name); color: root.ink; textFormat: Text.PlainText; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 15; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
              Text { objectName: 'overview-badge'; textFormat: Text.PlainText; text: card.modelData.badge || ''; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }
              Text { textFormat: Text.PlainText; text: card.modelData.status || 'idle'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }
            }
            RowLayout {
              Layout.fillWidth: true; Layout.fillHeight: true; spacing: 20
              ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 4
                RowLayout {
                  objectName: "overview-cpu-row"
                  Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 0; clip: true
                  Cyber.DataText { cyberStyle: root.cyberStyle; objectName: "overview-cpu-value"; textFormat: Text.PlainText; sourceText: 'CPU  ' + (card.cpu ? card.cpu.percentText : '—'); color: root.ink; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 14; Layout.minimumWidth: implicitWidth; Layout.preferredWidth: implicitWidth }
                  Text { objectName: "overview-cpu-temperature"; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; elide: Text.ElideRight; textFormat: Text.PlainText; readonly property string temperatureText: card.cpu && typeof card.cpu.tempText === 'string' && card.cpu.tempText !== '—' && card.cpu.tempText !== 'n/a' ? card.cpu.tempText : ''; visible: temperatureText !== ''; text: temperatureText !== '' ? '  ' + temperatureText : ''; color: card.cpu && card.cpu.tempLevel === 'hot' ? root.critical : (card.cpu && card.cpu.tempLevel === 'warm' ? root.warning : root.ink); font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 14 }
                }
                Sparkline { cyberStyle: root.cyberStyle; objectName: "overview-cpu-sparkline"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 20; samples: card.cpu ? card.cpu.history : []; strokeColor: root.accent; ink: root.ink; mutedInk: root.mutedInk; tooltipBg: root.cardColor; yMax: 100 }
                Row {
                  Layout.fillWidth: true; spacing: 2; clip: true
                  Repeater {
                    objectName: "overview-cores-repeater"
                    model: card.cores.length
                    delegate: Rectangle {
                      required property int index
                      readonly property var modelData: card.cores[index] || ({percent: 0})
                      width: Math.max(1, Math.min(10, (parent.width - Math.max(0, card.cores.length - 1) * 2) / Math.max(1, card.cores.length)))
                      height: 7; color: root.accent; opacity: Math.max(0.15, Math.min(1, (Number(modelData.percent) || 0) / 100))
                    }
                  }
                }
              }
              ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: 'MEM  ' + (card.mem ? card.mem.usedText : '—'); color: root.ink; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 14; elide: Text.ElideRight }
                Text { textFormat: Text.PlainText; text: card.mem && card.mem.usedText !== '—' && card.mem.usedText !== 'n/a' ? Math.round(card.mem.fraction * 100) + '%' : '—'; color: root.ink; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 14 }
                Meter { cyberStyle: root.cyberStyle; Layout.fillWidth: true; implicitHeight: 7; fraction: card.mem ? card.mem.fraction : 0; fill: root.secondary; track: root.track; critical: false }
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
