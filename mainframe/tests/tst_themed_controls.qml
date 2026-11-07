import QtQuick
import QtTest
import ".." as Mainframe

TestCase {
  id: test
  name: "ThemedControls"
  width: 500; height: 300
  visible: true
  when: windowShown

  Mainframe.ThemedButton { id: button; x: 10; y: 10; text: "Test"; accent: "#ff0000" }
  Mainframe.ThemedTextField { id: field; x: 10; y: 50; width: 160; placeholderText: "Name"; accent: "#ff0000" }
  Mainframe.ThemedComboBox { id: combo; x: 10; y: 90; model: ["one", "two"]; accent: "#ff0000" }
  Mainframe.ThemedCheckBox { id: check; x: 10; y: 130; text: "Show unavailable providers"; accent: "#ff0000" }

  Component {
    id: overlayComponent
    Mainframe.SettingsOverlay {
      width: 720; height: 600
      ink: "#eeeeee"; mutedInk: "#888888"; accent: "#ff0000"
      cardColor: "#202020"; borderColor: "#555555"
      config: ({hosts:{hosts:[{name:"Day", ssh:"day"}]}, accounts:{accounts:[]}, settings:{overviewView:"systems", showUnavailable:false}})
    }
  }

  function test_overlay_loads() {
    var overlay = overlayComponent.createObject(test)
    verify(overlay !== null)
    wait(0)
    overlay.destroy()
  }

  function test_settings_save_emits_only_the_changed_key() {
    var overlay = overlayComponent.createObject(test, {
      config: {hosts:{hosts:[]}, accounts:{accounts:[]}, settings:{
        overviewView:"systems", showUnavailable:false, theme:"example",
        style:"cyberpunk", cyber:{hudFrames:false}, futureSetting:42
      }}
    })
    var saved = null
    overlay.save.connect(function(kind, value) { if (kind === "settings") saved = value })
    overlay.saveSetting("overviewView", "agents")
    compare(saved.overviewView, "agents")
    compare(Object.keys(saved).length, 1)
    overlay.destroy()
  }

  function test_controls() {
    compare(button.height, 30)
    compare(field.height, 30)
    compare(combo.height, 30)
    compare(button.font.pixelSize, 15)
    compare(field.placeholderTextColor, field.mutedInk)
    mouseClick(check)
    verify(check.checked)
    compare(check.indicator.border.color, check.accent)
    mouseClick(combo)
    tryVerify(function() { return combo.popup.visible })
    compare(combo.popup.background.color, combo.cardColor)
    keyClick(Qt.Key_Down)
    keyClick(Qt.Key_Return)
    compare(combo.currentIndex, 1)
  }
}
