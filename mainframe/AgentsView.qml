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
  readonly property var sectionData: Agents.sections(rows)
  readonly property var valueTotals: [{label:'TODAY', value:valueData.totals.today}, {label:'LAST 7 DAYS', value:valueData.totals.seven}, {label:'LAST 30 DAYS', value:valueData.totals.thirty}]
  readonly property var valueRows: [{name:'Claude', totals:valueData.providers.claude}, {name:'Codex', totals:valueData.providers.codex}].concat(valueData.hosts)
  property var valueData: ({totals:{today:0,seven:0,thirty:0},providers:{claude:{},codex:{}},hosts:[],unpriced:[],partial:true,excluded:0})
  property color ink; property color mutedInk; property color accent; property color warning; property color critical
  property color cardColor; property color borderColor; property color track
  property bool busy: false
  property string status: ''
  signal refresh()
  function checkLayout() {
    var failures = 0
    for (var i = 0; i < sectionRepeater.count; i++) { var section = sectionRepeater.itemAt(i); if (section) failures += section.checkLayout() }
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
      contentWidth: width; contentHeight: sections.implicitHeight
      ColumnLayout {
        id: sections; width: parent.width; spacing: 10
        Card {
          Layout.fillWidth: true; Layout.preferredHeight: valueContent.implicitHeight + 54
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
        Repeater {
          id: sectionRepeater; objectName: 'agents-sections-repeater'; model: root.sectionData.length
          delegate: ColumnLayout {
            id: section
            required property int index
            readonly property var modelData: root.sectionData[index] || ({heading:'', cards:[]})
            readonly property var cards: modelData.cards || []
            Layout.fillWidth: true; spacing: 10
            function checkLayout() {
              var failures = 0
              for (var i = 0; i < repeater.count; i++) { var c = repeater.itemAt(i); var first = repeater.itemAt(Math.floor(i / grid.columns) * grid.columns); if (c && (c.width > grid.width + 1 || c.height + 1 < c.contentHeight || (first && Math.abs(c.y - first.y) > 1))) failures++ }
              return failures
            }
            Text { text: root.cyberStyle && root.cyberStyle.hudFrames ? (section.modelData.heading || '').toUpperCase() : (section.modelData.heading || ''); textFormat: Text.PlainText; color: root.mutedInk; font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : 'monospace'; font.pixelSize: 12 }
            GridLayout {
              id: grid; Layout.fillWidth: true; columns: width >= 1300 ? 3 : 2; columnSpacing: 10; rowSpacing: 10
              Repeater {
                id: repeater; objectName: 'agents-cards-repeater'; model: section.cards.length
                delegate: Rectangle {
                  id: card
                  required property int index
                  readonly property var modelData: section.cards[index] || ({name:'', age:'', limits:[], activity:[], models:[]})
                  readonly property var limits: modelData.limits || []
                  readonly property var activity: modelData.activity || []
                  readonly property var models: modelData.models || []
                  readonly property real contentHeight: content.implicitHeight + 24
                  Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.preferredHeight: contentHeight; Layout.alignment: Qt.AlignTop
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
                          Text { Layout.fillWidth: true; text: modelData.label || ''; textFormat: Text.PlainText; color: root.ink; font.family: 'monospace'; font.pixelSize: 11; elide: Text.ElideRight }
                          Text { objectName: 'agents-limit-percent'; textFormat: Text.PlainText; text: (modelData.level ? modelData.level + ' · ' : '') + (modelData.percent == null ? '—' : Agents.percent(modelData.percent)); color: root.ink; font.family: 'monospace'; font.pixelSize: 11 }
                        }
                        Meter { cyberStyle: root.cyberStyle; Layout.fillWidth: true; implicitHeight: 6; fraction: modelData.percent == null ? 0 : modelData.percent / 100; fill: modelData.level === 'Critical' ? root.critical : modelData.level === 'Warning' ? root.warning : root.accent; track: root.track; critical: modelData.level === 'Critical'; warningInk: root.ink }
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
                          MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
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
        }
      }
    }
  }
}
