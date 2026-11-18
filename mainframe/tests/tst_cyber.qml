import QtQuick
import QtTest
import ".." as Mainframe
import "../cyber" as Cyber

TestCase {
  id: test
  name: "CyberStyle"
  width: 600; height: 400; visible: true; when: windowShown

  Cyber.CyberStyle { id: style; settings: ({}) }
  Mainframe.Card { id: card; width: 200; height: 100; title: "Example"; cyberStyle: style; accent: "cyan" }
  Mainframe.Meter { id: meter; y: 110; width: 200; height: 14; fraction: 0.5; cyberStyle: style }
  Mainframe.Sparkline { id: chart; y: 140; width: 200; height: 50; samples: [10, 40, 20]; cyberStyle: style }
  Loader {
    id: grid
    objectName: "cyber-grid-loader"
    width: 200; height: 100
    active: style.gridBackdrop
    sourceComponent: Cyber.GridBackdrop { accent: "cyan" }
  }
  Mainframe.OverviewView {
    id: overview; x: 250; width: 300; height: 180; cyberStyle: style
    warning: "#e0c36a"; critical: "#e06c75"; ink: "white"; mutedInk: "gray"; accent: "cyan"; secondary: "cyan"; cardColor: "black"; borderColor: "gray"; track: "gray"
    rows: [{name:"Machine", status:"connected", index:0, view:{cpu:{percentText:"20%",history:[10,20],cores:[]},mem:{usedText:"1 GB",fraction:0.5,swapText:"0"}}}]
  }
  Mainframe.AgentsView {
    id: agents; x: 250; y: 190; width: 300; height: 180; cyberStyle: style
    ink: "white"; mutedInk: "gray"; accent: "cyan"; warning: "yellow"; critical: "red"; cardColor: "black"; borderColor: "gray"; track: "gray"
    rows: [{name:"Example",category:"other",limits:[{label:"Usage",percent:25,level:"",reset:""}],activity:[],models:[],age:"",status:"",help:""}]
  }
  Item { id: focusTarget; property int presses: 0; Keys.onPressed: function(event) { presses++; event.accepted = true } }
  Component { id: temporaryFocus; Item { } }
  QtObject { id: manualClock; signal dataStep(); function requestDataStep() {} }
  Component { id: chartMotionComponent; Cyber.ChartMotion { clock: manualClock; samples: [0]; samplesB: [0] } }
  Cyber.DataText { id: figure; cyberStyle: style; sourceText: "20.0%" }
  Loader {
    id: ambient; width: 600; height: 400; active: style.windowActive && (style.titleGlitch || style.scanlineSweep)
    sourceComponent: Cyber.Ambient { glitchEnabled: style.titleGlitch; sweepEnabled: style.scanlineSweep }
  }
  Loader {
    id: boot; property bool pending: false
    active: pending && style.windowActive && style.bootSequence
    sourceComponent: Cyber.Boot { width: 100; height: 100; onFinished: boot.pending = false }
  }
  function init() { ambient.height = 400; style.windowActive = true; boot.pending = false; figure.sourceText = "20.0%"; meter.fraction = 0.5; chart.samples = [10, 40, 20]; style.fontSource = Qt.resolvedUrl("../fonts/Orbitron-VariableFont_wght.ttf"); style.settings = ({}) }
  function objectDestroyed(item) { try { return item.objectName === undefined } catch (e) { return true } }
  function loader(item, name) { var result = findChild(item, name); verify(result !== null); return result }
  function test_classic_has_no_cyber_items() {
    compare(style.cyberOn, false)
    compare(loader(card, "cyber-hud-loader").item, null)
    compare(loader(meter, "cyber-segments-loader").item, null)
    compare(loader(meter, "cyber-meter-glow-loader").item, null)
    compare(loader(chart, "cyber-chart-glow-loader").item, null)
    compare(loader(style, "cyber-font-loader").item, null)
    compare(grid.item, null)
  }
  function test_features_toggle_live() {
    style.settings = {style:"cyberpunk", cyber:{}}
    verify(style.cyberOn && style.dataAnimations && style.titleGlitch && style.scanlineSweep && style.pulsingStatusDots && style.bootSequence)
    verify(loader(card, "cyber-hud-loader").active && loader(card, "cyber-hud-loader").item !== null)
    verify(loader(meter, "cyber-meter-glow-loader").active && loader(chart, "cyber-chart-glow-loader").active)
    verify(loader(meter, "cyber-segments-loader").active && grid.active && loader(style, "cyber-font-loader").active)
    style.settings = {style:"cyberpunk", cyber:{hudFrames:false, neonGlow:false, gridBackdrop:false, displayFont:false, segmentedMeters:false, dataAnimations:false, titleGlitch:false, scanlineSweep:false, pulsingStatusDots:false, bootSequence:false}}
    verify(!loader(card, "cyber-hud-loader").active && !loader(card, "cyber-hud-loader").item)
    verify(!loader(meter, "cyber-meter-glow-loader").active && !loader(chart, "cyber-chart-glow-loader").active)
    verify(!loader(meter, "cyber-segments-loader").active && !grid.active && !loader(style, "cyber-font-loader").active)
    verify(!style.dataAnimations && !style.titleGlitch && !style.scanlineSweep && !style.pulsingStatusDots && !style.bootSequence)
    style.settings = {style:"cyberpunk", cyber:{hudFrames:true, neonGlow:true, gridBackdrop:true, displayFont:true, segmentedMeters:true}}
    verify(loader(card, "cyber-hud-loader").item && loader(meter, "cyber-segments-loader").item && grid.item)
    style.settings = {style:"classic", cyber:{}}
    compare(loader(card, "cyber-hud-loader").item, null)
    compare(loader(chart, "cyber-chart-glow-loader").item, null)
    compare(grid.item, null)
  }
  function test_each_feature_independently() {
    var keys = ["hudFrames", "neonGlow", "gridBackdrop", "displayFont", "segmentedMeters"]
    var targets = [loader(card, "cyber-hud-loader"), loader(chart, "cyber-chart-glow-loader"), grid, loader(style, "cyber-font-loader"), loader(meter, "cyber-segments-loader")]
    for (var i = 0; i < keys.length; ++i) {
      var switches = {hudFrames:false, neonGlow:false, gridBackdrop:false, displayFont:false, segmentedMeters:false}
      switches[keys[i]] = true
      style.settings = {style:"cyberpunk", cyber:switches}
      for (var j = 0; j < targets.length; ++j) compare(targets[j].active, i === j)
      switches[keys[i]] = false
      style.settings = {style:"cyberpunk", cyber:switches}
      verify(!targets[i].active && targets[i].item === null)
    }
  }
  function test_views_receive_live_style() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var overviewCard = findChild(overview, "overview-machine-card")
    verify(overviewCard !== null)
    verify(loader(overviewCard, "cyber-hud-loader").active)
    verify(loader(overviewCard, "cyber-chart-glow-loader").active)
    verify(loader(overviewCard, "cyber-segments-loader").active)
    verify(loader(agents, "cyber-hud-loader").active)
    verify(loader(agents, "cyber-segments-loader").active)
    style.settings = {style:"classic"}
    verify(!loader(overviewCard, "cyber-hud-loader").active)
    verify(!loader(agents, "cyber-segments-loader").active)
  }
  function test_overview_temperature_in_both_styles() {
    overview.rows = [{name:"Machine", status:"connected", view:{cpu:{percentText:"23%",tempText:"95°C",tempLevel:"hot",history:[10,23],cores:[]}}}]
    var temp = findChild(overview, "overview-cpu-temperature")
    var overviewCard = findChild(overview, "overview-machine-card")
    var initialHeight = overviewCard.height
    compare(temp.text, "  95°C")
    compare(temp.color, overview.critical)
    for (var i = 0; i < 2; i++) {
      style.settings = {style:i === 0 ? "classic" : "cyberpunk", cyber:{}}
      compare(temp.color, overview.critical)
      compare(overviewCard.height, initialHeight)
    }
  }
  function test_display_font_loads() {
    style.settings = {style:"cyberpunk", cyber:{displayFont:true}}
    tryCompare(loader(style, "cyber-font-loader").item, "status", FontLoader.Ready)
    verify(style.fontFamily.toLowerCase().indexOf("orbitron") >= 0)
  }
  function test_missing_font_falls_back() {
    style.fontSource = Qt.resolvedUrl("missing-font.ttf")
    style.settings = {style:"cyberpunk", cyber:{displayFont:true}}
    tryCompare(loader(style, "cyber-font-loader").item, "status", FontLoader.Error)
    compare(style.fontFamily, "monospace")
  }
  function test_motion_loaders_and_visibility() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var clockLoader = loader(style, "cyber-data-clock-loader")
    verify(clockLoader.active && !clockLoader.item.running)
    var valueLoader = loader(figure, "cyber-data-text-loader")
    var meterLoader = loader(meter, "cyber-meter-motion-loader")
    var chartLoader = loader(chart, "cyber-chart-motion-loader")
    var dotLoader = loader(overview, "cyber-dot-loader")
    verify(valueLoader.active && meterLoader.active && chartLoader.active && dotLoader.active)
    verify(loader(ambient.item, "cyber-glitch-loader").active)
    verify(loader(ambient.item, "cyber-sweep-loader").active)
    boot.pending = true
    verify(boot.active)
    style.windowActive = false
    verify(!clockLoader.active && !clockLoader.item)
    verify(!valueLoader.active && !meterLoader.active && !chartLoader.active && !dotLoader.active && !ambient.active && !boot.active)
    compare(valueLoader.item, null); compare(meterLoader.item, null); compare(chartLoader.item, null)
    style.windowActive = true
    style.settings = {style:"cyberpunk", cyber:{dataAnimations:false, titleGlitch:false, scanlineSweep:false, pulsingStatusDots:false, bootSequence:false}}
    verify(!clockLoader.active && !clockLoader.item)
    verify(!valueLoader.active && !meterLoader.active && !chartLoader.active && !dotLoader.active && !ambient.active && !boot.active)
    compare(valueLoader.item, null); compare(meterLoader.item, null); compare(chartLoader.item, null)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:false, scanlineSweep:true}}
    verify(!loader(ambient.item, "cyber-glitch-loader").active)
    verify(loader(ambient.item, "cyber-sweep-loader").active)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:true, scanlineSweep:false}}
    verify(loader(ambient.item, "cyber-glitch-loader").active)
    verify(!loader(ambient.item, "cyber-sweep-loader").active)
  }
  function test_motion_switches_independently() {
    var keys = ["dataAnimations", "titleGlitch", "scanlineSweep", "pulsingStatusDots", "bootSequence"]
    for (var i = 0; i < keys.length; ++i) {
      boot.pending = false
      style.settings = {style:"cyberpunk", cyber:{}}
      boot.pending = true
      figure.sourceText = i % 2 ? "20.0%" : "80.0%"
      var clockLoader = loader(style, "cyber-data-clock-loader")
      var glitch = loader(ambient.item, "cyber-glitch-loader")
      var sweep = loader(ambient.item, "cyber-sweep-loader")
      glitch.item.startGlitch(); sweep.item.startSweep()
      verify(clockLoader.item.running && loader(glitch.item, "cyber-glitch-reset").running && loader(sweep.item, "cyber-sweep-travel").running)
      var switches = {}; switches[keys[i]] = false
      style.settings = {style:"cyberpunk", cyber:switches}
      compare(clockLoader.active, i !== 0)
      compare(loader(figure, "cyber-data-text-loader").active, i !== 0)
      compare(loader(meter, "cyber-meter-motion-loader").active, i !== 0)
      compare(loader(chart, "cyber-chart-motion-loader").active, i !== 0)
      if (i !== 0) verify(clockLoader.item.running)
      else compare(clockLoader.item, null)
      compare(glitch.active, i !== 1); compare(sweep.active, i !== 2)
      if (i !== 1) verify(loader(glitch.item, "cyber-glitch-timer").running && loader(glitch.item, "cyber-glitch-reset").running)
      else compare(glitch.item, null)
      if (i !== 2) verify(loader(sweep.item, "cyber-sweep-timer").running && loader(sweep.item, "cyber-sweep-travel").running)
      else compare(sweep.item, null)
      var dot = loader(overview, "cyber-dot-loader")
      compare(dot.active, i !== 3)
      if (i !== 3) { style.sampleTick = 0; compare(dot.item.opacity, 1); style.sampleTick = 1; compare(dot.item.opacity, 0.5) }
      else compare(dot.item, null)
      compare(boot.active, i !== 4)
      if (i !== 4) verify(loader(boot.item, "cyber-boot-timer").running)
      else compare(boot.item, null)
    }
    boot.pending = false
  }
  function test_chart_independent_series_do_not_rewind() {
    var plot = createTemporaryObject(chartMotionComponent, test)
    verify(plot !== null)
    plot.samples = [90]
    manualClock.dataStep()
    var before = plot.shown[0]
    plot.samplesB = [60]
    compare(plot.shown[0], before)
    manualClock.dataStep()
    verify(plot.shown[0] >= before)
    compare(plot.shown[0], 90)
    verify(plot.running)
    manualClock.dataStep()
    compare(plot.shownB[0], 60)
    verify(!plot.running)
  }
  function test_data_motion_exact_and_unchanged() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var val = loader(figure, "cyber-data-text-loader").item
    var bar = loader(meter, "cyber-meter-motion-loader").item
    var plot = loader(chart, "cyber-chart-motion-loader").item
    compare(loader(style, "cyber-data-clock-loader").item.interval, 50)
    verify(!val.running && !bar.running && !plot.running)
    figure.sourceText = "87.3%"; meter.fraction = 0.7234; chart.samples = [10, 40, 85]
    tryCompare(plot, "running", true, 100)
    verify(val.running && bar.running && plot.running)
    tryCompare(val, "running", false, 500); tryCompare(bar, "running", false, 500); tryCompare(plot, "running", false, 500)
    compare(figure.text, "87.3%")
    compare(meter.shown, 0.7234)
    compare(plot.shown[2], 85)
    figure.sourceText = "87.3%"; meter.fraction = 0.7234; chart.samples = [10, 40, 85]
    wait(20)
    verify(!val.running && !bar.running && !plot.running)
    chart.samples = [20, 40, 85]
    wait(20)
    verify(!plot.running)
    compare(plot.shown[0], 20)
  }
  function test_data_text_units_and_negative() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var val = loader(figure, "cyber-data-text-loader").item
    figure.sourceText = "999.0 KiB/s"; compare(figure.text, "999.0 KiB/s")
    figure.sourceText = "1.0 MiB/s"; compare(figure.text, "1.0 MiB/s"); verify(!val.running)
    figure.sourceText = "900 KB/s"; figure.sourceText = "1.2 MB/s"; compare(figure.text, "1.2 MB/s"); verify(!val.running)
    figure.sourceText = "CPU  3.0%"; figure.sourceText = "GPU  8.0%"; compare(figure.text, "GPU  8.0%"); verify(!val.running)
    figure.sourceText = "unavailable"; compare(figure.text, "unavailable")
    figure.sourceText = "-8.0 C"; compare(figure.text, "-8.0 C")
    val = loader(figure, "cyber-data-text-loader").item
    figure.sourceText = "-4.25 C"; verify(val.running); verify(figure.text.indexOf("-6.75") === 0)
    // Include 100 ms for QtTest polling beyond the animation budget.
    tryCompare(val, "running", false, 400); compare(figure.text, "-4.25 C")
  }
  function test_chart_missing_endpoint() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var plot = loader(chart, "cyber-chart-motion-loader").item
    chart.samples = [10,40,null]
    compare(plot.shown[2], null); verify(!plot.running)
    chart.samples = [10,40,Infinity]; compare(plot.shown[2], Infinity); verify(!plot.running)
    chart.samples = [10,40,NaN]; verify(isNaN(plot.shown[2])); verify(!plot.running)
    chart.samples = [10,40,20]; compare(plot.shown[2], 20); verify(!plot.running)
  }
  function test_data_timing_and_step_count() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var val = loader(figure, "cyber-data-text-loader").item
    var bar = loader(meter, "cyber-meter-motion-loader").item
    var plot = loader(chart, "cyber-chart-motion-loader").item
    var counts = [0,0,0]
    var a = function() { counts[0]++ }, b = function() { counts[1]++ }, c = function() { counts[2]++ }
    val.valueChanged.connect(a); bar.valueChanged.connect(b); plot.shownChanged.connect(c)
    var start = Date.now()
    figure.sourceText = "75.0%"; meter.fraction = 0.8; chart.samples = [10,40,80]
    // Allow 100 ms for QtTest polling and scheduling beyond the 300 ms budget.
    tryVerify(function() { return !val.running && !bar.running && !plot.running }, 400)
    verify(Date.now() - start <= 400)
    compare(val.step, 3); compare(bar.step, 3); compare(plot.stepA, 3)
    for (var i = 0; i < counts.length; i++) compare(counts[i], 3)
    val.valueChanged.disconnect(a); bar.valueChanged.disconnect(b); plot.shownChanged.disconnect(c)
  }
  function test_ambient_timing_and_disable_mid_glitch() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var effects = ambient.item
    verify(effects.glitchInterval >= 20000 && effects.glitchDuration <= 250)
    verify(effects.sweepInterval >= 30000)
    verify(effects.sweepDuration >= 6000 && effects.sweepDuration <= 10000)
    verify(effects.sweepStepInterval >= 75 && effects.sweepStepInterval <= 100)
    verify(effects.sweepPeak >= 0.03 && effects.sweepPeak <= 0.08)
    compare(effects.glitchInterval, 25000); compare(effects.glitchDuration, 180)
    compare(effects.sweepInterval, 30000)
    var glitch = loader(effects, "cyber-glitch-loader")
    glitch.item.startGlitch(); compare(effects.glitchOffset, 2)
    var start = Date.now()
    // Allow 100 ms for QtTest polling and scheduling beyond each budget.
    tryCompare(effects, "glitchOffset", 0, 350)
    verify(Date.now() - start <= 350)
    glitch.item.startGlitch(); compare(effects.glitchOffset, 2)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:false}}
    compare(effects.glitchOffset, 0); verify(!glitch.active)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:true}}
    compare(effects.glitchOffset, 0)
  }
  function test_sweep_structure_and_size() {
    style.settings = {style:"cyberpunk", cyber:{scanlineSweep:true}}
    var effects = ambient.item
    effects.accent = "#369acb"
    var sweep = loader(effects, "cyber-sweep-loader").item
    var band = loader(sweep, "cyber-sweep-band")
    var travel = loader(sweep, "cyber-sweep-travel")
    verify(!effects.sweeping && !sweep.sweeping && !travel.running && !band.visible)
    verify(sweep.clip)
    compare(effects.sweepDuration, 8000); compare(effects.sweepStepInterval, 80)
    compare(effects.sweepPeak, 0.05); compare(travel.interval, effects.sweepStepInterval)
    ambient.height = 1000; compare(band.height, 140)
    ambient.height = 400; compare(band.height, 80)
    ambient.height = 2000; compare(band.height, 220)
    ambient.height = 1000; compare(band.height, 140)
    compare(band.width, sweep.width)
    compare(band.children.length, 0)
    verify(!band.layer.enabled)
    compare(band.gradient.stops.length, 3)
    compare(band.gradient.stops[0].position, 0)
    compare(band.gradient.stops[1].position, 0.5)
    compare(band.gradient.stops[2].position, 1)
    for (var i = 0; i < band.gradient.stops.length; i++) {
      var color = band.gradient.stops[i].color
      verify(Math.abs(color.r - effects.accent.r) < 0.005)
      verify(Math.abs(color.g - effects.accent.g) < 0.005)
      verify(Math.abs(color.b - effects.accent.b) < 0.005)
      verify(color.a * band.opacity <= 0.08)
    }
    verify(band.gradient.stops[0].color.a < 0.01 && band.gradient.stops[2].color.a < 0.01)
    verify(Math.abs(band.gradient.stops[1].color.a * band.opacity - effects.sweepPeak) < 0.005)
    // The sweep has no pointer handlers or mouse areas among its visual children.
    compare(sweep.children.length, 1)
    compare(sweep.data.length, 4) // One band and three timers, with no pointer handlers.
    compare(sweep.children[0], band)
    compare(band.acceptedButtons, undefined)
  }
  function test_sweep_linear_restart_and_resize() {
    style.settings = {style:"cyberpunk", cyber:{scanlineSweep:true}}
    var effects = ambient.item
    var now = 100000
    effects.sweepNow = function() { return now }
    var sweep = loader(effects, "cyber-sweep-loader").item
    var band = loader(sweep, "cyber-sweep-band")
    var travel = loader(sweep, "cyber-sweep-travel")
    var start = now
    sweep.startSweep()
    verify(effects.sweeping && sweep.sweeping && travel.running && band.visible)
    compare(band.y, -band.height)
    now = start - 100
    travel.triggered()
    compare(band.y, -band.height)
    for (var i = 1; i <= 3; i++) {
      now = start + effects.sweepDuration * i / 4
      travel.triggered()
      var expected = -band.height + i / 4 * (sweep.height + band.height)
      verify(Math.abs(band.y - expected) <= (sweep.height + band.height) * 0.01)
    }
    sweep.startSweep()
    start = now
    compare(band.y, -band.height)
    verify(travel.running && band.visible)
    now = start + effects.sweepDuration / 2
    travel.triggered()
    compare(band.y, -band.height + 0.5 * (sweep.height + band.height))
    ambient.height = 1000
    travel.triggered()
    compare(band.y, -band.height + 0.5 * (sweep.height + band.height))
    var reachedBottom = false
    var onYChanged = function() { if (band.y >= sweep.height) reachedBottom = true }
    band.yChanged.connect(onYChanged)
    now = start + effects.sweepDuration
    travel.triggered()
    band.yChanged.disconnect(onYChanged)
    verify(reachedBottom, "band must reach the new bottom before it resets")
    verify(!travel.running && !sweep.sweeping && !effects.sweeping && !band.visible)
    compare(band.y, -band.height)
  }
  function test_sweep_single_driver() {
    style.settings = {style:"cyberpunk", cyber:{scanlineSweep:true}}
    var effects = ambient.item
    var now = 100000
    effects.sweepNow = function() { return now }
    var sweep = loader(effects, "cyber-sweep-loader").item
    var band = loader(sweep, "cyber-sweep-band")
    var travel = loader(sweep, "cyber-sweep-travel")
    var timers = []
    for (var i = 0; i < sweep.data.length; i++) {
      var child = sweep.data[i]
      if (child.interval !== undefined && child.triggered !== undefined) timers.push(child)
    }
    compare(timers.length, 3)
    sweep.startSweep()
    now += effects.sweepDuration / 2
    var drivers = 0
    for (i = 0; i < timers.length; i++) {
      sweep.startSweep()
      now += effects.sweepDuration / 2
      var before = band.y
      timers[i].triggered()
      if (band.y !== before) {
        drivers++
        compare(timers[i], travel)
      }
    }
    compare(drivers, 1)
    sweep.startSweep()
    verify(travel.running)
    for (i = 0; i < timers.length; i++) {
      if (timers[i] !== travel && timers[i].interval !== effects.sweepInterval) verify(!timers[i].running)
    }
  }
  function test_sweep_real_timer_advances() {
    style.settings = {style:"cyberpunk", cyber:{scanlineSweep:true}}
    var sweep = loader(ambient.item, "cyber-sweep-loader").item
    var band = loader(sweep, "cyber-sweep-band")
    sweep.startSweep()
    var initialY = band.y
    tryVerify(function() { return band.y > initialY }, 2000)
  }
  function test_sweep_real_timer_repeats() {
    var sweepLoader = null
    var sweep = null
    var band = null
    var travel = null
    var observer = null
    try {
      style.settings = {style:"cyberpunk", cyber:{scanlineSweep:true}}
      tryVerify(function() {
        if (!ambient.item) return false
        sweepLoader = findChild(ambient.item, "cyber-sweep-loader")
        if (!sweepLoader || !sweepLoader.active || !sweepLoader.item) return false
        sweep = sweepLoader.item
        band = findChild(sweep, "cyber-sweep-band")
        travel = findChild(sweep, "cyber-sweep-travel")
        return band !== null && travel !== null
      }, 1000)
      observer = Qt.createQmlObject('import QtQuick; Connections { target: null; property var positions: []; property var times: []; property var band; function onTriggered() { positions.push(band.y); times.push(Date.now()) } }', test)
      observer.band = band
      observer.target = travel
      sweep.startSweep()
      tryVerify(function() { return observer.positions.length >= 3 }, 3000)
      verify(observer.positions[1] > observer.positions[0])
      verify(observer.positions[2] > observer.positions[1])
      verify(observer.times[1] - observer.times[0] >= 40)
      verify(observer.times[2] - observer.times[1] >= 40)
      compare(travel.repeat, true)
    } finally {
      try {
        if (observer !== null) observer.destroy()
      } finally {
        try {
          style.settings = ({})
        } finally {
          tryVerify(function() {
            if (!ambient.item) return true
            var currentLoader = findChild(ambient.item, "cyber-sweep-loader")
            if (!currentLoader || !currentLoader.active || !currentLoader.item) return true
            var currentTravel = findChild(currentLoader.item, "cyber-sweep-travel")
            return !currentTravel || !currentTravel.running
          }, 1000)
        }
      }
    }
  }
  function test_sweep_unload() {
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:true, scanlineSweep:true}}
    var effects = ambient.item
    var sweepLoader = loader(effects, "cyber-sweep-loader")
    var sweep = sweepLoader.item
    var band = loader(sweep, "cyber-sweep-band")
    var travel = loader(sweep, "cyber-sweep-travel")
    sweep.startSweep()
    verify(travel.running)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:true, scanlineSweep:false}}
    verify(ambient.active && !sweepLoader.active)
    compare(sweepLoader.item, null)
    wait(0)
    verify(objectDestroyed(sweep) && objectDestroyed(travel) && objectDestroyed(band))
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:true, scanlineSweep:true}}
    sweep = sweepLoader.item
    travel = loader(sweep, "cyber-sweep-travel")
    verify(!travel.running && !sweep.sweeping)
    sweep.startSweep()
    verify(travel.running)
    style.windowActive = false
    verify(!ambient.active)
    compare(ambient.item, null)
    wait(0)
    verify(objectDestroyed(effects) && objectDestroyed(sweep) && objectDestroyed(travel))
    style.windowActive = true
    var newSweep = loader(ambient.item, "cyber-sweep-loader").item
    verify(!newSweep.sweeping && !loader(newSweep, "cyber-sweep-travel").running)
  }
  function test_grid_item_count_large() {
    style.settings = {style:"cyberpunk", cyber:{}}
    grid.width = 8000; grid.height = 4000
    verify(grid.item.children.length <= 2)
    grid.width = 200; grid.height = 100
  }
  function test_boot_finishes_and_skips() {
    style.settings = {style:"cyberpunk", cyber:{}}
    focusTarget.forceActiveFocus(); verify(focusTarget.activeFocus)
    var start = Date.now()
    boot.pending = true; verify(boot.active)
    compare(loader(boot.item, "cyber-boot-timer").interval, 1200)
    // Allow 100 ms for QtTest polling and scheduling beyond the 1500 ms budget.
    tryCompare(boot, "active", false, 1600)
    verify(Date.now() - start <= 1600); verify(focusTarget.activeFocus)
    keyClick(Qt.Key_A); compare(focusTarget.presses, 1)
    boot.pending = true; verify(boot.active)
    mouseClick(boot.item, 10, 10)
    verify(!boot.active && focusTarget.activeFocus)
    boot.pending = true; verify(boot.active)
    keyClick(Qt.Key_A)
    verify(!boot.active && focusTarget.activeFocus)
    keyClick(Qt.Key_A); compare(focusTarget.presses, 2)
  }
  function test_boot_saved_focus_destroyed() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var target = temporaryFocus.createObject(test)
    target.forceActiveFocus(); verify(target.activeFocus)
    boot.pending = true; verify(boot.active)
    compare(boot.item.previousFocus, target)
    target.destroy(); wait(0)
    boot.item.finish()
    verify(!boot.active)
  }
  function test_dot_uses_sample_tick() {
    style.settings = {style:"cyberpunk", cyber:{}}
    var pulse = loader(overview, "cyber-dot-loader").item
    style.sampleTick = 0; compare(pulse.opacity, 1)
    style.sampleTick = 1; compare(pulse.opacity, 0.5)
    style.sampleTick = 2; compare(pulse.opacity, 1)
  }

}
