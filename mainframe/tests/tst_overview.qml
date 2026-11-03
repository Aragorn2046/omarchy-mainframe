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
