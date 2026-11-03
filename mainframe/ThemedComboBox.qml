import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.ComboBox {
  id: control
  property color ink: "#cacccc"
  property color mutedInk: "#707880"
  property color accent: "#7aa2f7"
  property color cardColor: "#171b22"
  property color borderColor: "#14cacccc"
  implicitWidth: Math.max(80, contentItem.implicitWidth + leftPadding + rightPadding)
  implicitHeight: 30
  leftPadding: 8
  rightPadding: 30
  font.family: "monospace"
  font.pixelSize: 15
  hoverEnabled: true
  contentItem: Text {
    textFormat: Text.PlainText
    text: control.displayText
    font: control.font
    color: control.enabled ? control.ink : control.mutedInk
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
  }
  indicator: Text {
    textFormat: Text.PlainText
    x: control.width - width - 8
    y: (control.height - height) / 2
    text: "▾"
    font: control.font
    color: control.enabled ? control.ink : control.mutedInk
  }
  background: Rectangle {
    radius: 4
    color: control.hovered ? Qt.lighter(control.cardColor, 1.2) : control.cardColor
    border.width: 1
    border.color: control.down || control.activeFocus || control.popup.visible ? control.accent : control.borderColor
  }
  delegate: Basic.ItemDelegate {
    required property int index
    width: control.popup.width
    implicitHeight: 30
    highlighted: control.highlightedIndex === index
    hoverEnabled: true
    contentItem: Text {
      textFormat: Text.PlainText
      text: control.textRole ? control.model[index][control.textRole] : control.model[index]
      font: control.font
      color: control.enabled ? control.ink : control.mutedInk
      verticalAlignment: Text.AlignVCenter
      elide: Text.ElideRight
    }
    background: Rectangle {
      color: parent.highlighted ? control.accent : parent.hovered ? Qt.lighter(control.cardColor, 1.2) : control.cardColor
      border.width: 1
      border.color: parent.highlighted ? control.accent : control.borderColor
      radius: 4
    }
  }
  popup: Basic.Popup {
    y: control.height
    width: control.width
    implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, 240)
    padding: 1
    contentItem: ListView {
      clip: true
      implicitHeight: contentHeight
      model: control.popup.visible ? control.delegateModel : null
      currentIndex: control.highlightedIndex
    }
    background: Rectangle {
      color: control.cardColor
      border.width: 1
      border.color: control.borderColor
      radius: 4
    }
  }
}
