import QtQuick
import QtTest
import ".." as Mainframe

TestCase {
  id: test
  name: "Sparkline"
  width: 400
  height: 200
  visible: true
  when: windowShown

  Mainframe.Sparkline {
    id: chart
    width: 300
    height: 100
    labelA: "CPU"
    samples: [10, 20, 30]
  }
  Component {
    id: freshChart
    Mainframe.Sparkline { width: 300; height: 100; rateChart: true; samples: [4, 4] }
  }
  function resetChart() {
    mouseMove(test, 350, 150)
    chart.visible = true
    chart.samples = [10, 20, 30]
    chart.samplesB = []
    chart.rateChart = false
    chart.yMax = -1
    chart.yMin = 0
  }
  function init() {
    resetChart()
    tryVerify(function() { return chart.built && chart.lastYMax === -1 && chart.lastYMin === 0 && chart.paintedSamples && chart.paintedSamples.length === 3 && chart.paintedSamples[2] === 30 && chart.paintedSamplesB && chart.paintedSamplesB.length === 0 })
  }
  function cleanup() {
    resetChart()
    wait(0)
  }

  function test_painted_state_stays_in_sync() {
    chart.yMax = 100
    chart.samples = [10, 20, 30]
    tryVerify(function() { return chart.built && chart.lastYMax === 100 && chart.paintedSamples[2] === 30 })
    var label = findChild(chart, "sparkline-end-label-0")
    verify(label !== null)
    var oldPath = chart.strokeSvg
    var oldY = label.y
    chart.samples = [10, 20, 80]
    compare(chart.strokeSvg, oldPath)
    compare(label.y, oldY)
    compare(label.values[2], 30)
    tryVerify(function() { return chart.paintedSamples[2] === 80 })
    verify(chart.strokeSvg !== oldPath)
    compare(label.values[2], 80)
    verify(label.y !== oldY)

    chart.samples = [5, 5, 5]
    tryVerify(function() { return chart.steady })
    var stalePath = chart.strokeSvg
    chart.samples = [5, 10, 5]
    verify(chart.steady)
    compare(chart.strokeSvg, stalePath)
    tryVerify(function() { return !chart.steady })
    verify(chart.strokeSvg !== stalePath)
    verify(chart.strokeSvg.length > 0)
    compare(label.values[1], 10)
  }

  function test_resting_hover_tracks_growing_history() {
    chart.samples = [10, 20, 30]
    tryVerify(function() { return chart.paintedSamples.length === 3 && chart.paintedSamples[2] === 30 })
    var tip = findChild(chart, "sparkline-tooltip-text")
    mouseMove(chart, 285, 30)
    tryVerify(function() { return chart.hoverIndex !== -1 })
    // The time axis has 60 fixed slots, so x=285 maps to index 0 with 3 samples.
    compare(chart.hoverIndex, 0)
    compare(tip.text, "CPU 10% · 2 s ago")
    var oldX = chart.hoverX
    chart.samples = [10, 20, 30, 40, 50]
    compare(chart.paintedSamples.length, 3)
    compare(chart.hoverIndex, 0)
    compare(chart.hoverX, oldX)
    compare(tip.text, "CPU 10% · 2 s ago")
    tryVerify(function() { return chart.paintedSamples.length === 5 })
    compare(chart.hoverIndex, 1)
    compare(tip.text, "CPU 20% · 3 s ago")
    verify(chart.hoverX !== oldX)
    mouseMove(test, 350, 150)
  }

  function test_initial_and_hidden_state() {
    var fresh = createTemporaryObject(freshChart, test)
    verify(fresh !== null)
    compare(fresh.paintedSamples, null)
    verify(!fresh.steady)
    verify(!findChild(fresh, "sparkline-peak").visible)
    fresh.visible = false
    fresh.samples = [10, 40, 20]
    wait(0)
    compare(fresh.paintedSamples, null)
    fresh.visible = true
    tryVerify(function() { return fresh.built && fresh.paintedSamples && fresh.paintedSamples[1] === 40 })
    verify(!fresh.steady)
    compare(fresh.plotMax, 40)
    var oldPath = fresh.strokeSvg
    fresh.visible = false
    fresh.samples = [8, 8, 8]
    wait(0)
    compare(fresh.paintedSamples[1], 40)
    compare(fresh.strokeSvg, oldPath)
    verify(!fresh.steady)
    fresh.visible = true
    tryVerify(function() { return fresh.steady && fresh.paintedSamples[1] === 8 })
    compare(fresh.strokeSvg, oldPath)
    fresh.visible = false
    fresh.samples = [8, 20, 8]
    wait(0)
    compare(fresh.paintedSamples[1], 8)
    verify(fresh.steady)
    compare(fresh.strokeSvg, oldPath)
    fresh.visible = true
    tryVerify(function() { return !fresh.steady && fresh.paintedSamples[1] === 20 && fresh.strokeSvg !== oldPath })
  }

  function test_painted_samples_do_not_alias_inputs() {
    var a = [10, 20, 30]
    var b = [4, 5, 6]
    chart.samples = a
    chart.samplesB = b
    tryVerify(function() { return chart.paintedSamplesB && chart.paintedSamplesB[2] === 6 })
    var path = chart.strokeSvg
    var pathB = chart.strokeSvgB
    a[2] = 80
    b[2] = 40
    compare(chart.paintedSamples[2], 30)
    compare(chart.paintedSamplesB[2], 6)
    compare(chart.strokeSvg, path)
    compare(chart.strokeSvgB, pathB)
    chart.samples = a.slice()
    chart.samplesB = b.slice()
    tryVerify(function() { return chart.paintedSamples[2] === 80 && chart.paintedSamplesB[2] === 40 })
    verify(chart.strokeSvg !== path)
    verify(chart.strokeSvgB !== pathB)

    var flatA = [5, 5]
    var flatB = [8, 8]
    chart.samples = flatA
    chart.samplesB = flatB
    tryVerify(function() { return chart.steady && chart.paintedSamples[0] === 5 && chart.paintedSamplesB[0] === 8 })
    flatA[0] = 9
    flatB[0] = 10
    verify(chart.steady)
    compare(chart.paintedSamples[0], 5)
    compare(chart.paintedSamplesB[0], 8)
  }

  function test_peak_waits_for_painted_samples() {
    chart.rateChart = true
    chart.yMax = -1
    chart.samples = [10, 20, 30]
    tryVerify(function() { return chart.plotMax === 30 })
    var peak = findChild(chart, "sparkline-peak")
    var oldText = peak.text
    var oldPath = chart.strokeSvg
    chart.samples = [10, 20, 90]
    compare(peak.text, oldText)
    compare(chart.strokeSvg, oldPath)
    tryVerify(function() { return chart.plotMax === 90 })
    verify(peak.text !== oldText)
    verify(chart.strokeSvg !== oldPath)
  }

  function test_hover_and_rebuild() {
    var tip = findChild(chart, "sparkline-tooltip")
    var text = findChild(chart, "sparkline-tooltip-text")
    var crosshair = findChild(chart, "sparkline-crosshair-x")
    verify(tip !== null && text !== null && crosshair !== null)
    tryVerify(function() { return chart.strokeSvg.length > 0 })
    verify(!tip.visible && !crosshair.visible)
    compare(text.text, "")

    mouseMove(chart, 295, 30)
    tryVerify(function() { return tip.visible && crosshair.visible })
    verify(text.text.indexOf("CPU") >= 0)
    mouseMove(test, 350, 150)
    tryVerify(function() { return !tip.visible && !crosshair.visible })
    compare(text.text, "")

    chart.samples = [5, 5, 5]
    tryVerify(function() { return chart.steady && !chart.built })
    chart.samples = [5, 10, 5]
    tryVerify(function() { return !chart.steady && chart.built && chart.strokeSvg.length > 0 })
  }
}
