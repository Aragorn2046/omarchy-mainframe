import QtQuick
import QtTest
import ".."
import "../lib/navigation.js" as Navigation
import "../lib/agents.js" as Agents

TestCase {
  id: testCase
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
  function init() {
    view.fleetLiveAgents = {total:0, reporting:0, hostsTotal:0, hosts:[], accounts:[]}
  }
  function cleanup() {
    view.fleetLiveAgents = {total:0, reporting:0, hostsTotal:0, hosts:[], accounts:[]}
    testCase.width = 900
    view.rows = []
    view.valueData = valueData(0, [])
    view.flick.cancelFlick()
    view.flick.contentY = 0
  }
  function test_live_card() {
    compare(view.checkLayout(), 0)
    view.rows = [{name:'Agent', category:'llm'}]
    view.fleetLiveAgents = {total:2, reporting:1, hostsTotal:1, hosts:[{host:'laptop', count:2, cap:3, over:false, headless:0, providers:[], sessions:[], status:'reporting'}], accounts:[]}
    compare(findChild(view, 'agents-live-total').text, '2')
    var rows = findChild(view, 'agents-live-hosts')
    compare(rows.count, 1)
    compare(findChild(rows.itemAt(0), 'agents-live-host-count').text, '2 / 3')
    tryVerify(function() { return view.checkLayout() === 0 })
    view.fleetLiveAgents = {total:256, truncated:true, reporting:1, hostsTotal:1, hosts:[{host:'host', count:256, truncated:true, cap:256, over:true, headless:0, providers:[], sessions:[], status:'reporting'}], accounts:[]}
    compare(findChild(view, 'agents-live-total').text, '256+')
    compare(findChild(rows.itemAt(0), 'agents-live-host-count').text, '256+ / 256')
    tryVerify(function() { return view.checkLayout() === 0 })
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
      return view.packed.blocks.length === 5 && view.packed.height > 0 && valueCard.y === view.packed.height + 10 && view.checkLayout() === 0
    })
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
  function test_video_and_voice_share_space() {
    testCase.width = 1750
    var rows = []
    for (var i = 0; i < 6; i++) rows.push({name:'LLM ' + i, category:'llm', age:''})
    rows.push({name:'Higgsfield', category:'video', age:''})
    rows.push({name:'ElevenLabs', category:'voice', age:''})
    view.rows = rows
    tryVerify(function() { return view.packed.columns === 5 && view.packed.blocks.length === 3 && view.checkLayout() === 0 })
    var video = view.packed.blocks[1].cards[0]
    var voice = view.packed.blocks[2].cards[0]
    verify(video.x !== voice.x)
    verify(Math.abs(video.y - voice.y) <= 1)
  }
  function test_packing_updates_after_content_and_width_change() {
    testCase.width = 900
    view.rows = [{name:'Agent', category:'other', age:'', limits:[]}]
    var section = findChild(view, 'agents-sections-repeater').itemAt(0)
    var card = findChild(section, 'agents-cards-repeater').itemAt(0)
    tryVerify(function() { return view.packed.blocks.length === 1 && card.height === card.contentHeight })
    var oldHeight = card.height
    view.rows = [{name:'Agent', category:'other', age:'', limits:[{label:'Limit', percent:50}]}]
    tryVerify(function() { return card.height > oldHeight && card.height === card.contentHeight && view.checkLayout() === 0 })
    testCase.width = 350
    tryVerify(function() { return view.packed.columns === 1 && card.width === view.flick.width && view.checkLayout() === 0 })
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
    var record = {name:'Agent', limits:[{label:'Session', percent:29},
                                       {title:'Fable Weekly', percent:80}]}
    view.rows = [Agents.parse(JSON.stringify(record), 'agent', Date.now())]
    var card = findChild(view, 'agents-cards-repeater').itemAt(0)
    var limits = findChild(card, 'agents-limits-repeater')
    compare(limits.count, 2)
    compare(findChild(limits.itemAt(0), 'agents-limit-percent').text, '29%')
    compare(findChild(limits.itemAt(0), 'agents-limit-meter').shown, 0.29)
    compare(findChild(limits.itemAt(1), 'agents-limit-percent').text, 'Warning · 80%')
    compare(findChild(limits.itemAt(1), 'agents-limit-meter').shown, 0.8)
    compare(findChild(limits.itemAt(1), 'agents-limit-title').text, 'Fable Weekly')
    record.limits = [{percent:null}, {percent:true}, {percent:false}, {}, {}, {}]
    card = null
    limits = null
    view.rows = [Agents.parse(JSON.stringify(record), 'agent', Date.now())]
    tryVerify(function() {
      var cards = findChild(view, 'agents-cards-repeater')
      var currentCard = cards && cards.itemAt(0)
      var currentLimits = currentCard && findChild(currentCard, 'agents-limits-repeater')
      return currentLimits && currentLimits.count === 6 && currentLimits.itemAt(5)
    })
    card = findChild(view, 'agents-cards-repeater').itemAt(0)
    limits = findChild(card, 'agents-limits-repeater')
    compare(limits.count, 6)
    for (var i = 0; i < limits.count; i++)
      compare(findChild(limits.itemAt(i), 'agents-limit-percent').text, '—')
  }
}
