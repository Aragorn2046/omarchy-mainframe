import QtQuick

QtObject {
  id: root
  property var clock: null
  property real target: 0
  property real value: target
  property real startValue: target
  property int step: 0
  property bool ready: false
  property bool running: false
  property Connections clockConnection: Connections {
    target: root.clock
    function onDataStep() {
      if (!root.running) return
      root.step++
      root.value = root.step >= 4 ? root.target : root.startValue + (root.target - root.startValue) * root.step / 4
      if (root.step >= 4) root.running = false
      else root.clock.requestDataStep()
    }
  }
  onTargetChanged: {
    if (!ready) { value = target; return }
    if (target === value) { running = false; return }
    startValue = value; step = 1; running = true
    value = startValue + (target - startValue) / 4
    if (clock) clock.requestDataStep()
  }
  Component.onCompleted: { value = target; ready = true }
}
