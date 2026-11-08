import QtQuick
import QtQuick.Window

Rectangle {
  id: root
  signal finished()
  property color ink: "white"
  property color accent: "white"
  color: root.parent ? root.parent.color : "black"
  property var previousFocus: null
  property bool done: false
  function finish() {
    if (done) return
    done = true
    if (previousFocus) previousFocus.forceActiveFocus()
    root.finished()
  }
  Keys.onShortcutOverride: function(event) { event.accepted = true }
  Keys.onPressed: function(event) { event.accepted = true; root.finish() }
  MouseArea { anchors.fill: parent; onPressed: root.finish() }
  Column {
    anchors.centerIn: parent; spacing: 10
    Text { textFormat: Text.PlainText; text: "MAINFRAME"; color: root.accent; font.family: "monospace"; font.pixelSize: 22; font.bold: true }
    Text { textFormat: Text.PlainText; text: "INITIALISING SYSTEMS..."; color: root.ink; font.family: "monospace"; font.pixelSize: 12 }
  }
  Timer { interval: 1200; running: true; onTriggered: root.finish() }
  Component.onCompleted: {
    previousFocus = root.Window.window ? root.Window.window.activeFocusItem : null
    forceActiveFocus()
  }
  Component.onDestruction: if (!done && previousFocus && activeFocus) previousFocus.forceActiveFocus()
}
