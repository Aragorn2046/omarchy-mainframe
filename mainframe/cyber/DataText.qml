import QtQuick

Text {
  id: root
  textFormat: Text.PlainText
  property var cyberStyle: null
  property string sourceText: ""
  function parse(value) {
    var result = /^([^\d-]*)(-?\d+(?:\.\d+)?)(.*)$/.exec(value)
    return result && isFinite(Number(result[2])) ? result : null
  }
  readonly property var parts: parse(sourceText)
  property var previousParts: null
  onSourceTextChanged: {
    var next = parse(sourceText)
    if (motion.item && next) {
      if (!previousParts || previousParts[1] !== next[1] || previousParts[3] !== next[3])
        motion.item.jump(Number(next[2]))
      else motion.item.target = Number(next[2])
    }
    previousParts = next
  }
  Component.onCompleted: previousParts = parts
  text: {
    if (!motion.item || !parts || !motion.item.running) return sourceText
    var decimals = (parts[2].split('.')[1] || '').length
    return parts[1] + motion.item.value.toFixed(decimals) + parts[3]
  }
  Loader {
    id: motion
    objectName: "cyber-data-text-loader"
    active: root.visible && root.cyberStyle && root.cyberStyle.windowActive && root.cyberStyle.dataAnimations && !!root.parts
    onLoaded: if (root.parts) item.jump(Number(root.parts[2]))
    sourceComponent: StepValue { clock: root.cyberStyle }
  }
}
