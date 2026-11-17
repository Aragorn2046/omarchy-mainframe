import QtQuick

Item {
  id: root
  property color accent: "white"
  property bool glitchEnabled: false
  property bool sweepEnabled: false
  property bool smokeAmbientNow: false
  property var sweepNow: function() { return Date.now() }
  readonly property int glitchInterval: 25000
  readonly property int glitchDuration: 180
  readonly property int sweepInterval: 30000
  readonly property int sweepDuration: 8000
  readonly property int sweepStepInterval: 80
  readonly property real sweepPeak: 0.05
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
      clip: true
      readonly property bool sweeping: travel.running
      property double startTime: 0
      function startSweep() {
        startTime = root.sweepNow()
        band.y = -band.height
        travel.restart()
        if (root.smokeAmbientNow) console.log("AMBIENT sweep t=" + Date.now())
      }
      Rectangle {
        id: band
        objectName: "cyber-sweep-band"
        width: parent.width; height: Math.max(80, Math.min(220, sweep.height * 0.14))
        y: -height
        visible: sweep.sweeping
        gradient: Gradient {
          GradientStop { position: 0; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0) }
          GradientStop { position: 0.5; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, root.sweepPeak) }
          GradientStop { position: 1; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0) }
        }
      }
      Timer { objectName: "cyber-sweep-timer"; interval: root.sweepInterval; repeat: true; running: true; onTriggered: sweep.startSweep() }
      Timer { interval: 10000; running: root.smokeAmbientNow; onTriggered: sweep.startSweep() }
      Timer {
        id: travel
        objectName: "cyber-sweep-travel"
        interval: root.sweepStepInterval
        repeat: true
        onTriggered: {
          var progress = Math.max(0, Math.min(1, (root.sweepNow() - sweep.startTime) / root.sweepDuration))
          band.y = -band.height + progress * (sweep.height + band.height)
          if (progress >= 1) {
            stop()
            band.y = -band.height
          }
        }
      }
    }
  }
}
