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
    yMax: 100
    samples: [10, 20, 30]
  }

  function test_painted_state_stays_in_sync() {
    chart.samples = [10, 20, 30]
    tryVerify(function() { return chart.built && chart.paintedSamples[2] === 30 })
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
    compare(chart.strokeSvg, "M289.83 93.65Q294.92 88.8 297.46 91.23L300 93.65")
    compare(label.values[1], 10)
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
    chart.rateChart = false
    chart.yMax = 100
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
