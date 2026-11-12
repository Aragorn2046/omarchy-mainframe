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
    id: ambient; active: style.windowActive && (style.titleGlitch || style.scanlineSweep)
    sourceComponent: Cyber.Ambient { glitchEnabled: style.titleGlitch; sweepEnabled: style.scanlineSweep }
  }
  Loader {
    id: boot; property bool pending: false
    active: pending && style.windowActive && style.bootSequence
    sourceComponent: Cyber.Boot { width: 100; height: 100; onFinished: boot.pending = false }
  }
  function init() { style.windowActive = true; boot.pending = false; figure.sourceText = "20.0%"; meter.fraction = 0.5; chart.samples = [10, 40, 20]; style.fontSource = Qt.resolvedUrl("../fonts/Orbitron-VariableFont_wght.ttf"); style.settings = ({}) }
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
    verify(effects.sweepInterval >= 30000 && effects.sweepStepInterval * effects.sweepSteps <= 2000)
    compare(effects.glitchInterval, 25000); compare(effects.glitchDuration, 180)
    compare(effects.sweepInterval, 35000); compare(effects.sweepStepInterval, 300); compare(effects.sweepSteps, 5)
    var glitch = loader(effects, "cyber-glitch-loader")
    glitch.item.startGlitch(); compare(effects.glitchOffset, 2)
    var start = Date.now()
    // Allow 100 ms for QtTest polling and scheduling beyond each budget.
    tryCompare(effects, "glitchOffset", 0, 350)
    verify(Date.now() - start <= 350)
    var sweep = loader(effects, "cyber-sweep-loader").item
    sweep.startSweep(); compare(sweep.step, 1)
    start = Date.now()
    tryCompare(sweep, "step", 0, 2100)
    verify(Date.now() - start <= 2100)
    glitch.item.startGlitch(); compare(effects.glitchOffset, 2)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:false}}
    compare(effects.glitchOffset, 0); verify(!glitch.active)
    style.settings = {style:"cyberpunk", cyber:{titleGlitch:true}}
    compare(effects.glitchOffset, 0)
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
