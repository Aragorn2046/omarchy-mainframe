import QtQuick
import "cyber" as Cyber

Rectangle {
  id: root
  property var cyberStyle: null
  property color accent: borderColor
  property bool clickable: false
  signal activated()
  property string title: ""
  property string hint: ""
  property color hintColor: "#e06c75"
  property color labelColor: "#9aa0a6"
  property color borderColor: "#2a2e33"
  property int titleSize: 12
  radius: cyberStyle && cyberStyle.hudFrames ? 0 : 10
  border.width: cyberStyle && cyberStyle.hudFrames ? 0 : 1
  border.color: borderColor
  clip: true

  Loader {
    objectName: "cyber-hud-loader"
    anchors.fill: parent
    active: root.cyberStyle && root.cyberStyle.hudFrames
    sourceComponent: Cyber.HudFrame { accent: root.accent }
  }
  default property alias contentData: body.data

  Text {
    id: hintText
    visible: root.hint !== ""
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.rightMargin: 12
    anchors.topMargin: 10
    text: root.hint
    textFormat: Text.PlainText
    color: root.hintColor
    font.family: "monospace"
    font.pixelSize: root.titleSize
    elide: Text.ElideLeft
  }

  Text {
    id: heading
    objectName: "metric-label"
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.leftMargin: 12
    anchors.rightMargin: hintText.visible ? (hintText.implicitWidth + 8) : 12
    anchors.topMargin: 10
    text: root.cyberStyle && root.cyberStyle.hudFrames ? root.title.toUpperCase() : root.title
    textFormat: Text.PlainText
    color: root.labelColor
    font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : "monospace"
    font.pixelSize: root.titleSize
    font.letterSpacing: 0.6
    elide: Text.ElideRight
  }

  MouseArea { anchors.fill: parent; z: 100; enabled: root.clickable; cursorShape: Qt.PointingHandCursor; onClicked: root.activated() }

  Item {
    id: body
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: heading.bottom
    anchors.bottom: parent.bottom
    anchors.leftMargin: 12
    anchors.rightMargin: 12
    anchors.topMargin: 6
    anchors.bottomMargin: 12
  }
}
