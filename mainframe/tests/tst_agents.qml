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
    view.cyberStyle = null
    view.rows = []
    view.valueData = valueData(0, [])
    testCase.width = 900
  }
  function cleanup() {
    view.fleetLiveAgents = {total:0, reporting:0, hostsTotal:0, hosts:[], accounts:[]}
    testCase.width = 900
    view.rows = []
    view.valueData = valueData(0, [])
    view.cyberStyle = null
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
  function test_live_not_reporting_and_layout() {
    testCase.width = 1600
    view.rows = [{name:'Agent', category:'llm'}]
    var live = findChild(view, 'agents-live-card')
    var card = findChild(view, 'agents-cards-repeater').itemAt(0)
    var empty = findChild(view, 'agents-live-empty')
    var missing = findChild(view, 'agents-live-not-reporting')
    var host = {host:'A long reporting machine name that must fit inside this card', count:1, cap:2, over:false, headless:1, providers:[{provider:'codex', count:1}], sessions:[], status:'reporting'}
    var unavailable = function(name) { return {host:name, status:'not reporting'} }
    view.fleetLiveAgents = {total:1, reporting:1, hostsTotal:4, providers:[{provider:'codex', count:1}], hosts:[host, unavailable('Host A'), unavailable('Host B'), unavailable('Host C')], accounts:[{label:'An unusually long account label that must wrap inside the card', count:1}]}
    tryVerify(function() { return live.width === card.width && live.width < view.flick.width && view.checkLayout() === 0 })
    compare(findChild(view, 'agents-live-hosts').count, 1)
    compare(missing.text, 'Not reporting: Host\u00a0A · Host\u00a0B · Host\u00a0C')
    verify(missing.visible)
    verify(!findChild(view, 'agents-live-providers').visible)
    compare(findChild(view, 'agents-live-reporting').text, '1/4 reporting')
    verify(live.x < card.mapToItem(view.flick.contentItem, 0, 0).x)
    testCase.width = 350
    tryVerify(function() { return live.width === view.flick.width && card.width === live.width && view.checkLayout() === 0 })
    verify(card.mapToItem(view.flick.contentItem, 0, 0).y >= live.mapToItem(view.flick.contentItem, 0, 0).y + live.height)
    view.fleetLiveAgents = {total:0, reporting:0, hostsTotal:3, hosts:[unavailable('Host A'), unavailable('Host B'), unavailable('Host C')], accounts:[]}
    compare(empty.text, 'No machine reporting')
    compare(findChild(view, 'agents-live-total').text, '—')
    compare(findChild(view, 'agents-live-hosts').count, 0)
    compare(findChild(view, 'agents-live-reporting').text, '0/3 reporting')
    tryVerify(function() { return view.checkLayout() === 0 })
    view.fleetLiveAgents = {total:0, reporting:1, hostsTotal:1, hosts:[Object.assign({}, host, {count:0, headless:0})], accounts:[]}
    compare(empty.text, 'No agents running')
    compare(findChild(view, 'agents-live-reporting').text, '1/1 reporting')
    tryVerify(function() { return view.checkLayout() === 0 })
  }
  function test_live_expansion_and_wrapping() {
    testCase.width = 350
    var session = {provider:'codex', account:'x'.repeat(100), project:'project', age_s:90, interactive:false, rss:1048576}
    var providers = [{provider:'p'.repeat(100), count:1}]
    var host = {host:'A long reporting host name ' + 'h'.repeat(100), count:1, cap:0, over:true, headless:1, providers:providers, sessions:[session], status:'reporting'}
    view.fleetLiveAgents = {total:1, truncated:true, reporting:2, hostsTotal:3, providers:providers, hosts:[host, Object.assign({}, host, {host:'other'}), {host:'A long missing host name ' + 'm'.repeat(100), status:'not reporting'}], accounts:[{label:session.account, count:1}]}
    var live = findChild(view, 'agents-live-card')
    var rows = findChild(view, 'agents-live-hosts')
    var line = findChild(rows.itemAt(0), 'agents-live-host-row')
    tryVerify(function() { return view.checkLayout() === 0 && line.width > 0 })
    verify(findChild(view, 'agents-live-providers').visible)
    compare(findChild(view, 'agents-live-reporting').text, '2/3+ reporting')
    compare(findChild(rows.itemAt(0), 'agents-live-host-count').color, view.critical)
    var oldHeight = live.height
    var oldContentHeight = view.flick.contentHeight
    mouseClick(line, 5, 5)
    tryVerify(function() { return findChild(rows.itemAt(0), 'agents-live-session') !== null && live.height > oldHeight && view.flick.contentHeight > oldContentHeight && view.checkLayout() === 0 })
    var detail = findChild(rows.itemAt(0), 'agents-live-session')
    verify(detail.text.indexOf('codex · ') === 0 && detail.text.indexOf('headless · 1 MB') >= 0)
    compare(detail.wrapMode, Text.Wrap)
    var accounts = findChild(view, 'agents-live-accounts')
    verify(accounts.lineCount > 1)
    function verifyTextGeometry(item) {
      if (item.visible && typeof item.paintedWidth === 'number') {
        verify(item.width > 0, 'Text has no width: ' + item.text)
        verify(item.paintedWidth <= item.width + 0.5, 'Text paints outside its width: ' + item.text)
      }
      for (var i = 0; i < item.children.length; i++) verifyTextGeometry(item.children[i])
    }
    verifyTextGeometry(live)
  }
  function test_live_host_rows_and_word_wrapping() {
    testCase.width = 1600
    var providers = [{provider:'claude', count:13}, {provider:'codex', count:1}, {provider:'grok', count:1}, {provider:'another-provider', count:2}, {provider:'one more provider', count:3}]
    var host = {host:'this machine', count:17, cap:20, over:false, headless:0, providers:providers, sessions:[], status:'reporting'}
    view.fleetLiveAgents = {total:17, reporting:2, hostsTotal:3, providers:providers, hosts:[host, Object.assign({}, host, {host:'another machine'}), {host:'A machine that is not reporting', status:'not reporting'}], accounts:[{label:'first account',count:13}, {label:'second account on this machine',count:1}]}
    var live = findChild(view, 'agents-live-card')
    var rows = findChild(view, 'agents-live-hosts')
    var row = findChild(rows.itemAt(0), 'agents-live-host-row')
    var name = findChild(rows.itemAt(0), 'agents-live-host-name')
    var count = findChild(rows.itemAt(0), 'agents-live-host-count')
    var hostProviders = findChild(rows.itemAt(0), 'agents-live-host-providers')
    var accounts = findChild(view, 'agents-live-accounts')
    var missing = findChild(view, 'agents-live-not-reporting')
    var fleetProviders = findChild(view, 'agents-live-providers')
    tryVerify(function() { return view.checkLayout() === 0 && row.width > 0 && hostProviders.lineCount > 1 })
    compare(count.text, '17 / 20')
    compare(count.color, findChild(view, 'agents-live-total').color)
    verify(count.font.bold)
    verify(Math.abs(count.x + count.width - row.width) < 1)
    verify(name.x + name.width <= count.x)
    verify(hostProviders.y >= row.y + row.height)
    compare(hostProviders.color, view.mutedInk)
    verify(hostProviders.x + hostProviders.width <= live.width - 12)
    compare(hostProviders.text, 'claude\u00a013 · codex\u00a01 · grok\u00a01 · another-provider\u00a02 · one\u00a0more\u00a0provider\u00a03')
    compare(fleetProviders.text, hostProviders.text)
    compare(accounts.text, 'first\u00a0account\u00a013 · second\u00a0account\u00a0on\u00a0this\u00a0machine\u00a01')
    var pairs = accounts.text.split(' · ')
    for (var i = 0; i < pairs.length; i++) compare(pairs[i].indexOf(' '), -1)
    testCase.width = 350
    tryVerify(function() { return live.width === view.flick.width && view.checkLayout() === 0 })
    var measure = Qt.createQmlObject('import QtQuick; Text {}', testCase)
    measure.font = accounts.font
    for (i = 0; i < pairs.length; i++) {
      measure.text = pairs[i]
      verify(measure.implicitWidth <= accounts.width)
    }
    measure.text = accounts.text
    verify(measure.implicitWidth > accounts.width)
    compare(accounts.lineCount, pairs.length)
    measure.destroy()
    compare(accounts.wrapMode, Text.Wrap)
    compare(missing.wrapMode, Text.Wrap)
    compare(hostProviders.wrapMode, Text.Wrap)
    compare(fleetProviders.wrapMode, Text.Wrap)
  }
  function test_live_cyber_style() {
    var style = Qt.createQmlObject('import QtQuick; QtObject { property bool hudFrames: true; property bool displayFont: true; property string fontFamily: "monospace" }', testCase)
    view.cyberStyle = style
    view.rows = [{name:'Agent', category:'llm'}]
    view.fleetLiveAgents = {total:1, reporting:1, hostsTotal:1, hosts:[{host:'host', count:1, cap:null, over:false, headless:0, providers:[{provider:'codex',count:1}], sessions:[], status:'reporting'}], accounts:[]}
    var live = findChild(view, 'agents-live-card')
    tryVerify(function() { return findChild(live, 'cyber-hud-loader').active && live.height === live.contentHeight && view.checkLayout() === 0 })
    view.cyberStyle = null
    tryVerify(function() { return !findChild(live, 'cyber-hud-loader').active })
    style.destroy()
  }
  function test_live_leaves_columns_for_usage() {
    testCase.width = 1600
    var rows = []
    for (var i = 0; i < 5; i++) rows.push({name:'Agent ' + i, category:'llm'})
    view.rows = rows
    tryVerify(function() { return view.packed.columns === 4 && view.packed.blocks.length === 2 && view.checkLayout() === 0 })
    var live = view.packed.blocks[0].cards[0]
    var usage = view.packed.blocks[1].cards[0]
    verify(usage.x > live.x)
    compare(usage.y, live.y)
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
      return view.packed.blocks.length === 6 && view.packed.height > 0 && valueCard.y === view.packed.height + 10 && view.checkLayout() === 0
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
    tryVerify(function() { return view.packed.columns === 5 && view.packed.blocks.length === 4 && view.checkLayout() === 0 })
    var video = view.packed.blocks[2].cards[0]
    var voice = view.packed.blocks[3].cards[0]
    verify(video.x !== voice.x)
    verify(Math.abs(video.y - voice.y) <= 1)
  }
  function test_packing_updates_after_content_and_width_change() {
    testCase.width = 900
    view.rows = [{name:'Agent', category:'other', age:'', limits:[]}]
    var section = findChild(view, 'agents-sections-repeater').itemAt(0)
    var card = findChild(section, 'agents-cards-repeater').itemAt(0)
    tryVerify(function() { return view.packed.blocks.length === 2 && card.height === card.contentHeight })
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
