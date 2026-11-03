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
