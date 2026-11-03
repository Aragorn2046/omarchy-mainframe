import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.Button {
  id: control
  property color ink: "#cacccc"
  property color mutedInk: "#707880"
  property color accent: "#7aa2f7"
  property color cardColor: "#171b22"
  property color borderColor: "#14cacccc"
  implicitWidth: Math.max(30, contentItem.implicitWidth + leftPadding + rightPadding)
  implicitHeight: 30
  padding: 8
  font.family: "monospace"
  font.pixelSize: 15
  hoverEnabled: true
  contentItem: Text {
    textFormat: Text.PlainText
    text: control.text
    font: control.font
    color: control.enabled ? control.ink : control.mutedInk
    horizontalAlignment: Text.AlignHCenter
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
  }
  background: Rectangle {
    radius: 4
    color: control.hovered ? Qt.lighter(control.cardColor, 1.2) : control.cardColor
    border.width: 1
    border.color: control.down || control.checked || control.activeFocus ? control.accent : control.borderColor
  }
}
