import QtQuick

Item {
  id: root
  property color accent
  property real length: 14
  Rectangle { x: 0; y: 0; width: root.width; height: 1; color: root.accent; opacity: 0.25 }
  Repeater {
    model: 8
    Rectangle {
      required property int index
      readonly property bool horizontal: index % 2 === 0
      readonly property bool rightSide: index >= 4
      readonly property bool bottomSide: index % 4 >= 2
      x: rightSide ? root.width - width : 0
      y: bottomSide ? root.height - height : 0
      width: horizontal ? Math.min(root.length, root.width / 2) : 1
      height: horizontal ? 1 : Math.min(root.length, root.height / 2)
      color: root.accent
    }
  }
}
