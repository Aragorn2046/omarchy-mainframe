import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "lib/agents.js" as Agents

Rectangle {
  id: root
  property var config: ({hosts:{hosts:[]}, accounts:{accounts:[]}, settings:{overviewView:'systems',showUnavailable:false}})
  property string message: ''
  property color ink; property color mutedInk; property color accent; property color cardColor; property color borderColor
  signal save(string kind, var value)
  signal testHost(string alias)
  signal testAccount(var account)
  signal close()
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
        RowLayout { Layout.fillWidth: true; Text { textFormat: Text.PlainText; text: 'SETTINGS'; color: root.ink; font.family: 'monospace'; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true } Button { text: 'Close'; onClicked: root.close() } }
        Text { textFormat: Text.PlainText; text: root.message; color: root.mutedInk; font.family: 'monospace'; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
        Text { textFormat: Text.PlainText; text: 'MACHINES'; color: root.mutedInk; font.family: 'monospace'; font.bold: true }
        Repeater {
          model: root.config.hosts.hosts
          delegate: RowLayout {
            required property var modelData; required property int index
            Layout.fillWidth: true
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Agents.safeHelp(modelData.name) + '  ·  ' + Agents.safeHelp(modelData.ssh); color: root.ink; elide: Text.ElideRight }
            Button { text: '↑'; onClicked: root.reorder(index, -1) }
            Button { text: '↓'; onClicked: root.reorder(index, 1) }
            Button { text: 'Remove'; onClicked: { var a = root.config.hosts.hosts.slice(); a.splice(index, 1); root.save('hosts', {hosts:a}) } }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          TextField { id: hostName; Layout.fillWidth: true; placeholderText: 'Name' }
          TextField { id: hostAlias; Layout.fillWidth: true; placeholderText: 'SSH alias' }
          Button { text: 'Test'; onClicked: root.testHost(hostAlias.text) }
          Button { text: 'Add'; onClicked: { var a = root.config.hosts.hosts.slice(); a.push({name:hostName.text,ssh:hostAlias.text}); root.save('hosts', {hosts:a}) } }
        }
        Text { textFormat: Text.PlainText; text: 'ACCOUNTS'; color: root.mutedInk; font.family: 'monospace'; font.bold: true }
        Repeater {
          model: root.config.accounts.accounts
          delegate: RowLayout {
            required property var modelData; required property int index
            Layout.fillWidth: true
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Agents.safeHelp(modelData.name) + '  ·  ' + Agents.safeHelp(modelData.provider); color: root.ink; elide: Text.ElideRight }
            Button { text: 'Test'; onClicked: root.testAccount(modelData) }
            Button { text: 'Remove'; onClicked: { var a = root.config.accounts.accounts.slice(); a.splice(index, 1); root.save('accounts', {accounts:a}) } }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          ComboBox { id: providerBox; model: ['claude','codex','command'] }
          TextField { id: accountId; Layout.fillWidth: true; placeholderText: 'ID' }
          TextField { id: accountName; Layout.fillWidth: true; placeholderText: 'Name' }
        }
        RowLayout {
          Layout.fillWidth: true
          TextField { id: accountValue; Layout.fillWidth: true; placeholderText: providerBox.currentText === 'command' ? 'Command as JSON array' : 'Account directory' }
          Button { text: 'Test'; onClicked: root.testAccount(root.account()) }
          Button { text: 'Add'; onClicked: { var a = root.config.accounts.accounts.slice(); a.push(root.account()); root.save('accounts', {accounts:a}) } }
        }
        Text { textFormat: Text.PlainText; text: 'DISPLAY'; color: root.mutedInk; font.family: 'monospace'; font.bold: true }
        CheckBox { text: 'Show unavailable providers'; checked: root.config.settings.showUnavailable === true; onClicked: root.save('settings', {showUnavailable:checked, overviewView:root.config.settings.overviewView || 'systems'}) }
        RowLayout {
          Text { textFormat: Text.PlainText; text: 'Default overview'; color: root.ink }
          ComboBox { model: ['systems','storage','agents']; currentIndex: Math.max(0, model.indexOf(root.config.settings.overviewView)); onActivated: root.save('settings', {showUnavailable:root.config.settings.showUnavailable === true, overviewView:currentText}) }
        }
      }
    }
  }
}
