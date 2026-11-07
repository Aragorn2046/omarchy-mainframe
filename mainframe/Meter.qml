import QtQuick
import "cyber" as Cyber

Rectangle {
  id: root
  property var cyberStyle: null
  property real fraction: 0
  property bool vertical: false
  property bool critical: fraction >= 0.9
  property color warningInk: "#cacccc"
  property color fill: "#8a8f98"
  property color track: "#2a2e33"
  implicitHeight: 14
  implicitWidth: vertical ? 14 : 48
  radius: vertical ? 3 : 2
  color: track
  clip: true

  // Snap to the sample. An 80 ms ease scheduled extra software frames and
  // pushed the offscreen dashboard over the CPU budget.
  property real shown: {
    var f = fraction
    if (!isFinite(f) || f < 0) f = 0
    if (f > 1) f = 1
    return Math.round(f * 100) / 100
  }

  Rectangle {
    id: bar
    visible: !(root.cyberStyle && root.cyberStyle.segmentedMeters)
    radius: parent.radius
    color: root.fill
    x: 0
    y: root.vertical ? Math.max(0, parent.height - height) : 0
    width: {
      var w = root.vertical ? parent.width : root.shown * parent.width
      if (!(w > 0)) return 0
      return w
    }
    height: {
      var h = root.vertical ? root.shown * parent.height : parent.height
      if (!(h > 0)) return 0
      return h
    }
  }
  Rectangle {
    anchors.fill: parent
    z: 1
    color: "transparent"
    radius: parent.radius
    border.width: root.critical ? 2 : 0
    border.color: root.warningInk
  }
  Loader {
    objectName: "cyber-segments-loader"
    anchors.fill: parent
    active: root.cyberStyle && root.cyberStyle.segmentedMeters
    sourceComponent: Cyber.Segments { fraction: root.shown; vertical: root.vertical; fill: root.fill; track: root.track }
  }
  Loader {
    objectName: "cyber-meter-glow-loader"
    anchors.fill: parent
    active: root.cyberStyle && root.cyberStyle.neonGlow
    sourceComponent: Cyber.GlowStroke {
      stroke: root.fill
      path: root.vertical ? "M0 " + (root.height * (1 - root.shown)) + " L" + root.width + " " + (root.height * (1 - root.shown)) : "M" + (root.width * root.shown) + " 0 L" + (root.width * root.shown) + " " + root.height
    }
  }
}
