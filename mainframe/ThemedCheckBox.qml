import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.CheckBox {
  id: control
  property color ink: "#cacccc"
  property color mutedInk: "#707880"
  property color accent: "#7aa2f7"
  property color cardColor: "#171b22"
  property color borderColor: "#14cacccc"
  implicitWidth: contentItem.implicitWidth
  implicitHeight: 30
  spacing: 8
  padding: 0
  font.family: "monospace"
  font.pixelSize: 15
  hoverEnabled: true
  indicator: Rectangle {
    x: control.leftPadding
    y: (control.height - height) / 2
    width: 18; height: 18; radius: 4
    color: control.hovered ? Qt.lighter(control.cardColor, 1.2) : control.cardColor
    border.width: 1
    border.color: control.down || control.checked || control.activeFocus ? control.accent : control.borderColor
    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: control.checked ? "✓" : ""
      color: control.enabled ? control.accent : control.mutedInk
      font.family: "monospace"
      font.pixelSize: 15
      font.bold: true
    }
  }
  contentItem: Text {
    textFormat: Text.PlainText
    leftPadding: control.indicator.width + control.spacing
    text: control.text
    font: control.font
    color: control.enabled ? control.ink : control.mutedInk
    verticalAlignment: Text.AlignVCenter
  }
}
