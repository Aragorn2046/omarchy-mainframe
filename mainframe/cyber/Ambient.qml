import QtQuick

Item {
  id: root
  property color accent: "white"
  property bool glitchEnabled: false
  property bool sweepEnabled: false
  property bool smokeAmbientNow: false
  readonly property int glitchInterval: 25000
  readonly property int glitchDuration: 180
  readonly property int sweepInterval: 35000
  readonly property int sweepDuration: 1600
  readonly property int glitchOffset: glitch.item ? glitch.item.offset : 0
  readonly property bool sweeping: sweepLoader.item ? sweepLoader.item.sweeping : false
  Loader {
    id: glitch
    objectName: "cyber-glitch-loader"
    active: root.glitchEnabled
    sourceComponent: Item {
      id: glitchItem
      property int offset: 0
      function startGlitch() {
        offset = 2; reset.restart()
        if (root.smokeAmbientNow) console.log("AMBIENT glitch t=" + Date.now())
      }
      Timer { objectName: "cyber-glitch-timer"; interval: root.glitchInterval; repeat: true; running: true; onTriggered: glitchItem.startGlitch() }
      Timer { interval: 8000; running: root.smokeAmbientNow; onTriggered: glitchItem.startGlitch() }
      Timer { id: reset; objectName: "cyber-glitch-reset"; interval: root.glitchDuration; onTriggered: glitchItem.offset = 0 }
    }
  }
  Loader {
    id: sweepLoader
    objectName: "cyber-sweep-loader"
    anchors.fill: parent
    active: root.sweepEnabled
    sourceComponent: Item {
      id: sweep
      readonly property bool sweeping: travel.running
      function startSweep() {
        travel.restart()
        if (root.smokeAmbientNow) console.log("AMBIENT sweep t=" + Date.now())
      }
      Item {
        id: band
        objectName: "cyber-sweep-band"
        width: parent.width; height: 33
        visible: sweep.sweeping
        Rectangle {
          width: parent.width; height: 32
          gradient: Gradient {
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 1; color: root.accent }
          }
          opacity: 0.16
        }
        Rectangle { y: 32; width: parent.width; height: 1; color: root.accent; opacity: 0.45 }
      }
      Timer { objectName: "cyber-sweep-timer"; interval: root.sweepInterval; repeat: true; running: true; onTriggered: sweep.startSweep() }
      Timer { interval: 10000; running: root.smokeAmbientNow; onTriggered: sweep.startSweep() }
      NumberAnimation { id: travel; objectName: "cyber-sweep-travel"; target: band; property: "y"; from: -band.height - 1; to: sweep.height + 1; duration: root.sweepDuration; easing.type: Easing.InOutSine }
    }
  }
}
