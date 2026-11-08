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
  readonly property int sweepStepInterval: 300
  readonly property int sweepSteps: 5
  readonly property int glitchOffset: glitch.item ? glitch.item.offset : 0
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
      property int step: 0
      function startSweep() {
        step = 1; travel.restart()
        if (root.smokeAmbientNow) console.log("AMBIENT sweep t=" + Date.now())
      }
      Rectangle { width: parent.width; height: 1; y: parent.height * parent.step / root.sweepSteps; color: root.accent; opacity: parent.step > 0 ? 0.35 : 0 }
      Timer { objectName: "cyber-sweep-timer"; interval: root.sweepInterval; repeat: true; running: true; onTriggered: sweep.startSweep() }
      Timer { interval: 10000; running: root.smokeAmbientNow; onTriggered: sweep.startSweep() }
      Timer { id: travel; objectName: "cyber-sweep-travel"; interval: root.sweepStepInterval; repeat: true; onTriggered: { sweep.step++; if (sweep.step > root.sweepSteps) { stop(); sweep.step = 0 } } }
    }
  }
}
