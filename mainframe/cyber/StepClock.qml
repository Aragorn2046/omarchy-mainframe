import QtQuick

Timer {
  interval: 50
  repeat: false
  signal step()
  function request() { if (!running) start() }
  onTriggered: step()
}
