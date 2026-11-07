import QtQuick

Item {
  id: root
  property color accent: "white"
  property bool glitchEnabled: false
  property bool sweepEnabled: false
  property alias glitchOffset: glitch.offset
  Loader {
    id: glitch
    objectName: "cyber-glitch-loader"
    property int offset: item ? item.offset : 0
    active: root.glitchEnabled
    sourceComponent: Item {
      property int offset: 0
      Timer { interval: 25000; repeat: true; running: true; onTriggered: { parent.offset = 2; reset.start() } }
      Timer { id: reset; interval: 180; onTriggered: parent.offset = 0 }
    }
  }
  Loader {
    objectName: "cyber-sweep-loader"
    anchors.fill: parent
    active: root.sweepEnabled
    sourceComponent: Item {
      id: sweep
      property int step: 0
      Rectangle { width: parent.width; height: 1; y: parent.height * parent.step / 15; color: root.accent; opacity: parent.step > 0 ? 0.35 : 0 }
      Timer { interval: 35000; repeat: true; running: true; onTriggered: { sweep.step = 1; travel.start() } }
      Timer { id: travel; interval: 100; repeat: true; onTriggered: { sweep.step++; if (sweep.step > 15) { stop(); sweep.step = 0 } } }
    }
  }
}
