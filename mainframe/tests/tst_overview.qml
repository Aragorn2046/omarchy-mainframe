import QtQuick
import QtTest
import ".."

TestCase {
  id: test
  name: "Overview"
  width: 900; height: 700; visible: true; when: windowShown
  property int selected: -1
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
    overview.rows = [{name:"Updated", status:"connected", badge:"WSL", index:4, view:null}]
    compare(repeater.itemAt(0), card)
    compare(card.modelData.name, "Updated")
    overview.rows = [overview.rows[0], {name:"Second", badge:"", status:"idle", index:5, view:null}]
    compare(repeater.count, 2)
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
}
