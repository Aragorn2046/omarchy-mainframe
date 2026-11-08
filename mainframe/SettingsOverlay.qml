import QtQuick
import QtQuick.Layouts
import "lib/agents.js" as Agents

Rectangle {
  id: root
  property var config: ({hosts:{hosts:[]}, accounts:{accounts:[]}, settings:{overviewView:'systems',showUnavailable:false}})
  readonly property var cyberSwitches: [
    {key:'hudFrames', label:'HUD frames'}, {key:'neonGlow', label:'Neon glow'},
    {key:'gridBackdrop', label:'Grid backdrop'}, {key:'displayFont', label:'Display font'},
    {key:'segmentedMeters', label:'Segmented meters'}, {key:'dataAnimations', label:'Data animations'},
    {key:'titleGlitch', label:'Title glitch'}, {key:'scanlineSweep', label:'Scanline sweep'},
    {key:'pulsingStatusDots', label:'Pulsing status dots'}, {key:'bootSequence', label:'Boot sequence'}
  ]
  property string message: ''
  property color ink; property color mutedInk; property color accent; property color cardColor; property color borderColor
  signal save(string kind, var value)
  signal testHost(string alias)
  signal testAccount(var account)
  signal close()
  function saveSetting(key, value) {
    var settings = {}
    settings[key] = value
    save('settings', settings)
  }
  function saveCyber(key, value) {
    var switches = Object.assign({}, root.config.settings.cyber || {})
    switches[key] = value
    saveSetting('cyber', switches)
  }
  color: '#b0000000'; z: 100
  function account() {
    var provider = providerBox.currentText, item = {id: accountId.text, provider:provider, name:accountName.text}
    if (provider === 'command') { try { item.command = JSON.parse(accountValue.text) } catch(e) { item.command = [] } }
    else item.dir = accountValue.text
    return item
  }
  function reorder(index, delta) {
    var items = config.hosts.hosts.slice(), target = index + delta
    if (target < 0 || target >= items.length) return
    var x = items[index]; items[index] = items[target]; items[target] = x; save('hosts', {hosts:items})
  }
  MouseArea { anchors.fill: parent; onClicked: root.close() }
  Rectangle {
    anchors.centerIn: parent; width: Math.min(parent.width - 32, 720); height: Math.min(parent.height - 32, 850)
    color: root.cardColor; border.color: root.borderColor; radius: 10
    MouseArea { anchors.fill: parent }
    Flickable {
      anchors.fill: parent; anchors.margins: 20; contentWidth: width; contentHeight: body.implicitHeight; clip: true
      ColumnLayout {
        id: body; width: parent.width; spacing: 10
        RowLayout { Layout.fillWidth: true; Text { textFormat: Text.PlainText; text: 'SETTINGS'; color: root.ink; font.family: 'monospace'; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true } ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Close'; onClicked: root.close() } }
        Text { textFormat: Text.PlainText; text: root.message; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
        Text { textFormat: Text.PlainText; text: 'MACHINES'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 15; font.bold: true }
        Repeater {
          model: root.config.hosts.hosts
          delegate: RowLayout {
            required property var modelData; required property int index
            Layout.fillWidth: true
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Agents.safeHelp(modelData.name) + '  ·  ' + Agents.safeHelp(modelData.ssh); color: root.ink; font.family: 'monospace'; font.pixelSize: 15; elide: Text.ElideRight }
            ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; Layout.preferredWidth: 30; text: '↑'; onClicked: root.reorder(index, -1) }
            ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; Layout.preferredWidth: 30; text: '↓'; onClicked: root.reorder(index, 1) }
            ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Remove'; onClicked: { var a = root.config.hosts.hosts.slice(); a.splice(index, 1); root.save('hosts', {hosts:a}) } }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          ThemedTextField { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; id: hostName; Layout.fillWidth: true; placeholderText: 'Name' }
          ThemedTextField { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; id: hostAlias; Layout.fillWidth: true; placeholderText: 'SSH alias' }
          ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Test'; onClicked: root.testHost(hostAlias.text) }
          ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Add'; onClicked: { var a = root.config.hosts.hosts.slice(); a.push({name:hostName.text,ssh:hostAlias.text}); root.save('hosts', {hosts:a}) } }
        }
        Text { textFormat: Text.PlainText; text: 'ACCOUNTS'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 15; font.bold: true }
        Repeater {
          model: root.config.accounts.accounts
          delegate: RowLayout {
            required property var modelData; required property int index
            Layout.fillWidth: true
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Agents.safeHelp(modelData.name) + '  ·  ' + Agents.safeHelp(modelData.provider); color: root.ink; font.family: 'monospace'; font.pixelSize: 15; elide: Text.ElideRight }
            ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Test'; onClicked: root.testAccount(modelData) }
            ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Remove'; onClicked: { var a = root.config.accounts.accounts.slice(); a.splice(index, 1); root.save('accounts', {accounts:a}) } }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          ThemedComboBox { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; id: providerBox; model: ['claude','codex','command'] }
          ThemedTextField { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; id: accountId; Layout.fillWidth: true; placeholderText: 'ID' }
          ThemedTextField { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; id: accountName; Layout.fillWidth: true; placeholderText: 'Name' }
        }
        RowLayout {
          Layout.fillWidth: true
          ThemedTextField { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; id: accountValue; Layout.fillWidth: true; placeholderText: providerBox.currentText === 'command' ? 'Command as JSON array' : 'Account directory' }
          ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Test'; onClicked: root.testAccount(root.account()) }
          ThemedButton { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Add'; onClicked: { var a = root.config.accounts.accounts.slice(); a.push(root.account()); root.save('accounts', {accounts:a}) } }
        }
        Text { textFormat: Text.PlainText; text: 'DISPLAY'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 15; font.bold: true }
        ThemedCheckBox { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; text: 'Show unavailable providers'; checked: root.config.settings.showUnavailable === true; onClicked: root.saveSetting('showUnavailable', checked) }
        RowLayout {
          Text { textFormat: Text.PlainText; text: 'Default overview'; color: root.ink; font.family: 'monospace'; font.pixelSize: 15 }
          ThemedComboBox { ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor; model: ['systems','storage','agents']; currentIndex: Math.max(0, model.indexOf(root.config.settings.overviewView)); onActivated: root.saveSetting('overviewView', currentText) }
        }
        Text { textFormat: Text.PlainText; text: 'STYLE'; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 15; font.bold: true }
        RowLayout {
          Text { textFormat: Text.PlainText; text: 'Style'; color: root.ink; font.family: 'monospace'; font.pixelSize: 15 }
          ThemedComboBox {
            objectName: 'style-combo'
            ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor
            model: ['classic', 'cyberpunk']
            currentIndex: root.config.settings.style === 'cyberpunk' ? 1 : 0
            onActivated: root.saveSetting('style', currentText)
          }
        }
        Repeater {
          model: root.config.settings.style === 'cyberpunk' ? root.cyberSwitches : []
          delegate: ThemedCheckBox {
            required property var modelData
            objectName: 'cyber-switch-' + modelData.key
            ink: root.ink; mutedInk: root.mutedInk; accent: root.accent; cardColor: root.cardColor; borderColor: root.borderColor
            text: modelData.label
            checked: !root.config.settings.cyber || root.config.settings.cyber[modelData.key] !== false
            onClicked: root.saveCyber(modelData.key, checked)
          }
        }
      }
    }
  }
}
