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
  property bool jumping: false
  property Connections clockConnection: Connections {
    target: root.clock
    function onDataStep() {
      if (!root.running) return
      root.step++
      root.value = root.step >= 3 ? root.target : root.startValue + (root.target - root.startValue) * root.step / 3
      if (root.step >= 3) root.running = false
      else root.clock.requestDataStep()
    }
  }
  function jump(next) { jumping = true; target = next; reset(next); jumping = false }
  function reset(next) { running = false; value = next; startValue = next; step = 0 }
  onTargetChanged: {
    if (!ready || jumping) { value = target; return }
    if (target === value) { running = false; return }
    startValue = value; step = 1; running = true
    value = startValue + (target - startValue) / 3
    if (clock) clock.requestDataStep()
  }
  Component.onCompleted: { value = target; ready = true }
}
