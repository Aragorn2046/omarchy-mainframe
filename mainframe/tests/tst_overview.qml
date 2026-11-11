import QtQuick
import QtTest
import ".."
import "../cyber" as Cyber

TestCase {
  id: test
  name: "Overview"
  width: 900; height: 700; visible: true; when: windowShown
  property int selected: -1
  Cyber.CyberStyle { id: style; settings: ({}) }
  Cyber.CyberStyle { id: cyberAppearance; settings: ({}) }
  QtObject {
    id: shell
    property var cpuView: ({percentText:"100%", tempText:"95°C", tempPeakText:"peak 100°C", tempLevel:"hot", freqText:"3.20 GHz"})
    property color themeFg: "white"
    property color themeLabel: "gray"
    property color sensorColor: "red"
    property var themeColors: ({yellow:"#ffff00"})
    property int pxHero: 24
    property int pxValue: 14
    property int pxLabel: 12
  }
  OverviewView {
    id: overview
    anchors.fill: parent
    cyberStyle: style; warning: "#123456"; critical: "#654321"
    ink: "white"; mutedInk: "gray"; accent: "blue"; secondary: "cyan"; cardColor: "black"; borderColor: "gray"; track: "gray"
    rows: [{name:"Machine", status:"connected", badge:"WSL", index:3, view:null}]
    onOpenMachine: function(index) { test.selected = index }
  }
  Component {
    id: cpuHeaderComponent
    CpuHeader {
      cpuView: shell.cpuView; cyberStyle: cyberAppearance
      foreground: shell.themeFg; labelColor: shell.themeLabel
      hotColor: shell.sensorColor; warmColor: shell.themeColors.yellow
      heroSize: shell.pxHero; valueSize: shell.pxValue; labelSize: shell.pxLabel
    }
  }
  function init() {
    test.width = 900
    style.settings = ({})
    shell.cpuView = {percentText:"100%", tempText:"95°C", tempPeakText:"peak 100°C", tempLevel:"hot", freqText:"3.20 GHz"}
    overview.rows = [{name:"Machine", status:"connected", badge:"WSL", index:3, view:null}]
  }
  function cleanup() { test.width = 900 }
  function test_refresh_preserves_cards() {
    var repeater = findChild(overview, "overview-repeater")
    compare(repeater.count, 1)
    var card = repeater.itemAt(0)
    var title = findChild(card, 'overview-title')
    var badge = findChild(card, 'overview-badge')
    overview.rows = [{name:"Updated", status:"connected", badge:"Linux", index:4, view:null}]
    compare(repeater.itemAt(0), card)
    compare(title.text, "Updated")
    compare(badge.text, "Linux")
    overview.rows = [overview.rows[0], {name:"Second", badge:"", status:"idle", index:5, view:null}]
    compare(repeater.count, 2)
    var first = repeater.itemAt(0)
    compare(findChild(first, 'overview-title').text, "Updated")
    compare(findChild(first, 'overview-badge').text, "Linux")
    verify(repeater.itemAt(1) !== null)
    overview.rows = [overview.rows[0]]
    compare(repeater.count, 1)
    verify(repeater.itemAt(0) !== null)
  }
  function test_refresh_preserves_core_bars() {
    function row(value) {
      return {name:"Machine", status:"connected", badge:"WSL", index:3,
              view:{cpu:{percentText:value + "%", history:[10, value], cores:[{percent:value}]}}}
    }
    overview.rows = [row(25)]
    var cards = findChild(overview, "overview-repeater")
    var card = cards.itemAt(0)
    var cores = findChild(card, "overview-cores-repeater")
    var value = findChild(card, "overview-cpu-value")
    var bar = cores.itemAt(0)
    compare(value.text, "CPU  25%")
    compare(bar.opacity, 0.25)
    overview.rows = [row(75)]
    compare(cards.itemAt(0), card)
    compare(cores.itemAt(0), bar)
    compare(value.text, "CPU  75%")
    compare(bar.opacity, 0.75)
  }
  function test_missing_cores() {
    overview.rows = [{name:'Machine', badge:'', view:{cpu:{percentText:'—', history:[]}}}]
    var card = findChild(overview, 'overview-repeater').itemAt(0)
    compare(findChild(card, 'overview-cores-repeater').count, 0)
  }
  function test_cpu_header_from_shell_at_narrow_width() {
    var header = createTemporaryObject(cpuHeaderComponent, test)
    verify(header !== null)
    header.width = 600
    wait(20)
    var peak = findChild(header, "cpu-temperature-peak")
    var percent = findChild(header, "cpu-percent")
    var temp = findChild(header, "cpu-temperature")
    var freq = findChild(header, "cpu-frequency")
    verify(peak && percent && temp && freq)
    compare(peak.visible, true)
    compare(peak.text, "peak 100°C")
    verify(peak.width >= peak.implicitWidth)
    verify(!peak.truncated)
    var minWidth = percent.implicitWidth + temp.implicitWidth + freq.implicitWidth + header.spacing * 3
    header.width = minWidth + 4
    wait(20)
    verify(!peak.visible)
    verify(percent.width >= percent.implicitWidth)
    verify(temp.width >= temp.implicitWidth)
    verify(freq.width >= freq.implicitWidth)
    verify(!percent.truncated && !temp.truncated && !freq.truncated)
    shell.cpuView = {percentText:"100%", tempText:"95°C", tempPeakText:"", tempLevel:"hot", freqText:"3.20 GHz"}
    compare(peak.visible, false)
  }

  function test_narrow_cpu_row() {
    test.width = 250
    function row(temp) { return {name:"M", status:"connected", view:{cpu:{percentText:"100%", tempText:temp, tempLevel:"normal", history:[1,2], cores:[]}}} }
    overview.rows = [row("—")]
    wait(50)
    var card = findChild(overview, "overview-machine-card")
    var before = card.width
    var rowItem = findChild(card, "overview-cpu-row")
    var value = findChild(card, "overview-cpu-value")
    var temp = findChild(card, "overview-cpu-temperature")
    overview.rows = [row("120°C")]
    wait(50)
    compare(card.width, before)
    verify(rowItem.clip)
    verify(value.width >= value.implicitWidth)
    verify(temp.width < temp.implicitWidth)
    verify(value.x + value.width <= rowItem.width + 1)
    test.width = 900
  }

  function test_card_opens_machine() {
    var card = findChild(overview, "overview-machine-card")
    verify(card !== null)
    mouseClick(card, 100, 40)
    compare(selected, 3)
    selected = -1
    var chart = findChild(overview, "overview-cpu-sparkline")
    verify(chart !== null)
    mouseClick(chart, chart.width / 2, chart.height / 2)
    compare(selected, 3)
  }
  function test_cpu_temperature_colours_and_height() {
    function row(temp, level) {
      return {name:"Machine", status:"connected", view:{cpu:{percentText:"23%", tempText:temp, tempLevel:level, history:[10, 23], cores:[]}}}
    }
    overview.rows = [row("—", "normal")]
    var card = findChild(overview, "overview-machine-card")
    var value = findChild(card, "overview-cpu-value")
    var temp = findChild(card, "overview-cpu-temperature")
    wait(0)
    var cardHeight = card.height
    verify(!temp.visible)
    overview.rows = [row("47°C", "normal")]
    compare(value.text + temp.text, "CPU  23%  47°C")
    compare(temp.color, overview.ink)
    wait(0)
    compare(card.height, cardHeight)
    for (var i = 0; i < 2; i++) {
      style.settings = i ? {style:"cyberpunk", cyber:{dataAnimations:false}} : {style:"classic"}
      overview.rows = [row("85°C", "warm")]
      compare(temp.color, overview.warning)
      overview.rows = [row("95°C", "hot")]
      compare(temp.color, overview.critical)
      wait(0)
      compare(card.height, cardHeight)
    }
    overview.rows = [row("n/a", "normal")]
    verify(!temp.visible)
    overview.rows = [{name:"Machine", status:"connected", view:{cpu:{percentText:"23%", history:[10,23], cores:[]}}}]
    compare(temp.text, "")
    verify(!temp.visible)
    overview.rows = [row(42, "hot")]
    compare(temp.text, "")
    verify(!temp.visible)
    overview.rows = [row("47°C", "unexpected")]
    compare(temp.text, "  47°C")
    compare(temp.color, overview.ink)
  }
}
