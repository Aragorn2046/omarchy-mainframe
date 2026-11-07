import QtQuick

Item {
  id: root
  property var clock: null
  property var samples: []
  property var samplesB: []
  property var shown: samples
  property var shownB: samplesB
  property var previousA: []
  property var previousB: []
  property real fromA: 0
  property real fromB: 0
  property bool animateA: false
  property bool animateB: false
  property int step: 0
  property bool ready: false
  property bool running: false
  function same(a, b) { return JSON.stringify(a || []) === JSON.stringify(b || []) }
  function last(list) { return list && list.length ? Number(list[list.length - 1]) : NaN }
  function blend(target, from, progress) {
    var result = Array.prototype.slice.call(target || [])
    var end = last(result)
    progress = 1 - (1 - progress) * (1 - progress)
    if (result.length && isFinite(end) && isFinite(from)) result[result.length - 1] = from + (end - from) * progress
    return result
  }
  function update() {
    if (!ready || (same(samples, previousA) && same(samplesB, previousB))) return
    var changedA = !same(samples, previousA)
    var changedB = !same(samplesB, previousB)
    if (changedA) {
      fromA = last(shown)
      animateA = isFinite(fromA) && isFinite(last(samples)) && last(samples) !== last(previousA)
      previousA = samples
    }
    if (changedB) {
      fromB = last(shownB)
      animateB = isFinite(fromB) && isFinite(last(samplesB)) && last(samplesB) !== last(previousB)
      previousB = samplesB
    }
    if (!animateA && !animateB) { running = false; shown = samples; shownB = samplesB; return }
    step = 1; running = true
    shown = animateA ? blend(samples, fromA, 0.25) : samples
    shownB = animateB ? blend(samplesB, fromB, 0.25) : samplesB
    if (clock) clock.requestDataStep()
  }
  onSamplesChanged: update()
  onSamplesBChanged: update()
  Connections {
    target: root.clock
    function onDataStep() {
      if (!root.running) return
      root.step++
      root.shown = root.step >= 4 || !root.animateA ? root.samples : root.blend(root.samples, root.fromA, root.step / 4)
      root.shownB = root.step >= 4 || !root.animateB ? root.samplesB : root.blend(root.samplesB, root.fromB, root.step / 4)
      if (root.step >= 4) { root.running = false; root.animateA = false; root.animateB = false }
      else root.clock.requestDataStep()
    }
  }
  Component.onCompleted: { shown = samples; shownB = samplesB; previousA = samples; previousB = samplesB; ready = true }
}
