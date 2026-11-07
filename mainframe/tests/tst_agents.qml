import QtQuick
import QtTest
import ".."

TestCase {
  name: "Agents"
  width: 900; height: 700; visible: true; when: windowShown
  AgentsView {
    id: view
    anchors.fill: parent
    ink: "white"; mutedInk: "gray"; accent: "blue"; warning: "yellow"; critical: "red"; cardColor: "black"; borderColor: "gray"; track: "gray"
  }
  function valueData(amount, hosts) {
    return {totals:{today:amount,seven:0,thirty:0}, providers:{claude:{today:amount,seven:0,thirty:0},codex:{today:0,seven:0,thirty:0}}, hosts:hosts, unpriced:[], unpricedTokens:{}, partial:false, excluded:0}
  }
  function test_refresh_preserves_value_rows() {
    view.valueData = valueData(1, [])
    var repeater = findChild(view, "agents-value-repeater")
    compare(repeater.count, 2)
    var row = repeater.itemAt(0)
    var oldText = row.text
    view.valueData = valueData(2, [])
    compare(repeater.itemAt(0), row)
    verify(row.text !== oldText)
    compare(row.modelData.totals.today, 2)
    view.valueData = valueData(2, [{host:"host", totals:{today:1,seven:0,thirty:0}}])
    compare(repeater.count, 3)
    verify(repeater.itemAt(2) !== null)
    view.valueData = valueData(2, [])
    compare(repeater.count, 2)
    verify(repeater.itemAt(0) !== null)
  }
}
