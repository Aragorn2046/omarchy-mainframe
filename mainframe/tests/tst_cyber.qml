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
    ink: "white"; mutedInk: "gray"; accent: "cyan"; secondary: "cyan"; cardColor: "black"; borderColor: "gray"; track: "gray"
    rows: [{name:"Machine", status:"connected", index:0, view:{cpu:{percentText:"20%",history:[10,20],cores:[]},mem:{usedText:"1 GB",fraction:0.5,swapText:"0"}}}]
  }
  Mainframe.AgentsView {
    id: agents; x: 250; y: 190; width: 300; height: 180; cyberStyle: style
    ink: "white"; mutedInk: "gray"; accent: "cyan"; warning: "yellow"; critical: "red"; cardColor: "black"; borderColor: "gray"; track: "gray"
    rows: [{name:"Example",category:"other",limits:[{label:"Usage",percent:25,level:"",reset:""}],activity:[],models:[],age:"",status:"",help:""}]
  }
  function init() { style.fontSource = Qt.resolvedUrl("../fonts/Orbitron-VariableFont_wght.ttf"); style.settings = ({}) }
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
}
