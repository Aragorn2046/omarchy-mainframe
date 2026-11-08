import QtQuick
import QtTest
import ".."
import "../lib/navigation.js" as Navigation
import "../lib/agents.js" as Agents

TestCase {
  id: testCase
  name: "Agents"
  width: 900; height: 700; visible: true; when: windowShown
  property var gapSection: null
  property var gapCard: null
  readonly property real valueCardGap: gapSection && gapCard ? gapCard.y - (gapSection.y + gapSection.height) : -1
  AgentsView {
    id: view
    anchors.fill: parent
    ink: "white"; mutedInk: "gray"; accent: "blue"; warning: "yellow"; critical: "red"; cardColor: "black"; borderColor: "gray"; track: "gray"
  }
  function valueData(amount, hosts) {
    return {totals:{today:amount,seven:0,thirty:0}, providers:{claude:{today:amount,seven:0,thirty:0},codex:{today:0,seven:0,thirty:0}}, hosts:hosts, unpriced:[], unpricedTokens:{}, partial:false, excluded:0}
  }
  function cleanup() {
    gapSection = null
    gapCard = null
    view.rows = []
    view.valueData = valueData(0, [])
    view.flick.cancelFlick()
    view.flick.contentY = 0
  }
  function test_value_card_follows_agent_sections() {
    var rows = []
    var categories = ['llm', 'video', 'image', 'voice', 'other']
    for (var i = 0; i < categories.length; i++)
      for (var j = 0; j < 3; j++) rows.push({name:categories[i] + j, category:categories[i]})
    view.valueData = {totals:{today:12,seven:65,thirty:240}, providers:{claude:{today:8,seven:42,thirty:150},codex:{today:4,seven:23,thirty:90}}, hosts:[{host:'dawn',totals:{today:12,seven:65,thirty:240}}], unpriced:[], unpricedTokens:{}, partial:false, excluded:0}
    compare(view.checkLayout(), 0)
    view.rows = rows
    var sections = findChild(view, 'agents-sections-repeater')
    var valueCard = findChild(view, 'agents-value-card')
    compare(sections.count, 5)
    tryVerify(function() {
      var last = sections.itemAt(sections.count - 1)
      return last && last.height > 0 && valueCard.y > last.y + last.height
    })
    gapSection = sections.itemAt(sections.count - 1)
    gapCard = valueCard
    tryCompare(testCase, 'valueCardGap', 10, 2000)
    compare(view.checkLayout(), 0)
    verify(view.flick.contentHeight > view.flick.height)
    // The standalone view has no End shortcut; the shell calls this function for End.
    view.flick.contentY = Navigation.scrollTarget(view.flick.contentY, view.flick.contentHeight, view.flick.height, 'bottom')
    var top = valueCard.mapToItem(view.flick, 0, 0).y
    var bottom = top + valueCard.height
    verify(valueCard.visible)
    verify(top >= 0)
    verify(bottom <= view.flick.height + 1)
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
  function test_missing_arrays_and_removing_delegates() {
    var value = valueData(1, [])
    value.unpriced = ['unknown']
    value.unpricedTokens = {unknown: 12}
    view.valueData = value
    var unpriced = findChild(view, 'agents-unpriced-repeater')
    compare(unpriced.count, 1)
    value = valueData(1, [])
    delete value.unpriced
    delete value.unpricedTokens
    view.valueData = value
    compare(unpriced.count, 0)

    view.rows = [{name:'Agent', category:'other', age:'', limits:[{label:'Limit', percent:50, reset:''}], models:[{name:'Model', total:1}], activity:[{date:'today', count:2}]}]
    var cards = findChild(view, 'agents-cards-repeater')
    compare(cards.count, 1)
    var card = cards.itemAt(0)
    var limits = findChild(card, 'agents-limits-repeater')
    var models = findChild(card, 'agents-models-repeater')
    compare(limits.count, 1)
    compare(models.count, 1)
    view.rows = [{name:'Agent', category:'other', age:''}]
    compare(limits.count, 0)
    compare(models.count, 0)
    view.rows = []
    compare(findChild(view, 'agents-sections-repeater').count, 0)
  }
  function test_same_count_refresh_updates_visible_values() {
    function row(percent, modelTotal, activityCount) {
      return {name:'Agent', category:'other', age:'', showLocalStats:true,
              limits:[{label:'Limit', percent:percent}],
              models:[{name:'Model', total:modelTotal}],
              activity:[{date:'today', count:activityCount}, {date:'yesterday', count:10}]}
    }
    view.rows = [row(25, 1, 2)]
    var card = findChild(view, 'agents-cards-repeater').itemAt(0)
    var limits = findChild(card, 'agents-limits-repeater')
    var models = findChild(card, 'agents-models-repeater')
    var activity = findChild(card, 'agents-activity-repeater')
    var percent = findChild(limits.itemAt(0), 'agents-limit-percent')
    var model = models.itemAt(0)
    var bar = findChild(activity.itemAt(0), 'agents-activity-bar')
    compare(percent.text, '25%')
    compare(model.text, 'Model  1 total')
    compare(bar.height, 5)
    view.rows = [row(75, 3, 6)]
    compare(findChild(view, 'agents-cards-repeater').itemAt(0), card)
    compare(limits.count, 1)
    compare(models.count, 1)
    compare(activity.count, 2)
    compare(percent.text, '75%')
    compare(model.text, 'Model  3 total')
    compare(bar.height, 15)
    view.rows = [row(undefined, 3, 6)]
    compare(percent.text, '—')
  }
  function test_normalized_limits_show_matching_text_and_meter() {
    // Values match the records emitted by agents_usage.py for helper fractions.
    var record = {name:'Agent', limits:[{label:'Session', percent:55},
                                       {title:'Fable Weekly', percent:80}]}
    view.rows = [Agents.parse(JSON.stringify(record), 'agent', Date.now())]
    var card = findChild(view, 'agents-cards-repeater').itemAt(0)
    var limits = findChild(card, 'agents-limits-repeater')
    compare(limits.count, 2)
    compare(findChild(limits.itemAt(0), 'agents-limit-percent').text, '55%')
    compare(findChild(limits.itemAt(0), 'agents-limit-meter').shown, 0.55)
    compare(findChild(limits.itemAt(1), 'agents-limit-percent').text, 'Warning · 80%')
    compare(findChild(limits.itemAt(1), 'agents-limit-meter').shown, 0.8)
    compare(findChild(limits.itemAt(1), 'agents-limit-title').text, 'Fable Weekly')
    record.limits = [{percent:null}, {percent:true}, {percent:false}, {}, {}, {}]
    view.rows = [Agents.parse(JSON.stringify(record), 'agent', Date.now())]
    compare(limits.count, 6)
    for (var i = 0; i < limits.count; i++)
      compare(findChild(limits.itemAt(i), 'agents-limit-percent').text, '—')
  }
}
