import QtQuick

Text {
  id: root
  textFormat: Text.PlainText
  property var cyberStyle: null
  property string sourceText: ""
  readonly property var parts: /^([^\d-]*)(-?\d+(?:\.\d+)?)(.*)$/.exec(sourceText)
  text: {
    if (!motion.item || !parts || !motion.item.running) return sourceText
    var decimals = (parts[2].split('.')[1] || '').length
    return parts[1] + motion.item.value.toFixed(decimals) + parts[3]
  }
  Loader {
    id: motion
    objectName: "cyber-data-text-loader"
    active: root.visible && root.cyberStyle && root.cyberStyle.windowActive && root.cyberStyle.dataAnimations && !!root.parts
    sourceComponent: StepValue { clock: root.cyberStyle; target: root.parts ? Number(root.parts[2]) : 0 }
  }
}
