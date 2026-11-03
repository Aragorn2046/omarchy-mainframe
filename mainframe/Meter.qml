import QtQuick

Rectangle {
  id: root
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
    color: "transparent"
    radius: parent.radius
    border.width: root.critical ? 2 : 0
    border.color: root.warningInk
  }
}
