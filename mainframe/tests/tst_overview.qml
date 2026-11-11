import QtQuick
import QtTest
import ".."

TestCase {
  id: test
  name: "Overview"
  width: 900; height: 700; visible: true; when: windowShown
  property int selected: -1
  QtObject { id: shell; property var themeColors: ({yellow:"#123456"}); property color sensorColor: "#654321" }
  OverviewView {
    id: overview
    anchors.fill: parent
    ink: "white"; mutedInk: "gray"; accent: "blue"; secondary: "cyan"; cardColor: "black"; borderColor: "gray"; track: "gray"
    rows: [{name:"Machine", status:"connected", badge:"WSL", index:3, view:null}]
    onOpenMachine: function(index) { test.selected = index }
  }
  function init() {
    overview.rows = [{name:"Machine", status:"connected", badge:"WSL", index:3, view:null}]
  }
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
    compare(card.height, cardHeight)
    overview.rows = [row("85°C", "warm")]
    compare(temp.color, shell.themeColors.yellow)
    overview.rows = [row("95°C", "hot")]
    compare(temp.color, shell.sensorColor)
    compare(card.height, cardHeight)
    overview.rows = [row("n/a", "normal")]
    verify(!temp.visible)
  }
}
