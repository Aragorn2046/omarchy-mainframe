import QtQuick

Item {
  id: root
  property var settings: ({})
  property bool windowActive: true
  property int sampleTick: 0
  property int glitchOffset: 0
  property url fontSource: Qt.resolvedUrl("../fonts/Orbitron-VariableFont_wght.ttf")
  readonly property bool cyberOn: settings && settings.style === "cyberpunk"
  function enabled(key) { return cyberOn && (!settings.cyber || settings.cyber[key] !== false) }
  readonly property bool hudFrames: enabled("hudFrames")
  readonly property bool neonGlow: enabled("neonGlow")
  readonly property bool gridBackdrop: enabled("gridBackdrop")
  readonly property bool displayFont: enabled("displayFont")
  readonly property bool segmentedMeters: enabled("segmentedMeters")
  readonly property bool dataAnimations: enabled("dataAnimations")
  readonly property bool titleGlitch: enabled("titleGlitch")
  readonly property bool scanlineSweep: enabled("scanlineSweep")
  readonly property bool pulsingStatusDots: enabled("pulsingStatusDots")
  readonly property bool bootSequence: enabled("bootSequence")
  signal dataStep()
  function requestDataStep() { if (dataClock.item) dataClock.item.request() }
  Loader {
    id: dataClock
    objectName: "cyber-data-clock-loader"
    active: root.windowActive && root.dataAnimations
    sourceComponent: StepClock { onStep: root.dataStep() }
  }
  readonly property string fontFamily: fontLoader.item && fontLoader.item.status === FontLoader.Ready && fontLoader.item.name ? fontLoader.item.name : "monospace"
  Loader {
    id: fontLoader
    objectName: "cyber-font-loader"
    active: root.displayFont
    sourceComponent: FontLoader { source: root.fontSource }
  }
}
