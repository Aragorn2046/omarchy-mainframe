import QtQuick

Rectangle {
  id: root
  signal finished()
  property color ink: "white"
  property color accent: "white"
  color: root.parent ? root.parent.color : "black"
  focus: true
  Keys.onShortcutOverride: function(event) { event.accepted = true }
  Keys.onPressed: function(event) { event.accepted = true; root.finished() }
  MouseArea { anchors.fill: parent; onPressed: root.finished() }
  Column {
    anchors.centerIn: parent; spacing: 10
    Text { textFormat: Text.PlainText; text: "MAINFRAME"; color: root.accent; font.family: "monospace"; font.pixelSize: 22; font.bold: true }
    Text { textFormat: Text.PlainText; text: "INITIALISING SYSTEMS..."; color: root.ink; font.family: "monospace"; font.pixelSize: 12 }
  }
  Timer { interval: 1200; running: true; onTriggered: root.finished() }
  Component.onCompleted: forceActiveFocus()
}
