import QtQuick
import QtQuick.Layouts
import "cyber" as Cyber

RowLayout {
  id: root
  property var cpuView: null
  property var cyberStyle: null
  property color foreground
  property color labelColor
  property color hotColor
  property color warmColor
  property int heroSize: 24
  property int valueSize: 14
  property int labelSize: 12

  Cyber.DataText {
    id: cpuPercent
    objectName: "cpu-percent"
    cyberStyle: root.cyberStyle
    textFormat: Text.PlainText
    sourceText: root.cpuView ? root.cpuView.percentText : "—"
    color: root.foreground
    font.family: root.cyberStyle && root.cyberStyle.displayFont ? root.cyberStyle.fontFamily : "monospace"
    font.pixelSize: root.heroSize
    font.weight: Font.Medium
    Layout.minimumWidth: implicitWidth
  }
  Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0 }
  Text {
    id: cpuPeak
    objectName: "cpu-temperature-peak"
    textFormat: Text.PlainText
    text: root.cpuView ? root.cpuView.tempPeakText || "" : ""
    visible: text !== "" && root.width >= cpuPercent.implicitWidth + implicitWidth + cpuTemperature.implicitWidth + cpuFrequency.implicitWidth + root.spacing * 4
    color: root.labelColor
    font.family: "monospace"
    font.pixelSize: root.labelSize
  }
  Text {
    id: cpuTemperature
    objectName: "cpu-temperature"
    textFormat: Text.PlainText
    text: root.cpuView ? root.cpuView.tempText : "—"
    color: root.cpuView && root.cpuView.tempLevel === "hot" ? root.hotColor : (root.cpuView && root.cpuView.tempLevel === "warm" ? root.warmColor : root.foreground)
    font.family: "monospace"
    font.pixelSize: root.valueSize
    Layout.minimumWidth: implicitWidth
  }
  Text {
    id: cpuFrequency
    objectName: "cpu-frequency"
    textFormat: Text.PlainText
    text: root.cpuView ? root.cpuView.freqText : "—"
    color: root.labelColor
    font.family: "monospace"
    font.pixelSize: root.valueSize
    Layout.minimumWidth: implicitWidth
  }
}
