//@ pragma AppId mainframe
//@ pragma ShellId mainframe
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "lib/metrics.js" as Metrics

ShellRoot {
  id: shell

  property string homeDir: String(Quickshell.env("HOME") || "")
  property string themePath: homeDir + "/.local/state/omarchy/current/theme/colors.toml"
  property string themeRaw: ""
  property bool themeLoaded: false
  property bool themeMissing: false
  property bool quitting: false
  property bool stale: false
  property bool restarting: false
  property int samples: 0
  // starts/exits pair a child with its onExited. A late exit from an older
  // child does not match and cannot restart the one that replaced it.
  property int collectorStarts: 0
  property int collectorExits: 0
  property bool collectorUp: false
  property double restartRequestedMs: 0
  // Liveness is the time since the last stdout line from this process.
  property double lastLineMs: 0
  property var restartMarks: []
  property bool collectorStopped: false
  property string sensorError: ""
  property double collectorStartedMs: 0
  readonly property bool smokeMode: String(Quickshell.env("MAINFRAME_SMOKE") || "") === "1"
  // Stable core-row array. Assigned only when the metrics array identity changes.
  property var coreRows: []

  property color themeBg: "#101315"
  property color themeCard: "#171b22"
  property color themeFg: "#cacccc"
  property color themeLabel: "#707880"
  property color themeAccent: "#7aa2f7"
  property color themeCyan: "#7ec8c3"
  property color themeBorder: "#14cacccc"
  property color themeTrack: "#1acacccc"
  property var themeColors: ({ accent: "#7aa2f7", yellow: "#e0c36a", red: "#e06c75" })

  property var modelState: Metrics.emptyState()
  property var view: Metrics.emptyView()
  // Missing cards stay null so a partial view cannot throw inside a binding.
  readonly property var cpuView: (view && view.cpu != null) ? view.cpu : null
  readonly property var memView: (view && view.mem != null) ? view.mem : null
  readonly property var diskView: (view && view.disk != null) ? view.disk : null
  readonly property var netView: (view && view.net != null) ? view.net : null
  readonly property var gpuView: (view && view.gpu != null) ? view.gpu : null
  readonly property var batView: (view && view.battery != null) ? view.battery : null
  readonly property var procView: (view && view.processes != null) ? view.processes : null
  readonly property bool procStale: procView != null && procView.stale === true
  readonly property color sensorColor: Metrics.qtColor(themeColors && themeColors.red ? themeColors.red : "#e06c75")

  readonly property var shape: Metrics.gridShape(window.width)
  readonly property int columns: shape && shape.columns ? shape.columns : 2
  readonly property int cpuSpan: shape && shape.cpuSpan ? shape.cpuSpan : 2
  readonly property real uiScale: {
    var t = (window.width - 900) / 900
    if (t < 0) t = 0
    if (t > 1) t = 1
    return 1 + 0.22 * t
  }
  readonly property int pxLabel: Math.max(12, Math.round(12 * uiScale))
  readonly property int pxValue: Math.max(13, Math.round(14 * uiScale))
  readonly property int pxFigure: Math.max(18, Math.round(20 * uiScale))
  readonly property int pxHero: Math.max(26, Math.round(28 * uiScale))
  readonly property int smokeHoldMs: {
    var ms = Number(Quickshell.env("MAINFRAME_SMOKE_MS") || 0)
    if (!isFinite(ms) || ms <= 0) return 1200
    return Math.round(ms)
  }

  function applyTheme(resolved) {
    var colors = (resolved && resolved.colors) ? resolved.colors : {}
    // metrics.js keeps #RRGGBBAA. Qt colors are #AARRGGBB, and only here.
    themeBg = Metrics.qtColor(resolved.background)
    themeCard = Metrics.qtColor(resolved.card)
    themeFg = Metrics.qtColor(resolved.foreground)
    themeLabel = Metrics.qtColor(resolved.label)
    themeAccent = Metrics.qtColor(resolved.accent)
    themeCyan = Metrics.qtColor(resolved.cyan)
    themeBorder = Metrics.qtColor(resolved.border)
    themeTrack = Metrics.qtColor(resolved.track)
    themeColors = colors
  }

  function consumeTheme(raw) {
    var text = String(raw || "")
    if (text === "") {
      if (!themeLoaded) {
        applyTheme(Metrics.resolveTheme({}))
        themeMissing = true
        themeLoaded = true
      }
      return
    }
    var parsed = null
    try {
      parsed = Metrics.parseColorsToml(text)
    } catch (err) {
      console.log("mainframe theme:", err)
      if (!themeLoaded) {
        applyTheme(Metrics.resolveTheme({}))
        themeMissing = true
        themeLoaded = true
      }
      return
    }
    if (themeLoaded && text === themeRaw) return
    themeRaw = text
    applyTheme(Metrics.resolveTheme(parsed))
    themeMissing = false
    themeLoaded = true
  }

  function sampleHasErrors(raw) {
    if (!raw || typeof raw !== "object") return false
    if (raw.error) return true
    if (!raw.errors) return false
    var key
    for (key in raw.errors) {
      if (Object.prototype.hasOwnProperty.call(raw.errors, key) && raw.errors[key]) return true
    }
    return false
  }

  function pruneMarks(now) {
    var kept = []
    var marks = restartMarks || []
    var i
    for (i = 0; i < marks.length; i++) {
      if (now - marks[i] < 60000) kept.push(marks[i])
    }
    return kept
  }

  // No line for 5 s, or the process exited: one restart after 1 s.
  // Three restarts in a rolling minute stick the notice until r.
  function armRestart() {
    if (quitting || collectorStopped || restartTimer.running) return
    var now = Date.now()
    var marks = pruneMarks(now)
    restartMarks = marks
    if (marks.length >= 3) {
      collectorStopped = true
      stale = true
      restarting = false
      if (collector.running) collector.running = false
      return
    }
    restartTimer.interval = 1000
    restartTimer.start()
  }

  function doRestart() {
    if (quitting || collectorStopped) return
    var now = Date.now()
    // A line, or a process still inside its 5 s grace, cancels the restart.
    if (collector.running && lastLineMs > 0 && (now - lastLineMs) <= 5000) return
    if (collector.running && !(lastLineMs > 0) && collectorStartedMs > 0 && (now - collectorStartedMs) <= 5000) return
    var marks = pruneMarks(now)
    if (marks.length >= 3) {
      restartMarks = marks
      collectorStopped = true
      stale = true
      restarting = false
      if (collector.running) collector.running = false
      return
    }
    marks.push(now)
    restartMarks = marks
    if (collector.running) {
      requestCollectorStop()
    } else {
      collector.running = true
    }
  }

  // Stop the child, then SIGKILL if it has not exited within 2 s (SIGSTOP).
  function requestCollectorStop() {
    if (collector.running) collectorUp = true
    restarting = true
    restartRequestedMs = Date.now()
    collector.running = false
    killTimer.restart()
  }

  function ingest(line) {
    if (quitting || !line) return
    var raw = null
    try {
      raw = JSON.parse(line)
    } catch (err) {
      // Bad JSON is not liveness.
      console.log("mainframe collect: bad json")
      return
    }
    if (!raw || typeof raw !== "object") return
    if (smokeMode) console.log("SAMPLE t=" + Date.now())
    var now = Date.now()
    var result = null
    try {
      result = Metrics.step(modelState, raw, now)
    } catch (err2) {
      // The line arrived. Keep the last view and do not spend a restart.
      console.log("mainframe step:", err2)
      sensorError = "sensor error"
      var alive = Metrics.collectorLineAlive(now)
      lastLineMs = alive.lastLineMs
      stale = alive.stale
      if (alive.stopRestartTimer && restartTimer.running) restartTimer.stop()
      return
    }
    // Any parsed line, including a sensor-error line, proves the process is alive.
    lastLineMs = now
    stale = false
    if (restartTimer.running) restartTimer.stop()
    var erred = sampleHasErrors(raw)
    if (erred) {
      // Liveness only. Do not clear the notice or count the line as fresh data.
      sensorError = "sensor error"
      console.log("mainframe collect: sensor error")
    } else {
      sensorError = ""
    }
    if (result.skip) return
    // Every 1 Hz sample publishes the scene. Cards repaint only where the
    // new numbers differ: core rows keep their identity, sparklines keep
    // their path until the series or the box changes.
    modelState = result.state
    view = result.view
    var nextCores = (result.view && result.view.cpu && result.view.cpu.cores) ? result.view.cpu.cores : null
    if (nextCores && nextCores !== coreRows) coreRows = nextCores
    if (!erred) samples = samples + 1
  }

  // r resets the rolling window and starts a collector without spending a mark.
  function retryCollector() {
    if (quitting) return
    collectorStopped = false
    restartMarks = []
    sensorError = ""
    stale = false
    if (restartTimer.running) restartTimer.stop()
    if (collector.running) {
      requestCollectorStop()
    } else {
      collector.running = true
    }
  }

  // quit on stdin, then drop the process. The death signal and EOF end the child.
  function shutdown() {
    if (quitting) return
    quitting = true
    watchdog.stop()
    themeTimer.stop()
    restartTimer.stop()
    killTimer.stop()
    smokeTimer.stop()
    if (collector.running) {
      collector.write("quit\n")
      collector.running = false
    }
    Qt.quit()
  }

  function floorPx(value) {
    if (!(value >= 0)) return -1
    return Math.floor(value + 0.0001)
  }

  function coreCellOverflow(cell) {
    var want = ["core-index", "core-pct", "core-freq", "core-meter"]
    var rects = []
    var kids = cell.children || []
    var i
    for (i = 0; i < kids.length; i++) {
      var kid = kids[i]
      if (!kid || !kid.visible) continue
      var nm = kid.objectName || ""
      if (want.indexOf(nm) < 0) continue
      var rect = { x: kid.x, y: kid.y, r: kid.x + kid.width, b: kid.y + kid.height }
      if (rect.x < -1 || rect.y < -1 || rect.r > cell.width + 1 || rect.b > cell.height + 1) {
        console.log("OVERFLOW core-overlap", nm, "outside")
        return 1
      }
      var j
      for (j = 0; j < rects.length; j++) {
        var other = rects[j]
        var ox = Math.min(rect.r, other.r) - Math.max(rect.x, other.x)
        var oy = Math.min(rect.b, other.b) - Math.max(rect.y, other.y)
        if (ox > 1 && oy > 1) {
          console.log("OVERFLOW core-overlap", nm, other.name)
          return 1
        }
      }
      rects.push({ name: nm, x: rect.x, y: rect.y, r: rect.r, b: rect.b })
    }
    return 0
  }

  function walkGauge(item, depth, acc) {
    if (!item || depth > 12) return
    var name = item.objectName || ""
    if (name === "core-cell") acc.overflow = acc.overflow + coreCellOverflow(item)
    if (name === "core-meter") {
      // Hidden meters (compact heat map, or a cell too short to draw) are not gauged.
      if (item.visible) {
        acc.meters = acc.meters + 1
        if (acc.minH < 0 || item.height < acc.minH) acc.minH = item.height
        if (acc.minW < 0 || item.width < acc.minW) acc.minW = item.width
      }
    } else if (name === "metric-label" && item.visible && item.text && String(item.text).length > 0 && item.font) {
      var px = item.font.pixelSize
      if (acc.minLabel < 0 || px < acc.minLabel) acc.minLabel = px
    }
    if (name === "body" && item.implicitHeight > item.height + 2) {
      acc.overflow = acc.overflow + 1
      console.log("OVERFLOW content", "implicit", item.implicitHeight, "height", item.height)
    }
    var kids = item.children
    if (!kids) return
    for (var i = 0; i < kids.length; i++) walkGauge(kids[i], depth + 1, acc)
  }

  function checkLayout() {
    var overflow = 0
    var cards = 0
    var acc = { meters: 0, minH: -1, minW: -1, minLabel: -1, overflow: 0 }
    for (var i = 0; i < grid.children.length; i++) {
      var card = grid.children[i]
      if (!card || !card.objectName || card.objectName.indexOf("card-") !== 0) continue
      cards = cards + 1
      var bottom = card.y + card.height
      var right = card.x + card.width
      if (bottom > grid.height + 1 || right > grid.width + 1 || card.x < -1 || card.y < -1) {
        overflow = overflow + 1
        console.log("OVERFLOW card", card.objectName, "rect", card.x, card.y, card.width, card.height, "grid", grid.width, grid.height)
      }
      walkGauge(card, 0, acc)
    }
    overflow = overflow + acc.overflow
    var cores = shell.coreRows ? shell.coreRows.length : 0
    console.log("LAYOUT w=" + Math.round(window.width) + " h=" + Math.round(window.height)
      + " cols=" + columns + " rows=" + (shape && shape.rows ? shape.rows : 0)
      + " cpuSpan=" + cpuSpan + " cards=" + cards + " overflow=" + overflow
      + " samples=" + samples + " cores=" + cores)
    console.log("GAUGE meters=" + acc.meters
      + " minMeterH=" + floorPx(acc.minH)
      + " minMeterW=" + floorPx(acc.minW)
      + " minLabel=" + floorPx(acc.minLabel)
      + " compact=" + (coreArea.compact ? 1 : 0))
  }

  FileView {
    id: colorsFile
    path: shell.themePath
    watchChanges: true
    printErrors: false
    blockLoading: true
    onLoaded: shell.consumeTheme(text())
    onFileChanged: reload()
    onLoadFailed: {
      if (shell.themeLoaded) return
      shell.consumeTheme("")
    }
  }

  Timer {
    id: themeTimer
    interval: 2000
    repeat: true
    running: true
    onTriggered: colorsFile.reload()
  }

  Process {
    id: collector
    command: ["python3", "-u", Quickshell.shellDir + "/collect.py"]
    running: true
    stdinEnabled: true
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { shell.ingest(line) }
    }
    stderr: SplitParser {
      splitMarker: "\n"
      onRead: function(line) {
        if (!line) return
        console.log("mainframe collect stderr:", line)
      }
    }
    onStarted: {
      // The 5 s grace belongs to this process. A line from the previous one does not count.
      shell.collectorStarts = shell.collectorStarts + 1
      shell.collectorUp = true
      shell.collectorStartedMs = Date.now()
      shell.lastLineMs = 0
      shell.restarting = false
      shell.restartRequestedMs = 0
      if (killTimer.running) killTimer.stop()
    }
    onExited: function(code, status) {
      shell.collectorExits = shell.collectorExits + 1
      // A newer child is already up, or this exit has no matching start.
      if (Metrics.collectorExitIgnored(shell.collectorStarts, shell.collectorExits)) return
      shell.collectorUp = false
      if (shell.quitting) return
      if (shell.collectorStopped) return
      if (killTimer.running) killTimer.stop()
      if (shell.restarting) {
        shell.restarting = false
        shell.restartRequestedMs = 0
        collector.running = true
        return
      }
      console.log("mainframe collector exited", code)
      shell.armRestart()
    }
  }

  Timer {
    id: killTimer
    interval: 2000
    repeat: false
    onTriggered: {
      if (shell.quitting || !shell.restarting) return
      if (!Metrics.collectorKillDue(Date.now(), shell.restartRequestedMs, shell.collectorUp)) return
      // SIGKILL. A SIGSTOPped child ignores the terminate that running=false sent.
      if (collector.running || shell.collectorUp) collector.signal(9)
      shell.restarting = false
      shell.restartRequestedMs = 0
    }
  }

  Timer {
    id: watchdog
    interval: 1000
    repeat: true
    running: true
    onTriggered: {
      if (shell.quitting || shell.collectorStopped || shell.restarting) return
      var now = Date.now()
      var silent = false
      if (shell.lastLineMs > 0) silent = (now - shell.lastLineMs) > 5000
      else if (shell.collectorStartedMs > 0) silent = (now - shell.collectorStartedMs) > 5000
      if (!collector.running || silent) {
        shell.stale = true
        shell.armRestart()
      }
    }
  }

  Timer {
    id: restartTimer
    repeat: false
    onTriggered: shell.doRestart()
  }

  Timer {
    id: smokeTimer
    interval: shell.smokeHoldMs
    repeat: false
    onTriggered: {
      shell.checkLayout()
      shell.shutdown()
    }
  }

  Component.onCompleted: {
    var smoke = String(Quickshell.env("MAINFRAME_SMOKE") || "")
    if (smoke !== "1") return
    var w = Number(Quickshell.env("MAINFRAME_SMOKE_W") || 0)
    var h = Number(Quickshell.env("MAINFRAME_SMOKE_H") || 0)
    if (w > 0) window.implicitWidth = w
    if (h > 0) window.implicitHeight = h
    console.log("SMOKE appId=" + Quickshell.appId + " shellId=" + Quickshell.shellId)
    smokeTimer.start()
  }

  FloatingWindow {
    id: window
    title: "Mainframe"
    color: shell.themeBg
    implicitWidth: 1280
    implicitHeight: 800
    minimumSize: Qt.size(700, 560)

    onClosed: {
      // Closing the window during an in-progress quit must not shut down twice.
      if (shell.quitting) return
      shell.shutdown()
    }

    // One binding per action. sequences covers the letter and its shift form.
    Shortcut {
      sequences: ["Escape", "q", "Q"]
      context: Qt.WindowShortcut
      onActivated: shell.shutdown()
    }
    Shortcut {
      sequences: ["r", "R"]
      context: Qt.WindowShortcut
      onActivated: shell.retryCollector()
    }

    ColumnLayout {
      anchors.fill: parent
      anchors.margins: 14
      spacing: 8

      RowLayout {
        Layout.fillWidth: true
        visible: shell.themeMissing || shell.stale
        spacing: 14

        Text {
          visible: shell.themeMissing
          text: "theme not found"
          color: shell.themeLabel
          font.family: "monospace"
          font.pixelSize: shell.pxLabel
        }
        Text {
          visible: shell.stale
          text: "stale"
          textFormat: Text.PlainText
          color: shell.sensorColor
          font.family: "monospace"
          font.pixelSize: shell.pxLabel
        }
        Item { Layout.fillWidth: true }
      }

      Text {
        visible: shell.collectorStopped
        text: "collector stopped — press r to retry"
        textFormat: Text.PlainText
        color: shell.sensorColor
        font.family: "monospace"
        font.pixelSize: shell.pxLabel
        Layout.fillWidth: true
      }

      GridLayout {
        id: grid
        Layout.fillWidth: true
        Layout.fillHeight: true
        opacity: shell.stale ? 0.45 : 1
        columnSpacing: 14
        rowSpacing: 14
        columns: shell.columns

        Card {
          objectName: "card-cpu"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.columnSpan: shell.cpuSpan
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "CPU"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            RowLayout {
              Layout.fillWidth: true
              Text {
                text: shell.cpuView ? shell.cpuView.percentText : "—"
                color: shell.themeFg
                font.family: "monospace"
                font.pixelSize: shell.pxHero
                font.weight: Font.Medium
              }
              Item { Layout.fillWidth: true }
              Text {
                text: shell.cpuView ? shell.cpuView.tempText : "—"
                color: shell.themeFg
                font.family: "monospace"
                font.pixelSize: shell.pxValue
              }
              Text {
                text: shell.cpuView ? shell.cpuView.freqText : "—"
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxValue
              }
            }

            Sparkline {
              Layout.fillWidth: true
              Layout.fillHeight: false
              Layout.preferredHeight: 36
              Layout.minimumHeight: 28
              Layout.maximumHeight: 40
              samples: shell.cpuView ? shell.cpuView.history : []
              strokeColor: shell.themeAccent
              yMin: 0
              yMax: 100
            }

            Item {
              id: coreArea
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: 36

              readonly property int n: shell.coreRows ? shell.coreRows.length : 0
              // Width 0 on the first pass: estimate from the window, and never divide by 0.
              readonly property var layout: {
                var w = width
                var h = height
                if (!(w >= 40)) {
                  var gridW = window.width - 28
                  if (gridW < 0) gridW = 0
                  var gaps = (shell.columns - 1) * 14
                  var col = shell.columns > 0 ? (gridW - gaps) / shell.columns : gridW
                  w = col * shell.cpuSpan + (shell.cpuSpan - 1) * 14 - 24
                  if (!(w > 0)) w = 0
                }
                if (!(h > 0)) h = 0
                return Metrics.coreLayout(n, w, h)
              }
              readonly property int cols: (layout && layout.columns >= 1) ? layout.columns : 1
              readonly property int rows: (layout && layout.rows >= 1) ? layout.rows : 1
              readonly property int colGap: (layout && layout.colGap != null) ? layout.colGap : 6
              readonly property int rowGap: (layout && layout.rowGap != null) ? layout.rowGap : 4
              readonly property bool compact: layout ? layout.compact === true : false
              readonly property real cellW: {
                var v = layout ? Number(layout.cellW) : 0
                if (!(v > 0)) return 0
                return v
              }
              readonly property real cellH: {
                var v = layout ? Number(layout.cellH) : 0
                if (!(v > 0)) return 0
                return v
              }

              Repeater {
                model: coreArea.n
                delegate: Item {
                  id: coreCell
                  objectName: "core-cell"
                  property var core: {
                    var list = shell.coreRows
                    if (!list || index < 0 || index >= list.length) return null
                    return list[index]
                  }
                  property real pct: {
                    var p = 0
                    if (core && core.percent != null) p = Number(core.percent)
                    if (!isFinite(p) || p < 0) p = 0
                    if (p > 100) p = 100
                    return p / 100
                  }
                  x: coreArea.cols >= 1 ? (index % coreArea.cols) * (coreArea.cellW + coreArea.colGap) : 0
                  y: coreArea.cols >= 1 ? Math.floor(index / coreArea.cols) * (coreArea.cellH + coreArea.rowGap) : 0
                  width: coreArea.cellW > 0 ? coreArea.cellW : 0
                  height: coreArea.cellH > 0 ? coreArea.cellH : 0

                  // Dense machines (>32 logical cores) draw a heat tile instead of a meter.
                  // The loader stays inactive otherwise so those items are not updated.
                  Loader {
                    active: coreArea.compact
                    anchors.fill: parent
                    sourceComponent: Component {
                      Item {
                        Rectangle {
                          anchors.fill: parent
                          radius: 2
                          color: {
                            var sample = coreCell.core
                            if (!(sample && sample.percent != null) || !isFinite(Number(sample.percent))) return shell.themeTrack
                            return Metrics.qtColor(Metrics.meterColor(coreCell.pct, shell.themeColors))
                          }
                        }
                        Text {
                          // Hide rather than ellipsize: a cut-off percent is a broken number.
                          visible: parent.height >= 12 && parent.width >= 18 && implicitWidth <= Math.max(0, parent.width - 2)
                          anchors.centerIn: parent
                          text: coreCell.core && coreCell.core.percentText ? coreCell.core.percentText : "—"
                          textFormat: Text.PlainText
                          color: shell.themeFg
                          font.family: "monospace"
                          font.pixelSize: parent.height >= 18 ? 9 : 8
                        }
                      }
                    }
                  }

                  // Index stays left (at most ~45% of the cell) and percent stays
                  // right (at most ~50%). Digits shrink down to a floor instead of
                  // gaining an ellipsis; clip covers whatever still sticks out, so
                  // the two never overlap. Frequency (already "3.2G" / "800M") is
                  // drawn only when that whole token fits in the gap between them.
                  // These are not metric-label: the gauge floor is for the card titles.
                  // Hidden when the cell is too short to hold a line of text.
                  readonly property real freqRoom: {
                    if (coreArea.compact || height < 16) return 0
                    return width - coreIndex.width - corePct.width - 6
                  }

                  Text {
                    id: coreIndex
                    objectName: "core-index"
                    visible: !coreArea.compact && parent.height >= 16
                    anchors.left: parent.left
                    anchors.top: parent.top
                    // Natural width, capped. implicitWidth stays the unfitted size,
                    // so this does not chase the shrunk font.
                    width: Math.min(implicitWidth, Math.max(0, parent.width * 0.45))
                    clip: true
                    elide: Text.ElideNone
                    text: index < 10 ? ("0" + index) : ("" + index)
                    textFormat: Text.PlainText
                    color: shell.themeLabel
                    font.family: "monospace"
                    font.pixelSize: shell.pxLabel
                    fontSizeMode: Text.HorizontalFit
                    minimumPixelSize: 8
                  }

                  Text {
                    id: corePct
                    objectName: "core-pct"
                    visible: !coreArea.compact && parent.height >= 16
                    anchors.right: parent.right
                    anchors.top: parent.top
                    width: Math.min(implicitWidth, Math.max(0, parent.width * 0.50))
                    clip: true
                    elide: Text.ElideNone
                    horizontalAlignment: Text.AlignRight
                    text: core && core.percentText ? core.percentText : "—"
                    textFormat: Text.PlainText
                    color: shell.themeFg
                    font.family: "monospace"
                    font.pixelSize: shell.pxLabel
                    fontSizeMode: Text.HorizontalFit
                    minimumPixelSize: 8
                  }

                  Text {
                    id: coreFreq
                    objectName: "core-freq"
                    anchors.top: parent.top
                    visible: !coreArea.compact && parent.height >= 16 && text !== "" && implicitWidth <= parent.freqRoom
                    x: coreIndex.width + 3 + Math.max(0, (parent.freqRoom - implicitWidth) / 2)
                    text: core && core.freqText ? core.freqText : ""
                    textFormat: Text.PlainText
                    color: shell.themeLabel
                    font.family: "monospace"
                    font.pixelSize: shell.pxLabel
                  }

                  Meter {
                    objectName: "core-meter"
                    vertical: true
                    // anchors.bottom made a short cell negative. Height is clamped,
                    // and it does not read y, so visible cannot loop.
                    visible: !coreArea.compact && parent.height >= 32
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: coreIndex.bottom
                    anchors.topMargin: 4
                    height: {
                      var room = parent.height - shell.pxLabel - 10
                      if (!(room >= 14)) return 0
                      return room
                    }
                    width: {
                      var cell = parent.width
                      if (!(cell >= 14)) return 0
                      var wanted = cell * 0.36
                      if (wanted < 14) wanted = 14
                      if (wanted > 28) wanted = 28
                      if (wanted > cell) wanted = cell
                      return wanted
                    }
                    fraction: pct
                    fill: Metrics.qtColor(Metrics.meterColor(pct, shell.themeColors))
                    track: shell.themeTrack
                  }
                }
              }
            }
          }
        }

        Card {
          objectName: "card-mem"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Memory"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            Text {
              text: shell.memView ? shell.memView.usedText : "—"
              color: shell.themeFg
              font.family: "monospace"
              font.pixelSize: shell.pxFigure
              font.weight: Font.Medium
              elide: Text.ElideRight
              Layout.fillWidth: true
            }

            Meter {
              Layout.fillWidth: true
              Layout.preferredHeight: 12
              fraction: shell.memView ? shell.memView.fraction : 0
              fill: Metrics.qtColor(Metrics.meterColor(shell.memView ? shell.memView.fraction : 0, shell.themeColors))
              track: shell.themeTrack
            }

            Sparkline {
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: 28
              samples: shell.memView ? shell.memView.history : []
              strokeColor: shell.themeAccent
              yMin: 0
              yMax: 100
            }

            ColumnLayout {
              Layout.fillWidth: true
              spacing: 2
              Text {
                objectName: "metric-label"
                text: "available  " + (shell.memView ? shell.memView.availableText : "—")
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
              Text {
                objectName: "metric-label"
                text: "cached     " + (shell.memView ? shell.memView.cachedText : "—")
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
              Text {
                objectName: "metric-label"
                text: "swap       " + (shell.memView ? shell.memView.swapText : "—")
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
            }
          }
        }

        Card {
          objectName: "card-gpu"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: (shell.gpuView && shell.gpuView.driver) ? ("GPU  " + shell.gpuView.driver) : "GPU"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            Text {
              text: shell.gpuView == null ? "not available" : shell.gpuView.percentText
              color: (shell.gpuView != null && shell.gpuView.unsupported !== true) ? shell.themeFg : shell.themeLabel
              font.family: "monospace"
              font.pixelSize: (shell.gpuView != null && shell.gpuView.unsupported !== true) ? shell.pxHero : shell.pxLabel
              font.weight: Font.Medium
            }

            Text {
              objectName: "metric-label"
              visible: shell.gpuView != null
              text: shell.gpuView != null ? shell.gpuView.freqText : ""
              color: shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
            }

            Sparkline {
              visible: shell.gpuView != null && shell.gpuView.unsupported !== true
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: (shell.gpuView != null && shell.gpuView.unsupported !== true) ? 28 : 0
              samples: shell.gpuView != null ? shell.gpuView.history : []
              strokeColor: shell.themeAccent
              yMin: 0
              yMax: 100
            }
          }
        }

        Card {
          objectName: "card-disk"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Disk"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            RowLayout {
              Layout.fillWidth: true
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                  text: shell.diskView ? shell.diskView.readText : "unavailable"
                  color: shell.themeFg
                  font.family: "monospace"
                  font.pixelSize: shell.pxFigure
                  font.weight: Font.Medium
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                  Layout.preferredWidth: 0
                  Layout.minimumWidth: 0
                }
                Text {
                  objectName: "metric-label"
                  text: "read"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                  text: shell.diskView ? shell.diskView.writeText : "unavailable"
                  color: shell.themeFg
                  font.family: "monospace"
                  font.pixelSize: shell.pxFigure
                  font.weight: Font.Medium
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                  Layout.preferredWidth: 0
                  Layout.minimumWidth: 0
                }
                Text {
                  objectName: "metric-label"
                  text: "write"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
            }

            Text {
              text: shell.diskView ? shell.diskView.usageText : "—"
              color: shell.themeFg
              font.family: "monospace"
              font.pixelSize: shell.pxValue
              elide: Text.ElideRight
              Layout.fillWidth: true
              Layout.preferredWidth: 0
              Layout.minimumWidth: 0
            }

            Meter {
              Layout.fillWidth: true
              Layout.preferredHeight: 12
              fraction: shell.diskView ? shell.diskView.fraction : 0
              fill: Metrics.qtColor(Metrics.meterColor(shell.diskView ? shell.diskView.fraction : 0, shell.themeColors))
              track: shell.themeTrack
            }

            Sparkline {
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: 28
              samples: shell.diskView ? shell.diskView.readHistory : []
              samplesB: shell.diskView ? shell.diskView.writeHistory : []
              strokeColor: shell.themeAccent
              strokeColorB: shell.themeCyan
              yMin: 0
              yMax: -1
            }

            RowLayout {
              Layout.fillWidth: true
              Text {
                visible: shell.diskView && shell.diskView.tempText && shell.diskView.tempText !== "—"
                text: shell.diskView ? shell.diskView.tempText : ""
                color: shell.themeFg
                font.family: "monospace"
                font.pixelSize: shell.pxValue
              }
              Item { Layout.fillWidth: true }
              Text {
                objectName: "metric-label"
                text: shell.diskView && shell.diskView.device ? shell.diskView.device : "—"
                textFormat: Text.PlainText
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignRight
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                Layout.minimumWidth: 0
              }
            }
          }
        }

        Card {
          objectName: "card-net"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Network"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            id: netBody
            objectName: "body"
            anchors.fill: parent
            spacing: 6
            readonly property var detail: Metrics.netDetailLines(
              shell.netView ? shell.netView.perIface : [],
              shell.netView && shell.netView.iface ? shell.netView.iface : ""
            )

            Text {
              objectName: "metric-label"
              text: shell.netView && shell.netView.iface ? shell.netView.iface : "—"
              textFormat: Text.PlainText
              color: shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
              elide: Text.ElideRight
              Layout.fillWidth: true
              Layout.preferredWidth: 0
              Layout.minimumWidth: 0
            }

            RowLayout {
              Layout.fillWidth: true
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                  text: shell.netView ? shell.netView.downText : "—"
                  color: shell.themeAccent
                  font.family: "monospace"
                  font.pixelSize: shell.pxFigure
                  font.weight: Font.Medium
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                  Layout.preferredWidth: 0
                  Layout.minimumWidth: 0
                }
                Text {
                  objectName: "metric-label"
                  text: "down"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                  text: shell.netView ? shell.netView.upText : "—"
                  color: shell.themeCyan
                  font.family: "monospace"
                  font.pixelSize: shell.pxFigure
                  font.weight: Font.Medium
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                  Layout.preferredWidth: 0
                  Layout.minimumWidth: 0
                }
                Text {
                  objectName: "metric-label"
                  text: "up"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
            }

            Repeater {
              model: netBody.detail ? netBody.detail.length : 0
              delegate: Text {
                property var ifaceRow: {
                  var rows = netBody.detail
                  if (!rows || index < 0 || index >= rows.length) return null
                  return rows[index]
                }
                objectName: "metric-label"
                visible: text !== ""
                textFormat: Text.PlainText
                text: {
                  if (!ifaceRow) return ""
                  if (ifaceRow.more) return ifaceRow.text ? ifaceRow.text : ""
                  return ifaceRow.name + "  " + ifaceRow.downText + "  " + ifaceRow.upText
                }
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                Layout.minimumWidth: 0
              }
            }

            Sparkline {
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: 28
              samples: shell.netView ? shell.netView.rxHistory : []
              samplesB: shell.netView ? shell.netView.txHistory : []
              strokeColor: shell.themeAccent
              strokeColorB: shell.themeCyan
              yMin: 0
              yMax: -1
            }
          }
        }

        Card {
          objectName: "card-bat"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Battery"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            Text {
              text: shell.batView != null ? shell.batView.percentText : "no battery"
              color: shell.batView != null ? shell.themeFg : shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.batView != null ? shell.pxHero : shell.pxLabel
              font.weight: Font.Medium
            }

            Text {
              objectName: "metric-label"
              visible: shell.batView != null
              text: shell.batView != null ? shell.batView.statusText : ""
              textFormat: Text.PlainText
              color: shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
            }

            Text {
              visible: shell.batView != null
              text: shell.batView != null ? shell.batView.powerText : ""
              color: shell.themeFg
              font.family: "monospace"
              font.pixelSize: shell.pxFigure
            }

            Meter {
              visible: shell.batView != null
              Layout.fillWidth: true
              Layout.preferredHeight: shell.batView != null ? 12 : 0
              fraction: shell.batView != null ? shell.batView.fraction : 0
              fill: Metrics.qtColor(Metrics.batteryMeterColor(shell.batView != null ? shell.batView.fraction : 0, shell.themeColors))
              track: shell.themeTrack
            }

            Sparkline {
              visible: shell.batView != null
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: shell.batView != null ? 28 : 0
              samples: shell.batView != null ? shell.batView.history : []
              strokeColor: shell.themeAccent
              // A flat 100% history would otherwise fill this plot solid.
              fillOpacity: 0.08
              strokeOnlyWhenFlat: true
              yMin: 0
              yMax: 100
            }
          }
        }

        Card {
          objectName: "card-proc"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Processes"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          // Top-down. A GridLayout centers a short column in the card, which
          // left the lists sitting in the lower half. Both lists start under
          // the title; spare height only loosens row spacing a little.
          Item {
            id: procBody
            objectName: "body"
            anchors.fill: parent
            readonly property bool sideBySide: width >= 260
            readonly property real listTop: procStale.visible ? procStale.implicitHeight + 4 : 0
            readonly property real listRoom: Math.max(0, height - listTop)

            Text {
              id: procStale
              visible: shell.procStale
              x: 0
              y: 0
              width: parent.width
              text: "stale"
              textFormat: Text.PlainText
              color: shell.sensorColor
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
            }

            ProcList {
              id: cpuList
              opacity: shell.procStale ? 0.45 : 1
              x: 0
              y: procBody.listTop
              width: procBody.sideBySide ? Math.max(0, Math.floor((procBody.width - 12) / 2)) : procBody.width
              // A layout inside a plain Item does not adopt its implicit height.
              height: implicitHeight
              availHeight: procBody.sideBySide ? procBody.listRoom : Math.max(0, (procBody.listRoom - 4) / 2)
              heading: "cpu"
              rows: shell.procView && shell.procView.byCpu ? shell.procView.byCpu : []
              labelColor: shell.themeLabel
              textColor: shell.themeFg
              labelPx: shell.pxLabel
              rowPx: shell.pxLabel
              valueWidth: Math.round(shell.pxLabel * 5.5)
            }
            ProcList {
              id: memList
              opacity: shell.procStale ? 0.45 : 1
              x: procBody.sideBySide ? cpuList.width + 12 : 0
              y: procBody.sideBySide ? procBody.listTop : (cpuList.y + cpuList.height + 4)
              width: cpuList.width
              height: implicitHeight
              availHeight: procBody.sideBySide ? procBody.listRoom : Math.max(0, procBody.height - y)
              heading: "memory"
              rows: shell.procView && shell.procView.byMem ? shell.procView.byMem : []
              labelColor: shell.themeLabel
              textColor: shell.themeFg
              labelPx: shell.pxLabel
              rowPx: shell.pxLabel
              valueWidth: Math.round(shell.pxLabel * 5.5)
            }
          }
        }
      }
    }
  }
}
