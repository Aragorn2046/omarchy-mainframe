import QtQuick
import QtQuick.Layouts

ColumnLayout {
  id: root
  property string heading: ""
  property var rows: []
  property color labelColor: "#9aa0a6"
  property color textColor: "#e8e8e8"
  property int labelPx: 12
  property int rowPx: 12
  property int valueWidth: 64
  spacing: 2

  Text {
    objectName: "metric-label"
    text: root.heading
    color: root.labelColor
    font.family: "monospace"
    font.pixelSize: root.labelPx
    Layout.fillWidth: true
    Layout.preferredWidth: 0
    Layout.minimumWidth: 0
  }

  Repeater {
    model: 8
    delegate: RowLayout {
      Layout.fillWidth: true
      // preferredWidth 0 lets the row shrink below the name's implicit width.
      Layout.preferredWidth: 0
      Layout.minimumWidth: 0
      spacing: 6
      property var row: root.rows && root.rows[index] ? root.rows[index] : null

      Text {
        text: row && row.name ? row.name : ""
        textFormat: Text.PlainText
        color: root.textColor
        font.family: "monospace"
        font.pixelSize: root.rowPx
        elide: Text.ElideRight
        clip: true
        Layout.fillWidth: true
        Layout.preferredWidth: 0
        Layout.minimumWidth: 0
      }

      Text {
        objectName: "metric-label"
        text: row && row.text ? row.text : ""
        textFormat: Text.PlainText
        color: root.labelColor
        font.family: "monospace"
        font.pixelSize: root.rowPx
        horizontalAlignment: Text.AlignRight
        Layout.preferredWidth: root.valueWidth
      }
    }
  }
}
