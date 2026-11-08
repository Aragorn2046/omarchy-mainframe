import QtQuick

Item {
  id: root
  property real fraction: 0
  property bool vertical: false
  property color fill
  property color track
  readonly property int count: Math.max(1, Math.min(40, Math.floor((vertical ? height : width) / 7)))
  Repeater {
    model: root.count
    Rectangle {
      required property int index
      readonly property real step: (root.vertical ? root.height : root.width) / root.count
      x: root.vertical ? 0 : index * step
      y: root.vertical ? root.height - (index + 1) * step : 0
      width: root.vertical ? root.width : Math.max(1, step - 2)
      height: root.vertical ? Math.max(1, step - 2) : root.height
      color: (index + 0.5) / root.count <= root.fraction ? root.fill : root.track
    }
  }
}
