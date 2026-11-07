pragma ComponentBehavior: Bound
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
  property color ink: "#cacccc"
  property color mutedInk: "#8a8f98"
  property color tooltipBg: "#171b22"
  property string labelA: ""
  property string labelB: ""
  property bool rateChart: false
  readonly property bool steady: Metrics.seriesFlat(paintedSamples) && (!(paintedSamplesB && paintedSamplesB.length) || Metrics.seriesFlat(paintedSamplesB))
  property real plotMax: 1
  property real hoverX: -1
  property int hoverIndex: -1
  function pointY(value) {
    return Math.max(0, Math.min(height - 1, height - ((Number(value) - yMin) / (plotMax - yMin)) * (height - 3) - 1.5))
  }
  function displayValue(value) { return rateChart ? Metrics.formatRate(value) : Math.round(Number(value) * 10) / 10 + "%" }
  function hit(x) {
    var count = Math.min(60, paintedSamples ? paintedSamples.length : 0)
    if (!count) return -1
    var slot = Math.round(Math.max(0, Math.min(width, x)) / Math.max(1, width) * 59)
    return Math.max(0, Math.min(count - 1, slot - (60 - count))) + Math.max(0, paintedSamples.length - 60)
  }
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
    // A steady chart draws only its label. Its hidden paths need no geometry.
    if (Metrics.seriesFlat(samples) && (!(samplesB && samplesB.length) || Metrics.seriesFlat(samplesB))) {
      paintedSamples = samples
      paintedSamplesB = samplesB
      built = false
      return
    }
    var sameSeries = Metrics.seriesSame(samples, paintedSamples) && Metrics.seriesSame(samplesB, paintedSamplesB)
    var sameBox = canvas.lastW === width && canvas.lastH === height
        && canvas.lastYMin === yMin && canvas.lastYMax === yMax
    // Repaint only when a new point, or the box, would change the path.
    if (built && sameSeries && sameBox) return
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
    plotMax = maxv
    var primary = Metrics.buildSparkline(samples, width, height, minv, maxv, 60)
    var secondary = Metrics.buildSparkline(samplesB, width, height, minv, maxv, 60)
    var fillPath = cmdsToSvg(primary.fill)
    var strokePath = cmdsToSvg(primary.stroke)
    var strokePathB = cmdsToSvg(secondary.stroke)
    if (fillSvg !== fillPath) fillSvg = fillPath
    if (strokeSvg !== strokePath) strokeSvg = strokePath
    if (strokeSvgB !== strokePathB) strokeSvgB = strokePathB
    paintedSamples = samples
    paintedSamplesB = samplesB
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

  // Both series and dimensions can change in one sample. Coalesce them into
  // a single rebuild after the current batch of bindings has settled.
  function scheduleRebuild() { Qt.callLater(rebuild) }
  onSamplesChanged: scheduleRebuild()
  onSamplesBChanged: scheduleRebuild()
  onYMaxChanged: scheduleRebuild()
  onYMinChanged: scheduleRebuild()
  onWidthChanged: scheduleRebuild()
  onHeightChanged: scheduleRebuild()
  onVisibleChanged: scheduleRebuild()
  Component.onCompleted: scheduleRebuild()

  ShapePath {
    fillColor: (canvas.steady || (canvas.strokeOnlyWhenFlat && canvas.seriesFlat(canvas.paintedSamples)))
      ? "transparent"
      : Qt.rgba(canvas.strokeColor.r, canvas.strokeColor.g, canvas.strokeColor.b, canvas.fillOpacity)
    strokeColor: "transparent"
    strokeWidth: 0
    PathSvg { path: canvas.fillSvg }
  }
  ShapePath {
    fillColor: "transparent"
    strokeColor: canvas.steady ? "transparent" : canvas.strokeColor
    strokeWidth: 1.6
    capStyle: ShapePath.RoundCap
    joinStyle: ShapePath.RoundJoin
    PathSvg { path: canvas.strokeSvg }
  }
  ShapePath {
    fillColor: "transparent"
    strokeColor: canvas.steady ? "transparent" : canvas.strokeColorB
    strokeStyle: ShapePath.DashLine
    dashPattern: [4, 3]
    strokeWidth: 1.6
    capStyle: ShapePath.RoundCap
    joinStyle: ShapePath.RoundJoin
    PathSvg { path: canvas.strokeSvgB }
  }

  Text {
    textFormat: Text.PlainText
    visible: canvas.steady
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    text: "steady"
    color: canvas.mutedInk
    font.family: "monospace"
    font.pixelSize: 10
  }
  Text {
    textFormat: Text.PlainText
    objectName: "sparkline-peak"
    visible: canvas.rateChart && !canvas.steady
    anchors.left: parent.left
    anchors.top: parent.top
    text: "peak " + Metrics.formatRate(canvas.plotMax)
    color: canvas.mutedInk
    opacity: 0.75
    font.family: "monospace"
    font.pixelSize: 9
  }
  Text {
    textFormat: Text.PlainText
    visible: !canvas.steady
    anchors.left: parent.left
    anchors.bottom: parent.bottom
    text: "60 s"
    color: canvas.mutedInk
    font.family: "monospace"
    font.pixelSize: 9
  }
  Repeater {
    model: 2
    delegate: Text {
      textFormat: Text.PlainText
      objectName: "sparkline-end-label-" + index
      required property int index
      readonly property var values: index === 0 ? canvas.paintedSamples : canvas.paintedSamplesB
      readonly property string label: index === 0 ? canvas.labelA : canvas.labelB
      visible: !canvas.steady && label !== "" && values && values.length > 0
      x: Math.max(0, canvas.width - width - 2)
      y: {
        if (!values || !values.length) return 0
        var target = canvas.pointY(values[values.length - 1]) + (index === 0 ? -height : 1)
        if (index === 1 && canvas.paintedSamples && canvas.paintedSamples.length) {
          var first = Math.max(0, Math.min(canvas.height - height,
            canvas.pointY(canvas.paintedSamples[canvas.paintedSamples.length - 1]) - height))
          var second = Math.max(0, Math.min(canvas.height - height, target))
          if (Math.abs(second - first) < height) target = first + height <= canvas.height - height ? first + height : first - height
        }
        return Math.max(0, Math.min(canvas.height - height, target))
      }
      text: label
      color: canvas.ink
      font.family: "monospace"
      font.pixelSize: 9
    }
  }
  Rectangle {
    objectName: "sparkline-crosshair-x"
    visible: hover.containsMouse && canvas.hoverIndex >= 0 && !canvas.steady
    x: canvas.hoverX
    y: 0
    width: 1
    height: canvas.height
    color: canvas.ink
    opacity: 0.55
  }
  Rectangle {
    objectName: "sparkline-crosshair-y"
    visible: hover.containsMouse && canvas.hoverIndex >= 0 && !canvas.steady
    x: 0
    y: visible ? Math.max(0, Math.min(canvas.height - 1, hover.mouseY)) : 0
    width: canvas.width
    height: 1
    color: canvas.ink
    opacity: 0.4
  }
  Rectangle {
    objectName: "sparkline-tooltip"
    visible: hover.containsMouse && canvas.hoverIndex >= 0
    width: tip.implicitWidth + 8
    height: tip.implicitHeight + 6
    x: Math.max(0, Math.min(canvas.width - width, canvas.hoverX + 5))
    y: visible ? Math.max(0, Math.min(canvas.height - height, hover.mouseY - height - 3)) : 0
    radius: 3
    color: canvas.tooltipBg
    border.color: canvas.mutedInk
    Text {
      textFormat: Text.PlainText
      id: tip
      objectName: "sparkline-tooltip-text"
      anchors.centerIn: parent
      text: {
        if (!hover.containsMouse || canvas.hoverIndex < 0) return ""
        var i = canvas.hoverIndex
        if (i < 0 || !canvas.paintedSamples || i >= canvas.paintedSamples.length) return ""
        var result = (canvas.labelA ? canvas.labelA + " " : "") + canvas.displayValue(canvas.paintedSamples[i])
        if (canvas.paintedSamplesB && canvas.paintedSamplesB.length) {
          var j = i - (canvas.paintedSamples.length - canvas.paintedSamplesB.length)
          if (j >= 0 && j < canvas.paintedSamplesB.length) result += "  " + canvas.labelB + " " + canvas.displayValue(canvas.paintedSamplesB[j])
        }
        return result + " · " + (canvas.paintedSamples.length - 1 - i) + " s ago"
      }
      color: canvas.ink
      font.family: "monospace"
      font.pixelSize: 10
    }
  }
  MouseArea {
    id: hover
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.NoButton
    onPositionChanged: function(mouse) {
      canvas.hoverIndex = canvas.hit(mouse.x)
      if (canvas.hoverIndex >= 0) canvas.hoverX = canvas.width * (59 - (canvas.paintedSamples.length - 1 - canvas.hoverIndex)) / 59
    }
    onExited: canvas.hoverIndex = -1
  }
}
