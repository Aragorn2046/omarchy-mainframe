import QtQuick
import QtQuick.Shapes
import "lib/metrics.js" as Metrics

// The curve is a scene-graph path, not a Canvas image. A full-card Canvas
// repaint forced the software renderer to blend a large transparent buffer
// every sample. The geometry is the same quadratic stroke and fill.
Shape {
  id: canvas
  property var samples: []
  property var samplesB: []
  property color strokeColor: "#8a8f98"
  property color strokeColorB: "#6e8b8a"
  property real fillOpacity: 0.16
  // A flat series is a rectangle from the line to the baseline. Skip that
  // fill when the caller asks, so a full battery does not read as a solid bar.
  property bool strokeOnlyWhenFlat: false
  property real yMax: -1
  property real yMin: 0
  implicitHeight: 36
  antialiasing: false
  asynchronous: false
  preferredRendererType: Shape.SoftwareRenderer
  containsMode: Shape.BoundingRectContains

  property var paintedSamples: null
  property var paintedSamplesB: null
  property string fillSvg: ""
  property string strokeSvg: ""
  property string strokeSvgB: ""
  property real lastW: -1
  property real lastH: -1
  property real lastYMin: 0
  property real lastYMax: 0
  property bool built: false

  function cmdsToSvg(cmds) {
    var parts = []
    var n = cmds ? cmds.length : 0
    var i
    for (i = 0; i < n; i++) {
      var cmd = cmds[i]
      if (!cmd) continue
      if (cmd.t === "M") parts.push("M" + num(cmd.x) + " " + num(cmd.y))
      else if (cmd.t === "L") parts.push("L" + num(cmd.x) + " " + num(cmd.y))
      else if (cmd.t === "Q") parts.push("Q" + num(cmd.cx) + " " + num(cmd.cy) + " " + num(cmd.x) + " " + num(cmd.y))
      else if (cmd.t === "Z") parts.push("Z")
    }
    return parts.join("")
  }

  function num(v) {
    return Math.round(Number(v) * 100) / 100
  }

  function rebuild() {
    if (!visible) return
    if (width < 2 || height < 2) return
    var sameSeries = Metrics.seriesSame(samples, paintedSamples) && Metrics.seriesSame(samplesB, paintedSamplesB)
    var sameBox = canvas.lastW === width && canvas.lastH === height
        && canvas.lastYMin === yMin && canvas.lastYMax === yMax
    // Repaint only when a new point, or the box, would change the path.
    if (built && sameSeries && sameBox) return
    paintedSamples = samples
    paintedSamplesB = samplesB
    canvas.lastW = width
    canvas.lastH = height
    canvas.lastYMin = yMin
    canvas.lastYMax = yMax
    canvas.built = true

    var minv = yMin
    var maxv = yMax
    if (!(maxv > minv)) {
      maxv = seriesMax(samples, minv)
      maxv = seriesMax(samplesB, maxv)
      if (!(maxv > minv)) maxv = minv + 1
    }
    var primary = Metrics.buildSparkline(samples, width, height, minv, maxv, 60)
    var secondary = Metrics.buildSparkline(samplesB, width, height, minv, maxv, 60)
    fillSvg = cmdsToSvg(primary.fill)
    strokeSvg = cmdsToSvg(primary.stroke)
    strokeSvgB = cmdsToSvg(secondary.stroke)
  }

  function seriesFlat(list) {
    var n = list ? list.length : 0
    var base = null
    var i
    for (i = 0; i < n; i++) {
      var v = Number(list[i])
      if (!isFinite(v)) continue
      if (base == null) base = v
      else if (Math.abs(v - base) > 0.05) return false
    }
    return true
  }

  function seriesMax(list, current) {
    var n = list ? list.length : 0
    var maxv = current
    var i
    for (i = 0; i < n; i++) {
      var v = Number(list[i])
      if (isFinite(v) && v > maxv) maxv = v
    }
    return maxv
  }

  onSamplesChanged: rebuild()
  onSamplesBChanged: rebuild()
  onYMaxChanged: rebuild()
  onYMinChanged: rebuild()
  onWidthChanged: rebuild()
  onHeightChanged: rebuild()
  onVisibleChanged: rebuild()
  Component.onCompleted: rebuild()

  ShapePath {
    fillColor: (canvas.strokeOnlyWhenFlat && canvas.seriesFlat(canvas.samples))
      ? "transparent"
      : Qt.rgba(canvas.strokeColor.r, canvas.strokeColor.g, canvas.strokeColor.b, canvas.fillOpacity)
    strokeColor: "transparent"
    strokeWidth: 0
    PathSvg { path: canvas.fillSvg }
  }
  ShapePath {
    fillColor: "transparent"
    strokeColor: canvas.strokeColor
    strokeWidth: 1.6
    capStyle: ShapePath.RoundCap
    joinStyle: ShapePath.RoundJoin
    PathSvg { path: canvas.strokeSvg }
  }
  ShapePath {
    fillColor: "transparent"
    strokeColor: canvas.strokeColorB
    strokeWidth: 1.6
    capStyle: ShapePath.RoundCap
    joinStyle: ShapePath.RoundJoin
    PathSvg { path: canvas.strokeSvgB }
  }
}
