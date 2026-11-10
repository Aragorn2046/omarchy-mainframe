import QtQuick
import QtQuick.Layouts
import "cyber" as Cyber
import "lib/agents.js" as Agents
import "lib/usage_value.js" as UsageValue

Item {
  id: root
  property var cyberStyle: null
  property alias flick: scrollView
  property var rows: []
  property var fleetLiveAgents: ({total:0, reporting:0, hostsTotal:0, hosts:[], accounts:[]})
  function liveAge(seconds) { if (seconds == null) return '—'; var m = Math.floor(seconds / 60), h = Math.floor(m / 60); return h ? h + 'h ' + (m % 60) + 'm' : m ? m + 'm' : Math.floor(seconds) + 's' }
  function liveMemory(bytes) { return bytes == null ? '—' : (bytes / 1048576).toFixed(0) + ' MB' }
  readonly property var sectionData: Agents.sections(rows)
  readonly property var valueTotals: [{label:'TODAY', value:valueData.totals.today}, {label:'LAST 7 DAYS', value:valueData.totals.seven}, {label:'LAST 30 DAYS', value:valueData.totals.thirty}]
  readonly property var valueRows: [{name:'Claude', totals:valueData.providers.claude}, {name:'Codex', totals:valueData.providers.codex}].concat(valueData.hosts)
  property var valueData: ({totals:{today:0,seven:0,thirty:0},providers:{claude:{},codex:{}},hosts:[],unpriced:[],partial:true,excluded:0})
  property color ink; property color mutedInk; property color accent; property color warning; property color critical
  property color cardColor; property color borderColor; property color track
  property bool busy: false
  property string status: ''
  signal refresh()
  property var packed: Agents.pack([], 0)
  function schedulePacking() { Qt.callLater(updatePacking) }
  function updatePacking() {
    var blocks = []
    for (var i = 0; i < sectionRepeater.count; i++) {
      var section = sectionRepeater.itemAt(i)
      if (!section) continue
      var heights = []
      for (var j = 0; j < section.cardRepeater.count; j++) {
        var card = section.cardRepeater.itemAt(j)
        heights.push(card ? card.contentHeight : 0)
      }
      blocks.push({key:section.modelData.key, headingHeight:section.headingItem.implicitHeight, cardHeights:heights})
    }
    packed = Agents.pack(blocks, scrollView.width)
  }
  onSectionDataChanged: schedulePacking()
  function checkLayout() {
    var failures = 0, cards = [], headings = []
    for (var i = 0; i < sectionRepeater.count; i++) {
      var section = sectionRepeater.itemAt(i)
      if (!section) continue
      headings.push({x:section.x + section.headingItem.x, y:section.y + section.headingItem.y, width:section.headingItem.width, height:section.headingItem.height})
      for (var j = 0; j < section.cardRepeater.count; j++) {
        var card = section.cardRepeater.itemAt(j)
        if (card) cards.push({item:card, x:section.x + card.x, y:section.y + card.y, width:card.width, height:card.height})
      }
    }
    function overlaps(a, b) { return a.x < b.x + b.width - 0.01 && a.x + a.width > b.x + 0.01 && a.y < b.y + b.height - 0.01 && a.y + a.height > b.y + 0.01 }
    for (i = 0; i < cards.length; i++) {
      var c = cards[i], failed = c.x < -0.01 || c.x + c.width > scrollView.width + 0.01 || c.height + 0.01 < c.item.contentHeight
      for (j = 0; j < cards.length; j++) if (i !== j && overlaps(c, cards[j])) failed = true
      for (j = 0; j < headings.length; j++) if (overlaps(c, headings[j])) failed = true
      if (failed) failures++
    }
    return failures
  }
  ColumnLayout {
    anchors.fill: parent; spacing: 10
    RowLayout {
      Layout.fillWidth: true
      Text { textFormat: Text.PlainText; text: 'AGENT USAGE'; color: root.mutedInk; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 12; Layout.fillWidth: true }
      Text { textFormat: Text.PlainText; text: root.status; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }

    }
    Text { textFormat: Text.PlainText; visible: root.rows.length === 0; text: 'No agent usage reports yet.'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 13 }
    Flickable {
      id: scrollView
      Layout.fillWidth: true; Layout.fillHeight: true; clip: true
      contentWidth: width; contentHeight: sections.y + valueCard.y + valueCard.height
      onWidthChanged: root.schedulePacking()
      Card {
        id: liveCard; objectName: 'agents-live-card'
        width: scrollView.width; height: liveContent.implicitHeight + 54
        cyberStyle: root.cyberStyle; accent: root.accent; title: 'Running now'; color: root.cardColor; borderColor: root.borderColor; labelColor: root.mutedInk
        ColumnLayout {
          id: liveContent; width: parent.width; spacing: 7
          RowLayout {
            Text { textFormat: Text.PlainText; objectName: 'agents-live-total'; text: String(root.fleetLiveAgents.total || 0); color: root.ink; font.family: 'monospace'; font.pixelSize: 28; font.bold: true }
            Text { textFormat: Text.PlainText; text: (root.fleetLiveAgents.reporting || 0) + ' of ' + (root.fleetLiveAgents.hostsTotal || 0) + ' machines reporting'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11; Layout.fillWidth: true }
          }
          Flow {
            objectName: 'agents-live-providers'; Layout.fillWidth: true; spacing: 4
            Repeater {
              model: (root.fleetLiveAgents.providers || []).length
              delegate: Rectangle {
                required property int index
                readonly property var providerData: root.fleetLiveAgents.providers[index]
                width: fleetChip.implicitWidth + 10; height: fleetChip.implicitHeight + 4; radius: 4; color: root.track
                Text { textFormat: Text.PlainText; id: fleetChip; anchors.centerIn: parent; text: parent.providerData.provider + ' ' + parent.providerData.count; color: root.ink; font.family: 'monospace'; font.pixelSize: 10 }
              }
            }
          }
          Text { textFormat: Text.PlainText; visible: root.fleetLiveAgents.total === 0; text: 'No agents running'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }
          Repeater {
            objectName: 'agents-live-hosts'; model: (root.fleetLiveAgents.hosts || []).length
            delegate: ColumnLayout {
              id: liveHost
              required property int index
              property bool expanded: false
              readonly property var modelData: root.fleetLiveAgents.hosts[index]
              Layout.fillWidth: true; spacing: 4
              RowLayout {
                objectName: 'agents-live-host-row'; Layout.fillWidth: true
                Text { textFormat: Text.PlainText; text: (liveHost.expanded ? '▾ ' : '▸ ') + liveHost.modelData.host; color: root.ink; font.family: 'monospace'; font.pixelSize: 12; Layout.preferredWidth: 160; elide: Text.ElideRight }
                Text { textFormat: Text.PlainText; objectName: 'agents-live-host-count'; text: liveHost.modelData.status === 'not reporting' ? 'not reporting' : String(liveHost.modelData.count) + (liveHost.modelData.cap == null ? '' : ' / ' + liveHost.modelData.cap); color: liveHost.modelData.over ? root.critical : liveHost.modelData.status === 'not reporting' ? root.mutedInk : root.ink; font.family: 'monospace'; font.pixelSize: 12 }
                Flow {
                  Layout.fillWidth: true; spacing: 4
                  Repeater {
                    model: liveHost.modelData.providers.length
                    delegate: Rectangle {
                      required property int index
                      readonly property var providerData: liveHost.modelData.providers[index]
                      width: chip.implicitWidth + 10; height: chip.implicitHeight + 4; radius: 4; color: root.track
                      Text { textFormat: Text.PlainText; id: chip; anchors.centerIn: parent; text: parent.providerData.provider + ' ' + parent.providerData.count; color: root.ink; font.family: 'monospace'; font.pixelSize: 10 }
                    }
                  }
                }
                Text { textFormat: Text.PlainText; visible: liveHost.modelData.headless > 0; text: liveHost.modelData.headless + ' headless'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10 }
                TapHandler { onTapped: liveHost.expanded = !liveHost.expanded }
              }
              Repeater {
                model: liveHost.expanded ? liveHost.modelData.sessions.length : 0
                delegate: Text {
                  required property int index
                  readonly property var session: liveHost.modelData.sessions[index]
                  Layout.fillWidth: true; textFormat: Text.PlainText; wrapMode: Text.Wrap
                  text: '    ' + session.provider + ' · ' + session.account + ' · ' + (session.project || '—') + ' · ' + root.liveAge(session.age_s) + ' · ' + (session.interactive === true ? 'interactive' : session.interactive === false ? 'headless' : 'unknown') + ' · ' + root.liveMemory(session.rss)
                  color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11
                }
              }
            }
          }
          Repeater {
            model: (root.fleetLiveAgents.accounts || []).length
            delegate: Text {
              required property int index
              readonly property var account: root.fleetLiveAgents.accounts[index]
              Layout.fillWidth: true; textFormat: Text.PlainText; text: account.label + ' · ' + account.provider + '  ' + account.count
              color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight
            }
          }
        }
      }
      Item {
        id: sections; y: liveCard.height + 10; width: scrollView.width; height: valueCard.y + valueCard.height
        Repeater {
          id: sectionRepeater; objectName: 'agents-sections-repeater'; model: root.sectionData.length
          onItemAdded: root.schedulePacking()
          onItemRemoved: root.schedulePacking()
          delegate: Item {
            id: section
            required property int index
            readonly property var modelData: root.sectionData[index] || ({heading:'', cards:[]})
            readonly property var cards: modelData.cards || []
            readonly property var placement: root.packed.blocks[index] || ({x:0, y:0, width:0, heading:{x:0, y:0, width:0}, cards:[]})
            property alias cardRepeater: repeater
            property alias headingItem: heading
            x: placement.x; y: placement.y; width: placement.width
            height: { var h = heading.height; for (var i = 0; i < placement.cards.length; i++) h = Math.max(h, placement.cards[i].y - y + placement.cards[i].height); return h }
            Text { id: heading; x: section.placement.heading.x - section.x; y: section.placement.heading.y - section.y; width: section.placement.heading.width; text: root.cyberStyle && root.cyberStyle.hudFrames ? (section.modelData.heading || '').toUpperCase() : (section.modelData.heading || ''); textFormat: Text.PlainText; color: root.mutedInk; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 12; onImplicitHeightChanged: root.schedulePacking() }
            Repeater {
                id: repeater; objectName: 'agents-cards-repeater'; model: section.cards.length
                onItemAdded: root.schedulePacking()
                onItemRemoved: root.schedulePacking()
                delegate: Rectangle {
                  id: card
                  required property int index
                  readonly property var modelData: section.cards[index] || ({name:'', age:'', limits:[], activity:[], models:[]})
                  readonly property var limits: modelData.limits || []
                  readonly property var activity: modelData.activity || []
                  readonly property var models: modelData.models || []
                  readonly property real contentHeight: content.implicitHeight + 24
                  readonly property var placement: section.placement.cards[index] || ({x:0, y:0, width:root.packed.columnWidth, height:0})
                  x: placement.x - section.x; y: placement.y - section.y; width: placement.width; height: placement.height
                  onContentHeightChanged: root.schedulePacking()
                  radius: root.cyberStyle && root.cyberStyle.hudFrames ? 0 : 10; color: root.cardColor; border.width: root.cyberStyle && root.cyberStyle.hudFrames ? 0 : 1; border.color: root.borderColor; opacity: modelData.stale ? 0.55 : 1; clip: true
                  Loader { objectName: "cyber-hud-loader"; anchors.fill: parent; active: root.cyberStyle && root.cyberStyle.hudFrames; sourceComponent: Cyber.HudFrame { accent: root.accent } }
                  ColumnLayout {
                    id: content; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 7
                    RowLayout {
                      Layout.fillWidth: true
                      Text { text: card.modelData.name || ''; color: root.ink; textFormat: Text.PlainText; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 15; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                      Text { text: card.modelData.tier || ''; color: root.mutedInk; textFormat: Text.PlainText; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight; Layout.maximumWidth: 130 }
                    }
                    Text { textFormat: Text.PlainText; visible: !!card.modelData.broken; text: "Can't read this report"; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12 }
                    Text { textFormat: Text.PlainText; visible: !card.modelData.broken; text: card.modelData.age || ''; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11 }
                    Text { visible: !!card.modelData.status; Layout.fillWidth: true; text: card.modelData.status || ''; textFormat: Text.PlainText; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11; wrapMode: Text.Wrap }
                    Text { visible: !!card.modelData.help; Layout.fillWidth: true; text: card.modelData.help || ''; textFormat: Text.PlainText; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11; wrapMode: Text.Wrap }
                    Repeater {
                      objectName: 'agents-limits-repeater'; model: card.limits.length
                      delegate: ColumnLayout {
                        required property int index
                        readonly property var modelData: card.limits[index] || ({label:'', percent:null, reset:''})
                        Layout.fillWidth: true; spacing: 3
                        RowLayout {
                          Layout.fillWidth: true
                          Text { objectName: 'agents-limit-title'; Layout.fillWidth: true; text: modelData.label || ''; textFormat: Text.PlainText; color: root.ink; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight }
                          Text { objectName: 'agents-limit-percent'; textFormat: Text.PlainText; text: (modelData.level ? modelData.level + ' · ' : '') + (modelData.percent == null ? '—' : Agents.percent(modelData.percent)); color: root.ink; font.family: 'monospace'; font.pixelSize: 11 }
                        }
                        Meter { objectName: 'agents-limit-meter'; cyberStyle: root.cyberStyle; Layout.fillWidth: true; implicitHeight: 6; fraction: modelData.percent == null ? 0 : modelData.percent / 100; fill: modelData.level === 'Critical' ? root.critical : modelData.level === 'Warning' ? root.warning : root.accent; track: root.track; critical: modelData.level === 'Critical'; warningInk: root.ink }
                        Text { textFormat: Text.PlainText; visible: !!modelData.reset; text: modelData.reset || ''; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10 }
                      }
                    }
                    Text { textFormat: Text.PlainText; visible: !!card.modelData.sharedStatsWith; Layout.fillWidth: true; text: 'Local stats shared with ' + (card.modelData.sharedStatsWith || '') + (card.modelData.sharedProjectsFolder ? ' (same projects folder)' : ''); color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 11; wrapMode: Text.Wrap }
                    Text { textFormat: Text.PlainText; visible: !card.modelData.broken && !card.modelData.sharedStatsWith && !!card.modelData.showLocalStats; Layout.fillWidth: true; text: 'Today  ' + Agents.units(card.modelData.prompts) + ' prompts · ' + Agents.units(card.modelData.sessions) + ' sessions · ' + Agents.units(card.modelData.tokens) + ' tokens'; color: root.ink; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight }
                    Text { textFormat: Text.PlainText; visible: !card.modelData.broken && !card.modelData.sharedStatsWith && !!card.modelData.showLocalStats; text: 'ACTIVITY · 14 DAYS'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10 }
                    Row {
                      visible: !card.modelData.broken && !card.modelData.sharedStatsWith && !!card.modelData.showLocalStats; Layout.fillWidth: true; Layout.preferredHeight: 25; spacing: 3
                      property real peak: Math.max(1, ...card.activity.map(function(day) { return day && Number(day.count) || 0 }))
                      Repeater {
                        objectName: 'agents-activity-repeater'; model: card.activity.length
                        delegate: Item {
                          required property int index
                          readonly property var modelData: card.activity[index] || ({date:'', count:0})
                          width: Math.max(3, (parent.width - 39) / 14); height: 25
                          Rectangle { objectName: 'agents-activity-bar'; anchors.bottom: parent.bottom; width: parent.width; height: Math.max(2, parent.height * (Number(modelData.count) || 0) / parent.parent.peak); color: root.accent; opacity: modelData.count ? 0.8 : 0.2; radius: 1 }
                          MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton; onEntered: { card.z = 10; section.z = 10 } onExited: { card.z = 0; section.z = 0 } }
                          Rectangle { visible: hover.containsMouse; z: 10; y: -20; width: tip.implicitWidth + 8; height: 20; color: root.cardColor; border.color: root.borderColor
                            Text { textFormat: Text.PlainText; id: tip; anchors.centerIn: parent; text: (modelData.date || '') + ': ' + (modelData.count || 0); color: root.ink; font.pixelSize: 10 } }
                        }
                      }
                    }
                    Repeater {
                      objectName: 'agents-models-repeater'; model: card.modelData.sharedStatsWith ? 0 : card.models.length
                      delegate: Text {
                        required property int index
                        readonly property var modelData: card.models[index] || ({name:''})
                        Layout.fillWidth: true
                        text: (modelData.name || '') + '  ' + (modelData.total !== undefined ? Agents.units(modelData.total) + ' total' : 'in ' + Agents.units(modelData.input) + ' · out ' + Agents.units(modelData.output) + ' · cache ' + Agents.units(modelData.cache))
                        textFormat: Text.PlainText; color: root.ink; font.family: 'monospace'; font.pixelSize: 10; elide: Text.ElideRight
                      }
                    }
                  }
                }
              }
          }
        }
        Card {
          id: valueCard; objectName: 'agents-value-card'
          x: 0; y: root.packed.height + (root.sectionData.length ? 10 : 0); width: sections.width; height: valueContent.implicitHeight + 54
          cyberStyle: root.cyberStyle; accent: root.accent; title: 'VALUE AT API PRICES'; color: root.cardColor; borderColor: root.borderColor; labelColor: root.mutedInk
          ColumnLayout {
            id: valueContent; width: parent.width; spacing: 6
            RowLayout {
              Layout.fillWidth: true
              Repeater {
                model: root.valueTotals.length
                delegate: ColumnLayout {
                  required property int index
                  readonly property var modelData: root.valueTotals[index] || ({label:'', value:0})
                  Layout.fillWidth: true
                  Text { textFormat: Text.PlainText; text: modelData.label; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10 }
                  Text { textFormat: Text.PlainText; text: UsageValue.money(modelData.value) + (root.valueData.partial ? ' partial' : '') + (root.valueData.stale ? ' · includes stale data' : ''); color: root.ink; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 16; font.bold: true }
                }
              }
            }
            Repeater {
              objectName: "agents-value-repeater"
              model: root.valueRows.length
              delegate: Text {
                required property int index
                readonly property var modelData: root.valueRows[index] || ({name:'', totals:{}})
                Layout.fillWidth: true; textFormat: Text.PlainText; color: root.ink; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight
                text: (modelData.name || modelData.host || '') + '  ' + (modelData.status && modelData.status !== 'ready' ? modelData.status : UsageValue.money((modelData.totals || {}).today) + '  /  ' + UsageValue.money((modelData.totals || {}).seven) + '  /  ' + UsageValue.money((modelData.totals || {}).thirty))
              }
            }
            Text { textFormat: Text.PlainText; visible: root.valueData.excluded > 0; text: root.valueData.excluded + (root.valueData.excluded === 1 ? ' machine not included' : ' machines not included'); color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10 }
            Repeater { objectName: 'agents-unpriced-repeater'; model: (root.valueData.unpriced && root.valueData.unpriced.length) || 0; delegate: Text { required property int index; readonly property var modelData: (root.valueData.unpriced && root.valueData.unpriced[index]) || ""; textFormat: Text.PlainText; text: modelData + ' — no price · ' + Agents.units((root.valueData.unpricedTokens || {})[modelData]) + ' tokens'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideRight } }
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: 'Estimate at public API list prices; subscription fees not included.'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 10; wrapMode: Text.Wrap }
          }
        }
      }
    }
  }
}
