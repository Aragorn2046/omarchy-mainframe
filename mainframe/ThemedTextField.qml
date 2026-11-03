import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.TextField {
  id: control
  property color ink: "#cacccc"
  property color mutedInk: "#707880"
  property color accent: "#7aa2f7"
  property color cardColor: "#171b22"
  property color borderColor: "#14cacccc"
  implicitHeight: 30
  leftPadding: 8
  rightPadding: 8
  font.family: "monospace"
  font.pixelSize: 15
  color: enabled ? ink : mutedInk
  placeholderTextColor: mutedInk
  selectionColor: accent
  selectedTextColor: cardColor
  hoverEnabled: true
  background: Rectangle {
    radius: 4
    color: control.hovered ? Qt.lighter(control.cardColor, 1.2) : control.cardColor
    border.width: 1
    border.color: control.activeFocus ? control.accent : control.borderColor
  }
}
