import QtQuick
import QtQuick.Layouts

// Rows pack from the top. The parent passes the free height; this shows as
// many rows as fit completely, up to 10, and spends a little of the leftover
// on row spacing. A row that would be cut off is not created. Row height is
// the delegate font, not the heading. If the heading itself does not fit,
// nothing is drawn.
ColumnLayout {
  id: root
  property string heading: ""
  property var rows: []
  property color labelColor: "#9aa0a6"
  property color textColor: "#e8e8e8"
  property int labelPx: 12
  property int rowPx: 12
  property int valueWidth: 64
  property int maxRows: 10
  // Negative: no height budget, show every row up to maxRows at the base gap.
  property real availHeight: -1

  // Heading and rows use different fonts. A hidden Text still reports its
  // line height, which matches the RowLayout delegate (no extra padding).
  readonly property real headH: {
    var h = headingText.implicitHeight
    if (!(h > 0)) h = root.labelPx + 4
    return h
  }

  readonly property real rowH: {
    var h = rowMetrics.implicitHeight
    if (!(h > 0)) h = root.rowPx + 4
    return h
  }

  // A budget smaller than the heading hides the list. A sliced heading is
  // not left on screen.
  readonly property bool headingShown: {
    if (!(root.availHeight >= 0)) return true
    return root.headH <= root.availHeight + 0.5
  }

  function blockHeight(n, space) {
    var count = n
    if (!(count > 0)) count = 0
    // One gap per row: heading-to-first, then between rows.
    if (count === 0) return root.headH
    return root.headH + count * (root.rowH + space)
  }

  readonly property int dataRows: {
    var list = root.rows
    var n = (list && list.length > 0) ? list.length : 0
    if (n > root.maxRows) n = root.maxRows
    return n
  }

  readonly property int shownRows: {
    var n = root.dataRows
    if (!(root.availHeight >= 0)) return n
    if (!root.headingShown) return 0
    var guard = 0
    while (n > 0 && root.blockHeight(n, 2) > root.availHeight + 0.5 && guard < 12) {
      n = n - 1
      guard = guard + 1
    }
    return n
  }

  // Base gap is 2. Spare height may add up to 4, and only while every shown
  // row still fits in availHeight.
  readonly property int rowSpacing: {
    var n = root.shownRows
    if (n < 1 || !(root.availHeight >= 0)) return 2
    var spare = root.availHeight - root.blockHeight(n, 2)
    if (!(spare > 0)) return 2
    var extra = Math.floor(spare / n)
    if (extra > 4) extra = 4
    if (extra < 0) extra = 0
    return 2 + extra
  }

  spacing: root.rowSpacing

  // Not laid out (visible is false). Measures one row at the row font.
  Text {
    id: rowMetrics
    visible: false
    text: "Mg"
    textFormat: Text.PlainText
    font.family: "monospace"
    font.pixelSize: root.rowPx
  }

  Text {
    textFormat: Text.PlainText
    id: headingText
    objectName: "metric-label"
    visible: root.headingShown
    text: root.heading
    color: root.labelColor
    font.family: "monospace"
    font.pixelSize: root.labelPx
    Layout.fillWidth: true
    Layout.preferredWidth: 0
    Layout.minimumWidth: 0
  }

  Repeater {
    model: root.shownRows
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
