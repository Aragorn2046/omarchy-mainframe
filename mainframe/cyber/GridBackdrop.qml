import QtQuick

Item {
  id: root
  property color accent
  clip: true
  Repeater {
    model: Math.ceil(root.width / 40)
    Rectangle { required property int index; x: index * 40; width: 1; height: root.height; color: root.accent; opacity: 0.06 }
  }
  Repeater {
    model: Math.ceil(root.height / 4)
    Rectangle { required property int index; y: index * 4; width: root.width; height: 1; color: root.accent; opacity: index % 10 === 0 ? 0.06 : 0.025 }
  }
}
