import QtQuick
import QtQuick.Layouts
import "lib/storage.js" as Storage
import "lib/metrics.js" as Metrics

// frontend-design pre-emit critique: P5 H5 E4 S5 R5 V4
Card {
  id: root
  property var data: null
  property var palette: ({})
  property color ink
  property color mutedInk
  property color track
  property bool remote: false
  property bool scanning: false
  property string scanError: ""
  property var progress: ({})
  property double now: Date.now()
  property var rows: Storage.model(data, palette, Metrics.oklabDistance)
  property alias flick: list
  property color accent
  property int currentRow: 0
  property string selectedCategory: ""
  property bool keyboardSelection: false
  onCurrentRowChanged: {
    if (currentRow >= 0 && currentRow < rows.length) selectedCategory = rows[currentRow].name
  }
  onRowsChanged: {
    var selected = rows.findIndex(function(row) { return row.name === selectedCategory })
    currentRow = selected >= 0 ? selected : Math.max(0, Math.min(currentRow, rows.length - 1))
    selectedCategory = rows.length ? rows[currentRow].name : ""
  }
  function moveRow(step) {
    if (!list.visible || rows.length === 0) return
    currentRow = Math.max(0, Math.min(rows.length - 1, currentRow + (keyboardSelection ? step : 0)))
    keyboardSelection = true
    var row = rowRepeater.itemAt(currentRow)
    if (!row) return
    var top = row.mapToItem(list.contentItem, 0, 0).y
    if (top < list.contentY) list.contentY = top
    else if (top + row.height > list.contentY + list.height) list.contentY = top + row.height - list.height
    list.contentY = Math.max(0, Math.min(Math.max(0, list.contentHeight - list.height), list.contentY))
  }
  function selectAfterScroll(kind) {
    if (!list.visible || rows.length === 0) return
    keyboardSelection = true
    if (kind === "top") { currentRow = 0; return }
    if (kind === "bottom") { currentRow = rows.length - 1; return }
    for (var i = 0; i < rows.length; i++) {
      var row = rowRepeater.itemAt(i)
      if (!row) continue
      var top = row.mapToItem(list.contentItem, 0, 0).y
      if (top >= list.contentY && top + row.height <= list.contentY + list.height) {
        currentRow = i
        return
      }
    }
  }
  function openCurrentRow() {
    if (keyboardSelection && list.visible && rows.length > 0) root.openCategory(rows[currentRow].name)
  }
  function checkStorageLayout() {
    var bad = 0
    var width = list.width
    var children = rowsColumn.children
    for (var i = 0; i < children.length; i++) {
      var child = children[i]
      if (child.objectName === "storage-row" && child.visible && (child.x < -0.5 || child.x + child.width > width + 0.5 || child.height < 30)) bad++
    }
    if (content.width < 0 || content.height < 0 || list.width < 0 || list.height < 0) bad++
    return bad
  }
  signal back()
  signal rescan()
  signal openCategory(string category)
  title: "Storage"
  clip: true
  Timer { interval: 30000; repeat: true; running: root.visible; onTriggered: root.now = Date.now() }
  ColumnLayout {
    id: content
    anchors.fill: parent
    spacing: 8
    RowLayout {
      Layout.fillWidth: true
      Rectangle {
        implicitWidth: backText.implicitWidth + 20; implicitHeight: 32; radius: 5
        color: backMouse.containsMouse ? root.track : "transparent"
        border.color: root.borderColor
        Text { textFormat: Text.PlainText; id: backText; anchors.centerIn: parent; text: "← Back"; color: root.ink; font.family: "monospace"; font.pixelSize: 13 }
        MouseArea { id: backMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.back() }
      }
      Item { Layout.fillWidth: true }
      Text { textFormat: Text.PlainText; text: root.remote ? "Local only" : Storage.ageText(root.data ? root.data.timestamp : 0, root.now); color: root.mutedInk; font.family: "monospace"; font.pixelSize: 12 }
      Rectangle {
        visible: !root.remote
        implicitWidth: rescanText.implicitWidth + 20; implicitHeight: 32; radius: 5
        color: rescanMouse.containsMouse ? root.track : "transparent"; border.color: root.borderColor
        Text { textFormat: Text.PlainText; id: rescanText; anchors.centerIn: parent; text: "Rescan"; color: root.ink; font.family: "monospace"; font.pixelSize: 13 }
        MouseArea { id: rescanMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.rescan() }
      }
    }
    Text {
      textFormat: Text.PlainText
      Layout.fillWidth: true
      text: root.remote ? "Storage scanning is available on this machine only." : root.data ? "Root filesystem   " + Metrics.formatBytes(root.data.total) + " total   ·   " + Metrics.formatBytes(root.data.used) + " used   ·   " + Metrics.formatBytes(root.data.free) + " free" : "Root filesystem"
      color: root.ink; font.family: "monospace"; font.pixelSize: 14; elide: Text.ElideRight
    }
    ColumnLayout {
      visible: !root.remote && root.scanning
      Layout.fillWidth: true; spacing: 3
      Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: "Scanning " + (root.progress.files || 0) + " files · " + Metrics.formatBytes(root.progress.bytes || 0) + " · " + Math.round((root.progress.files || 0) / Math.max(1, root.progress.elapsed || 0)) + " files/s (10 min limit)"; color: root.mutedInk; font.family: "monospace"; font.pixelSize: 12; elide: Text.ElideRight }
      Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 4; radius: 2; color: root.track
        Rectangle { width: parent.width * Math.min(1, (root.progress.elapsed || 0) / 600); height: parent.height; radius: 2; color: root.ink }
      }
    }
    Text { textFormat: Text.PlainText; visible: !root.remote && root.scanError !== ""; Layout.fillWidth: true; text: root.scanError; color: root.ink; font.family: "monospace"; font.pixelSize: 12; wrapMode: Text.WordWrap }
    Text { textFormat: Text.PlainText; visible: root.data && root.data.partial === true; text: "Partial scan — 10 minute limit reached"; color: root.ink; font.family: "monospace"; font.pixelSize: 12 }
    Item {
      visible: !root.remote && root.data !== null
      Layout.fillWidth: true; Layout.preferredHeight: 24
      Row {
        anchors.fill: parent; spacing: 2
        Repeater {
          model: root.rows.filter(function(r) { return r.value > 0 })
          Rectangle {
            required property var modelData
            required property int index
            width: Math.max(0, (parent.width - Math.max(0, root.rows.filter(function(r) { return r.value > 0 }).length - 1) * 2) * modelData.fraction)
            height: parent.height; radius: 4; color: Metrics.qtColor(modelData.color); clip: true
            Canvas {
              visible: modelData.pattern; anchors.fill: parent
              onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = Storage.patternInk(modelData.color); c.lineWidth = 1; for (var x = -height; x < width; x += 7) { c.beginPath(); c.moveTo(x, height); c.lineTo(x + height, 0); c.stroke(); } }
            }
          }
        }
      }
    }
    Flickable {
      id: list
      visible: !root.remote && root.data !== null
      Layout.fillWidth: true; Layout.fillHeight: true
      contentHeight: rowsColumn.height; clip: true; boundsBehavior: Flickable.StopAtBounds
      Column {
        id: rowsColumn; width: list.width; spacing: 1
        Repeater {
          id: rowRepeater
          model: root.rows
          Rectangle {
            required property var modelData
            required property int index
            objectName: "storage-row"
            width: rowsColumn.width; height: 36; radius: 4; color: rowMouse.containsMouse ? root.track : "transparent"
            Rectangle { anchors.fill: parent; radius: parent.radius; color: root.accent; opacity: root.keyboardSelection && index === root.currentRow ? 0.16 : 0 }
            RowLayout {
              anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 10
              Rectangle {
                Layout.preferredWidth: 12; Layout.preferredHeight: 12; radius: 2; color: Metrics.qtColor(modelData.color); clip: true
                Canvas { visible: modelData.pattern; anchors.fill: parent; onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = Storage.patternInk(modelData.color); c.lineWidth = 1; for (var x = -height; x < width; x += 5) { c.beginPath(); c.moveTo(x, height); c.lineTo(x + height, 0); c.stroke(); } } }
              }
              Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.name; color: root.ink; font.family: "monospace"; font.pixelSize: 13; elide: Text.ElideRight }
              Text { textFormat: Text.PlainText; text: Metrics.formatBytes(modelData.value); color: root.ink; font.family: "monospace"; font.pixelSize: 13; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 100 }
              Text { textFormat: Text.PlainText; text: modelData.percent + "%"; color: root.mutedInk; font.family: "monospace"; font.pixelSize: 13; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 48 }
            }
            MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.currentRow = index; root.selectedCategory = modelData.name; root.openCategory(modelData.name) } }
          }
        }
      }
    }
    Text {
      textFormat: Text.PlainText
      visible: !root.remote
      Layout.fillWidth: true
      text: "System & other includes unclassified used space and reserved blocks (system files are not scanned without admin rights)."
      color: root.mutedInk; font.family: "monospace"; font.pixelSize: 12; wrapMode: Text.WordWrap
    }
  }
}
