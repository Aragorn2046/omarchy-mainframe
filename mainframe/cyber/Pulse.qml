import QtQuick

QtObject {
  property int sampleTick: 0
  readonly property real opacity: sampleTick % 2 ? 0.5 : 1.0
}
