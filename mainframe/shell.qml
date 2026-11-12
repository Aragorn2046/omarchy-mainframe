//@ pragma AppId mainframe
//@ pragma ShellId mainframe
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "cyber" as Cyber
import Quickshell
import Quickshell.Io
import "lib/metrics.js" as Metrics
import "lib/hosts.js" as Hosts
import "lib/usage_value.js" as UsageValue
import "lib/slotbind.js" as Slotbind
import "lib/agents.js" as Agents
import "lib/live_agents.js" as LiveAgents
import "lib/navigation.js" as Navigation

ShellRoot {
  id: shell

  property string homeDir: String(Quickshell.env("HOME") || "")
  property string themePath: String(Quickshell.env("MAINFRAME_PREVIEW_THEME") || (homeDir + "/.local/state/omarchy/current/theme/colors.toml"))
  property string themeRaw: ""
  property string themeChoice: "follow-omarchy"
  property string activeTheme: "follow-omarchy"
  property string previewDir: ""
  property string selectedPreview: ""
  property string themeNotice: ""
  property bool pickerAvailable: false
  property bool openPickerPending: false
  property string pickedTheme: ""
  property bool themeLoaded: false
  property bool themeMissing: false
  property bool storageOpen: false
  property var storageData: null
  property var storageProgress: ({})
  property string storageError: ""
  property bool storagePending: false
  property bool storageForce: false
  property int storageCleaners: 0
  property bool quitting: false
  property bool stale: false
  property bool restarting: false
  property int samples: 0
  // starts/exits pair a child with its onExited. A late exit from an older
  // child does not match and cannot restart the one that replaced it.
  property int collectorStarts: 0
  property int collectorExits: 0
  property bool collectorUp: false
  property double restartRequestedMs: 0
  // Liveness is the time since the last stdout line from this process.
  property double lastLineMs: 0
  property var restartMarks: []
  property bool collectorStopped: false
  property string sensorError: ""
  property double collectorStartedMs: 0
  readonly property bool smokeMode: String(Quickshell.env("MAINFRAME_SMOKE") || "") === "1"
  property var fleet: Hosts.createFleet("this machine")
  property int selectedIndex: 0
  property string page: "overview"
  property string overviewView: "systems"
  property bool settingsOpen: false
  property bool helpOpen: false
  property var focusBeforeHelp: null
  onHelpOpenChanged: {
    if (helpOpen) {
      var actualWindow = windowProbe.Window.window
      focusBeforeHelp = actualWindow ? actualWindow.activeFocusItem : null
      Qt.callLater(function() { if (shell.helpOpen) helpOverlay.forceActiveFocus() })
    } else {
      if (focusBeforeHelp && focusBeforeHelp.visible && focusBeforeHelp.enabled) focusBeforeHelp.forceActiveFocus()
      else windowContent.forceActiveFocus()
      focusBeforeHelp = null
    }
  }
  property var settingsData: ({hosts:{hosts:[]}, accounts:{accounts:[]}, settings:{overviewView:"systems",showUnavailable:false}})
  property bool settingsLoaded: false
  property var configSnapshots: ({})
  property string configDir: String(Quickshell.env("XDG_CONFIG_HOME") || (homeDir + "/.config")) + "/mainframe/"
  property string configInput: ""
  property string configAction: ""
  property var pendingSettings: null
  property var initialSettingsEdits: null
  property int settingsRevision: 0
  property int readingSettingsRevision: 0
  property bool hostsInitialized: false
  property string hostsSnapshot: ""
  property var remoteSlots: []
  property var agentRows: []
  property string agentStatus: ""
  property bool agentRefreshPending: false
  property bool agentRefreshForce: false
  readonly property bool agentsVisible: page === "overview" && overviewView === "agents"
  onAgentsVisibleChanged: { if (!agentsVisible && agentRefresh.running) agentRefresh.signal(15) }
  readonly property var overviewRows: { var dependency = tabs; return Hosts.overviewRows(fleet, localView, remoteBuckets) }
  function loadAgents() { if (agentsVisible && !agentReader.running) agentReader.running = true }
  function displayTabIndex() { return page === "overview" ? 0 : selectedIndex + 1 }
  function setOverviewView(value) {
    if (["systems", "storage", "agents"].indexOf(value) < 0) return
    overviewView = value
    if (!settingsLoaded) return
    saveConfig("settings", Object.assign({overviewView:value}, settingsData.settings, {overviewView:value}))
    if (agentsVisible) { loadAgents(); refreshAgents(false) }
  }
  function cycleOverview(step) { setOverviewView(Navigation.cycle(overviewView, step)) }
  function textFieldFocused() {
    var actualWindow = windowProbe.Window.window
    var item = actualWindow ? actualWindow.activeFocusItem : null
    return !!item && (item instanceof TextInput || item instanceof TextEdit)
  }
  function scrollActive(kind) {
    var flick = helpOpen ? helpFlick : storageOpen ? storageView.flick : systemsView.visible ? systemsView.flick : agentsView.visible ? agentsView.flick : null
    if (!flick || !flick.visible) return
    flick.contentY = Navigation.scrollTarget(flick.contentY, flick.contentHeight, flick.height, kind)
    if (!helpOpen && storageOpen && flick === storageView.flick) storageView.selectAfterScroll(kind)
  }
  function goBack() {
    if (storageOpen) closeStorage()
    else if (page === "machine") selectTab(0)
  }
  function moveVertical(step) {
    if (!helpOpen && storageOpen && storageView.flick.visible) storageView.moveRow(step)
    else scrollActive(step > 0 ? "line-down" : "line-up")
  }
  function refreshAgents(force) { if (!agentsVisible || quitting) return; if (agentRefresh.running) { agentRefreshPending = true; agentRefreshForce = agentRefreshForce || force; return } var command = ["python3", Quickshell.shellDir + "/config_manager.py", "refresh"]; if (force) command.push("--force"); agentRefresh.command = command; agentRefresh.running = true }
  function configChanged(name, value) {
    var snapshots = configSnapshots
    if (snapshots[name] === value) return
    var initialized = snapshots[name] !== undefined
    snapshots[name] = value
    if (initialized) { configReloadTimer.restart(); if (settingsLoaded && name === "settings") refreshThemes("") }
  }
  function saveConfig(kind, value) {
    if (kind === "settings") {
      if (!settingsLoaded) {
        initialSettingsEdits = Object.assign({}, initialSettingsEdits || {}, value)
        return
      }
      value = Object.assign({}, settingsData.settings || {}, value)
      settingsData = Object.assign({}, settingsData, {settings:value})
      settingsRevision++
    }
    if (configWriter.running) { if (kind === "settings") pendingSettings = value; else settingsOverlay.message = "Please wait for the current operation"; return }
    if (kind === "settings") pendingSettings = null
    configAction = "write"; configInput = JSON.stringify({kind:kind, data:value})
    configWriter.command = ["python3", Quickshell.shellDir + "/config_manager.py", "write"]; configWriter.stdinEnabled = true; configWriter.running = true
  }
  function testConfig(kind, value) {
    if (configWriter.running) return
    configAction = "test"; configInput = kind === "account" ? JSON.stringify(value) : ""
    configWriter.command = ["python3", Quickshell.shellDir + "/config_manager.py", kind === "account" ? "test-account" : "test-host"].concat(kind === "host" ? [value] : [])
    configWriter.stdinEnabled = kind === "account"; settingsOverlay.message = "Testing…"; configWriter.running = true
  }

  property var tabs: []
  property bool hostsHint: true
  property string reachTitle: ""
  property string reachDetail: ""
  property string connectingTo: ""
  property bool connectingSlow: false
  property var localState: Metrics.emptyState()
  property var localView: Metrics.emptyView()
  property var localUsage: null
  property var remoteUsage: ({})
  property var localLiveAgents: null
  property var remoteLiveAgents: ({})
  property double liveAgentsClock: Date.now()
  Timer { interval: 5000; repeat: true; triggeredOnStart: true; running: shell.agentsVisible && !shell.quitting; onTriggered: shell.liveAgentsClock = Date.now() }
  readonly property var fleetLiveAgents: {
    var dependency = liveAgentsClock, hostStatus = tabs
    var data = settingsData || {}
    var entries = LiveAgents.buildEntries(fleet && fleet.hosts, fleet && fleet.sessions, data.hosts && data.hosts.hosts,
                                         data.settings, localLiveAgents, remoteLiveAgents, localSilent)
    var accountList = LiveAgents.normalizeAccounts(data.accounts && data.accounts.accounts, homeDir)
    return LiveAgents.summarize(entries, accountList, Date.now())
  }
  readonly property var fleetUsageValue: {
    var dependency = tabs
    var entries = [{host:"this machine", usage:localUsage}]
    var all = fleet && fleet.hosts ? fleet.hosts : []
    for (var i = 0; i < all.length; i++) {
      var session = fleet.sessions[all[i].ssh]
      var offline = session && (session.phase === "unreachable" || session.phase === "error")
      var report = remoteUsage[all[i].ssh]
      var currentUsage = report ? report.usage : null
      entries.push({host:all[i].name, usage:currentUsage, status:offline ? "offline" : ""})
    }
    return UsageValue.calculate(entries, settingsData.prices || {}, Date.now())
  }
  property var remoteBuckets: ({})
  property string localSensorError: ""
  property bool localSilent: false
  // Per ssh alias. A shared string painted every remote tab with one host's error.
  property var remoteSensorErrors: ({})
  property var remoteLineAt: ({})
  property int smokeWantTab: -1
  property string smokeWantName: ""
  property bool smokeTabApplied: false
  // Tokens keep late callbacks from an old process away from its replacement.
  property int slotToken: 0
  // Stable core-row array. Assigned only when the metrics array identity changes.
  property var coreRows: []

  property color themeBg: "#101315"
  property color themeCard: "#171b22"
  property color themeFg: "#cacccc"
  property color themeLabel: "#707880"
  property color themeAccent: "#7aa2f7"
  property color themeCyan: "#7ec8c3"
  property color themeBorder: "#14cacccc"
  property color themeTrack: "#1acacccc"
  property var themeColors: ({ accent: "#7aa2f7", yellow: "#e0c36a", red: "#e06c75" })

  property var modelState: Metrics.emptyState()
  property var view: Metrics.emptyView()
  // Missing cards stay null so a partial view cannot throw inside a binding.
  readonly property var cpuView: (view && view.cpu != null) ? view.cpu : null
  readonly property var memView: (view && view.mem != null) ? view.mem : null
  readonly property var diskView: (view && view.disk != null) ? view.disk : null
  readonly property var netView: (view && view.net != null) ? view.net : null
  readonly property var gpuView: (view && view.gpu != null) ? view.gpu : null
  readonly property var batView: (view && view.battery != null) ? view.battery : null
  readonly property var procView: (view && view.processes != null) ? view.processes : null
  readonly property bool procStale: procView != null && procView.stale === true
  readonly property color sensorColor: Metrics.qtColor(themeColors && themeColors.red ? themeColors.red : "#e06c75")

  readonly property var shape: Metrics.gridShape(window.width)
  readonly property int columns: shape && shape.columns ? shape.columns : 2
  readonly property int cpuSpan: shape && shape.cpuSpan ? shape.cpuSpan : 2
  readonly property real uiScale: {
    var t = (window.width - 900) / 900
    if (t < 0) t = 0
    if (t > 1) t = 1
    return 1 + 0.22 * t
  }
  readonly property int pxLabel: Math.max(12, Math.round(12 * uiScale))
  readonly property int pxValue: Math.max(13, Math.round(14 * uiScale))
  readonly property int pxFigure: Math.max(18, Math.round(20 * uiScale))
  readonly property int pxHero: Math.max(26, Math.round(28 * uiScale))
  readonly property int smokeHoldMs: {
    var ms = Number(Quickshell.env("MAINFRAME_SMOKE_MS") || 0)
    if (!isFinite(ms) || ms <= 0) return 1200
    return Math.round(ms)
  }

  function startStorage(force) {
    if (selectedIndex !== 0 || quitting) return
    if (storageScanner.running) {
      storagePending = true
      storageForce = force
      stopStorage()
      return
    }
    storageError = ""
    storageProgress = ({})
    storageScanner.command = ["python3", "-u", Quickshell.shellDir + "/collect.py", "--storage"]
    if (force) storageScanner.command = storageScanner.command.concat(["--force"])
    storageScanner.running = true
  }
  function stopStorage() {
    if (!storageScanner.running) return
    var pid = Number(storageScanner.processId)
    try {
      if (pid > 1) {
        var cleaner = storageCleanerComponent.createObject(shell)
        if (!cleaner) throw new Error("Could not create storage group cleaner")
        cleaner.command = Hosts.groupCleanupCommand(pid, false)
        storageCleaners++
        cleaner.running = true
      }
    } finally {
      storageScanner.running = false
    }
  }
  function showStorage() {
    storageOpen = true
    if (selectedIndex === 0) startStorage(false)
  }
  function closeStorage() {
    storageOpen = false
    storageView.keyboardSelection = false
    storagePending = false
    stopStorage()
  }
  function storageLine(line) {
    try {
      var item = JSON.parse(line)
      if (item.type === "result") { storageData = item; storageProgress = ({}); }
      else if (item.type === "progress") storageProgress = item
      else if (item.type === "error") storageError = item.message
    } catch (err) { storageError = "Storage scan returned invalid data." }
  }

  function refreshThemes(selection) {
    if (themeManager.running || quitting) return
    themeManager.command = ["python3", Quickshell.shellDir + "/theme_manager.py"]
    if (selection) themeManager.command = ["python3", Quickshell.shellDir + "/theme_manager.py", selection]
    themeManager.running = true
  }

  function openThemePicker() {
    if (picker.running || themeManager.running) return
    openPickerPending = true
    refreshThemes("")
  }

  function handleThemeInfo(line) {
    try {
      var info = JSON.parse(line)
      if (!info) return
      themeChoice = info.theme
      activeTheme = info.active
      previewDir = info.previewDir
      selectedPreview = info.selected
      pickerAvailable = info.picker
      if (info.missing) themeNotice = "theme missing · following Omarchy"
      if (themePath !== info.colors) {
        themePath = info.colors
        themeRaw = ""
        themeLoaded = false
      }
    } catch (err) { console.log("mainframe theme manager:", err) }
  }

  function applyTheme(resolved) {
    var colors = (resolved && resolved.colors) ? resolved.colors : {}
    // metrics.js keeps #RRGGBBAA. Qt colors are #AARRGGBB, and only here.
    themeBg = Metrics.qtColor(resolved.background)
    themeCard = Metrics.qtColor(resolved.card)
    themeFg = Metrics.qtColor(resolved.foreground)
    themeLabel = Metrics.qtColor(resolved.label)
    themeAccent = Metrics.qtColor(resolved.accent)
    themeCyan = Metrics.qtColor(resolved.cyan)
    themeBorder = Metrics.qtColor(resolved.border)
    themeTrack = Metrics.qtColor(resolved.track)
    themeColors = colors
  }

  function consumeTheme(raw) {
    var text = String(raw || "")
    if (text === "") {
      if (!themeLoaded) {
        applyTheme(Metrics.resolveTheme({}))
        themeMissing = true
        themeLoaded = true
      }
      return
    }
    var parsed = null
    try {
      parsed = Metrics.parseColorsToml(text)
    } catch (err) {
      console.log("mainframe theme:", err)
      if (!themeLoaded) {
        applyTheme(Metrics.resolveTheme({}))
        themeMissing = true
        themeLoaded = true
      }
      return
    }
    if (themeLoaded && text === themeRaw) return
    themeRaw = text
    applyTheme(Metrics.resolveTheme(parsed))
    themeMissing = false
    themeLoaded = true
  }

  function sampleHasErrors(raw) {
    if (!raw || typeof raw !== "object") return false
    if (raw.error) return true
    if (!raw.errors) return false
    var key
    for (key in raw.errors) {
      if (Object.prototype.hasOwnProperty.call(raw.errors, key) && raw.errors[key]) return true
    }
    return false
  }

  function pruneMarks(now) {
    var kept = []
    var marks = restartMarks || []
    var i
    for (i = 0; i < marks.length; i++) {
      if (now - marks[i] < 60000) kept.push(marks[i])
    }
    return kept
  }

  // No line for 5 s, or the process exited: one restart after 1 s.
  // Three restarts in a rolling minute stick the notice until r.
  function armRestart() {
    if (quitting || collectorStopped || restartTimer.running) return
    var now = Date.now()
    var marks = pruneMarks(now)
    restartMarks = marks
    if (marks.length >= 3) {
      collectorStopped = true
      localSilent = true
      restarting = false
      if (collector.running) collector.running = false
      refreshShownAge(Date.now())
      return
    }
    restartTimer.interval = 1000
    restartTimer.start()
  }

  function doRestart() {
    if (quitting || collectorStopped) return
    var now = Date.now()
    // A line, or a process still inside its 5 s grace, cancels the restart.
    if (collector.running && lastLineMs > 0 && (now - lastLineMs) <= 5000) return
    if (collector.running && !(lastLineMs > 0) && collectorStartedMs > 0 && (now - collectorStartedMs) <= 5000) return
    var marks = pruneMarks(now)
    if (marks.length >= 3) {
      restartMarks = marks
      collectorStopped = true
      localSilent = true
      restarting = false
      if (collector.running) collector.running = false
      refreshShownAge(Date.now())
      return
    }
    marks.push(now)
    restartMarks = marks
    if (collector.running) {
      requestCollectorStop()
    } else {
      collector.running = true
    }
  }

  // Stop the child, then SIGKILL if it has not exited within 2 s (SIGSTOP).
  function requestCollectorStop() {
    if (collector.running) collectorUp = true
    restarting = true
    restartRequestedMs = Date.now()
    collector.running = false
    killTimer.restart()
  }

  function refreshConnectingSlow() {
    var host = Hosts.selectedHost(fleet)
    var session = host ? fleet.sessions[host.ssh] : null
    connectingSlow = !!(connectingTo && session && Date.now() - session.since >= 5000)
  }

  Timer {
    interval: 1000
    repeat: true
    running: !!shell.connectingTo
    onTriggered: shell.refreshConnectingSlow()
  }

  function refreshChrome() {
    var machineTabs = Hosts.tabModel(fleet)
    var nextTabs = [{ name: "Overview", status: "" }].concat(machineTabs)
    if (JSON.stringify(tabs) !== JSON.stringify(nextTabs)) tabs = nextTabs
    var reach = page === "machine" ? Hosts.reachMessage(fleet) : null
    reachTitle = reach && reach.title ? Agents.safeHelp(reach.title) : ""
    reachDetail = reach && reach.detail ? Agents.safeHelp(reach.detail) : ""
    connectingTo = page === "machine" ? Agents.safeHelp(Hosts.connectingName(fleet) || "") : ""
    refreshConnectingSlow()
    hostsHint = fleet.hint === true
    selectedIndex = fleet.selected
    refreshShownAge(Date.now())
    if (smokeMode) logTabs()
  }

  function logTabs() {
    var list = tabs || []
    var i
    for (i = 0; i < list.length; i++) {
      var tab = list[i]
      var status = tab && tab.status ? tab.status : "none"
      var wsl = tab && tab.wsl ? 1 : 0
      console.log("TAB index=" + i + " status=" + status + " wsl=" + wsl + " local=" + (tab && tab.remote === false ? 1 : 0) + " name=" + JSON.stringify(tab ? tab.name : ""))
    }
  }

  function publish(state, nextView) {
    modelState = state
    view = nextView
    var nextCores = (nextView && nextView.cpu && nextView.cpu.cores) ? nextView.cpu.cores : []
    if (nextCores.length > 0) {
      if (nextCores !== coreRows) coreRows = nextCores
    } else if (coreRows && coreRows.length) {
      coreRows = []
    }
  }

  function showSelected() {
    if (!fleet || fleet.selected === 0) {
      publish(localState, localView)
    } else {
      var host = Hosts.selectedHost(fleet)
      var bucket = host && remoteBuckets ? remoteBuckets[host.ssh] : null
      if (bucket && bucket.state) publish(bucket.state, bucket.view)
      else publish(Metrics.emptyState(), Metrics.emptyView())
    }
    refreshChrome()
  }

  function rememberRemote(ssh, state, nextView) {
    var buckets = copyMap(remoteBuckets)
    buckets[ssh] = { state: state, view: nextView }
    remoteBuckets = buckets
  }

  function applyHostsText(text, missing) {
    var snapshot = (missing === true ? "missing:" : "present:") + String(text || "")
    if (hostsInitialized && snapshot === hostsSnapshot) return
    hostsSnapshot = snapshot
    var parsed = Hosts.parseHosts(String(text || ""), missing === true)
    Hosts.applyConfig(fleet, parsed, Date.now())
    if (!hostsInitialized) {
      hostsInitialized = true
      if (smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_START_LOCAL") || "") === "1") page = "machine"
      if (page === "overview") Hosts.setOverview(fleet, true, Date.now())
    }
    pruneRemoteState()
    showSelected()
    syncRemotes()
    maybeSmokeTab()
  }

  function logActiveTab() {
    var highlighted = -1
    for (var i = 0; i < tabRepeater.count; i++) {
      var tab = tabRepeater.itemAt(i)
      if (tab && tab.active) highlighted = i
    }
    console.log("ACTIVE tab=" + displayTabIndex() + " selected=" + selectedIndex + " highlighted=" + highlighted)
  }

  function maybeSmokeTab() {
    if (!smokeMode || smokeTabApplied) return
    if (smokeWantName) {
      for (var i = 0; i < tabs.length; i++) {
        if (tabs[i].name === smokeWantName) { smokeTabApplied = true; selectTab(i); Qt.callLater(logActiveTab); return }
      }
      return
    }
    if (smokeWantTab < 0) return
    if (!fleet || !fleet.hosts || smokeWantTab > fleet.hosts.length) return
    smokeTabApplied = true
    selectTab(smokeWantTab + 1)
    Qt.callLater(logActiveTab)
  }

  function selectTab(index) {
    if (quitting || index < 0 || index >= tabs.length) return
    if (storageOpen) closeStorage()
    var offset = 1
    var nextPage = index === 0 ? "overview" : "machine"
    var now = Date.now()
    if (page === "overview" && nextPage !== "overview") Hosts.setOverview(fleet, false, now)
    page = nextPage
    fleet.activeSelected = page === "machine"
    if (page === "overview") Hosts.setOverview(fleet, true, now)
    if (page === "machine") {
      var target = index - offset
      // Revive the selected collector when leaving the overview.
      if (fleet.selected === target && target > 0) {
        var session = fleet.sessions[fleet.hosts[target - 1].ssh]
        if (session && session.phase === "lingering") { session.phase = session.samples ? "connected" : "connecting"; session.lingerUntil = 0 }
      }
      Hosts.selectIndex(fleet, target, now)
    }
    showSelected()
    syncRemotes()
    if (agentsVisible) { loadAgents(); refreshAgents(false) }
  }

  function cycleTab(direction) {
    var next = displayTabIndex() + (direction < 0 ? -1 : 1)
    if (next < 0) next = tabs.length - 1
    if (next >= tabs.length) next = 0
    selectTab(next)
  }

  function copyMap(source) {
    var out = {}
    var src = source || {}
    var key
    for (key in src) {
      if (Object.prototype.hasOwnProperty.call(src, key)) out[key] = src[key]
    }
    return out
  }

  function setRemoteError(ssh, text) {
    var errs = copyMap(remoteSensorErrors)
    if (text) errs[ssh] = text
    else delete errs[ssh]
    remoteSensorErrors = errs
  }

  function setRemoteLine(ssh, when) {
    var lines = copyMap(remoteLineAt)
    lines[ssh] = when
    remoteLineAt = lines
  }

  function pruneRemoteState() {
    var keep = {}
    var hosts = fleet && fleet.hosts ? fleet.hosts : []
    var i
    for (i = 0; i < hosts.length; i++) keep[hosts[i].ssh] = true
    var buckets = {}
    var oldBuckets = remoteBuckets || {}
    var ssh
    for (ssh in oldBuckets) {
      if (Object.prototype.hasOwnProperty.call(oldBuckets, ssh) && keep[ssh]) buckets[ssh] = oldBuckets[ssh]
    }
    remoteBuckets = buckets
    var errs = {}
    var oldErrs = remoteSensorErrors || {}
    for (ssh in oldErrs) {
      if (Object.prototype.hasOwnProperty.call(oldErrs, ssh) && keep[ssh]) errs[ssh] = oldErrs[ssh]
    }
    remoteSensorErrors = errs
    var lines = {}
    var oldLines = remoteLineAt || {}
    for (ssh in oldLines) {
      if (Object.prototype.hasOwnProperty.call(oldLines, ssh) && keep[ssh]) lines[ssh] = oldLines[ssh]
    }
    remoteLineAt = lines
  }

  // Local silence and the selected remote's last line are separate.
  // Unreachable and idle are not stale data.
  function refreshShownAge(now) {
    var t = now || Date.now()
    if (!fleet || !(fleet.selected > 0)) {
      stale = localSilent
      sensorError = localSensorError
      return
    }
    var host = Hosts.selectedHost(fleet)
    if (!host) {
      stale = false
      sensorError = ""
      return
    }
    var session = fleet.sessions ? fleet.sessions[host.ssh] : null
    var phase = session && session.phase ? session.phase : ""
    var live = phase === "connecting" || phase === "connected" || phase === "lingering"
    var at = 0
    if (remoteLineAt && remoteLineAt[host.ssh]) at = Number(remoteLineAt[host.ssh]) || 0
    var old = false
    if (live) {
      if (at > 0) old = (t - at) > 5000
      else if (session && session.since > 0) old = (t - session.since) > 5000
    }
    stale = old
    var err = ""
    if (remoteSensorErrors && remoteSensorErrors[host.ssh]) err = String(remoteSensorErrors[host.ssh])
    sensorError = err
  }

  function slotProc(index) { return remoteSlots[index].proc }
  function slotOut(index) { return remoteSlots[index].out }
  function slotErrParser(index) { return remoteSlots[index].err }
  function currentMark(index) { return remoteSlots[index] ? remoteSlots[index].mark : null }
  function storeMark(mark) { if (mark && remoteSlots[mark.index]) remoteSlots[mark.index].mark = mark }

  function detachSlot(mark) {
    if (!mark) return
    var bag = Slotbind.take(mark.token)
    if (!bag) return
    var proc = slotProc(mark.index)
    var out = slotOut(mark.index)
    var errp = slotErrParser(mark.index)
    try { proc.started.disconnect(bag.onStart) } catch (e0) {}
    try { proc.exited.disconnect(bag.onExit) } catch (e1) {}
    try { out.read.disconnect(bag.onOut) } catch (e2) {}
    try { errp.read.disconnect(bag.onErr) } catch (e3) {}
  }

  // Each start connects its own callbacks. A later start has a new token, so
  // a line or exit from the previous process cannot land on the new one.
  function bindSlot(index, mark) {
    var proc = slotProc(index)
    var out = slotOut(index)
    var errp = slotErrParser(index)
    var token = mark.token
    var onStart = function() {
      var current = shell.currentMark(index)
      if (!current || current.token !== token) return
      shell.onRemoteStarted(current)
    }
    var onExit = function(code, status) {
      var current = shell.currentMark(index)
      if (!current || current.token !== token) return
      shell.finishHost(current, code)
    }
    var onOut = function(line) {
      var current = shell.currentMark(index)
      if (!current || current.token !== token || current.stopping) return
      shell.ingestRemote(current, line)
    }
    var onErr = function(line) {
      var current = shell.currentMark(index)
      if (!current || current.token !== token || current.stopping) return
      shell.onRemoteErr(current, line)
    }
    proc.started.connect(onStart)
    proc.exited.connect(onExit)
    out.read.connect(onOut)
    errp.read.connect(onErr)
    Slotbind.save(token, { onStart: onStart, onExit: onExit, onOut: onOut, onErr: onErr })
  }

  function noteHostLine(ssh, line) {
    if (!ssh || !line) return
    Hosts.noteStderr(fleet, ssh, line)
    var clean = Hosts.sanitizeError(line)
    var host = Hosts.selectedHost(fleet)
    if (host && host.ssh === ssh) refreshChrome()
  }

  function finishHost(mark, code) {
    if (!mark) return
    var current = currentMark(mark.index)
    if (!current || current.token !== mark.token) return
    var stopping = mark.stopping === true || current.stopping === true
    var ssh = mark.ssh
    var gen = mark.gen
    var err = mark.err
    mark.exited = true
    if (!stopping && ssh) {
      Hosts.noteExit(fleet, ssh, gen, code, err, Date.now())
      showSelected()
    }
    stopSlot(mark.index, false)
    maybeReleaseSlot(mark)
  }

  function maybeReleaseSlot(mark) {
    if (!mark || !Slotbind.release(mark.ssh, mark.token, mark.exited, mark.groupGone)) return
    detachSlot(mark)
    remoteSlots[mark.index].mark = null
    syncRemotes()
    finishShutdown()
  }

  function slotMatches(ssh, generation) {
    for (var i = 0; i < remoteSlots.length; i++) { var m = currentMark(i); if (m && m.ssh === ssh && m.gen === generation && !m.stopping) return true }
    return false
  }
  function slotBusy(ssh) { return Slotbind.busy(ssh) }
  function freeSlot() {
    for (var i = 0; i < remoteSlots.length; i++) if (!currentMark(i) && !slotProc(i).running) return i
    var slot = remoteSlotComponent.createObject(shell)
    if (!slot) return -1
    remoteSlots.push(slot)
    return remoteSlots.length - 1
  }

  function slotPid(index) {
    var mark = currentMark(index)
    var pid = mark && mark.pid ? Number(mark.pid) : 0
    if (pid > 1) return pid
    var proc = slotProc(index)
    pid = Number(proc.processId)
    if (pid > 1) return pid
    return 0
  }

  function stopSlot(index, hard) {
    var mark = currentMark(index)
    var proc = slotProc(index)
    if (mark) {
      mark.stopping = true
      mark.hard = mark.hard || hard
      Slotbind.stopping(mark.ssh, mark.token)
      storeMark(mark)
    }
    if (mark && !mark.pid) mark.pid = slotPid(index)
    startGroupCleanup(mark)
    if (proc.running) proc.running = false
    if (!slotKillTimer.running) slotKillTimer.start()
  }

  function startGroupCleanup(mark) {
    if (!mark || mark.groupGone || mark.cleanupStarted) return
    if (!(mark.pid > 1)) {
      if (mark.exited) { mark.groupGone = true; maybeReleaseSlot(mark) }
      return
    }
    var cleaner = remoteSlots[mark.index].cleaner
    if (cleaner.running) return
    mark.cleanupStarted = true
    cleaner.command = Hosts.groupCleanupCommand(mark.pid, mark.hard)
    cleaner.running = true
  }

  function cleanupExited(index, code) {
    var mark = currentMark(index)
    if (!mark || !mark.stopping) return
    mark.cleanupStarted = false
    if (code === 0) mark.groupGone = true
    maybeReleaseSlot(mark)
  }

  function escalateSlots() {
    var pending = false
    var i
    for (i = 0; i < remoteSlots.length; i++) {
      var stopping = currentMark(i) && currentMark(i).stopping
      if (!stopping) continue
      pending = true
      var mark = currentMark(i)
      if (mark) startGroupCleanup(mark)
    }
    if (!pending && slotKillTimer.running) slotKillTimer.stop()
  }

  function startSlot(index, job) {
    var proc = slotProc(index)
    if (smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_NO_REMOTE") || "") === "1") {
      Hosts.noteExit(fleet, job.ssh, job.generation, 1, "unreachable fixture", Date.now())
      refreshChrome()
      return
    }
    var cmd = smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_FAKE_REMOTE") || "") === "1"
      ? ["python3", "-u", Quickshell.shellDir + "/tests/fake-remote.py"] : Hosts.sshCommand(job.ssh)
    if (!cmd) {
      Hosts.noteExit(fleet, job.ssh, job.generation, 1, "bad alias", Date.now())
      refreshChrome()
      return
    }
    var copy = []
    var i
    for (i = 0; i < cmd.length; i++) copy.push(String(cmd[i]))
    slotToken = slotToken + 1
    if (!Slotbind.reserve(job.ssh, slotToken)) return
    var mark = {
      token: slotToken,
      gen: job.generation,
      ssh: job.ssh,
      index: index,
      stopping: false,
      err: "",
      pid: 0,
      exited: false,
      groupGone: false,
      cleanupStarted: false,
      hard: false
    }
    storeMark(mark)
    bindSlot(index, mark)
    proc.stdinEnabled = true
    proc.command = copy
    proc.running = true
  }

  function syncRemotes() {
    if (quitting) return
    Hosts.tick(fleet, Date.now())
    var want = Hosts.desired(fleet) || []
    var i
    var j
    for (i = 0; i < remoteSlots.length; i++) {
      var mark = currentMark(i)
      if (!mark || mark.stopping) continue
      var ssh = mark.ssh
      var gen = mark.gen
      var job = null
      for (j = 0; j < want.length; j++) {
        if (want[j].ssh === ssh) job = want[j]
      }
      if (!job || job.generation !== gen) stopSlot(i, false)
    }
    for (j = 0; j < want.length; j++) {
      if (slotMatches(want[j].ssh, want[j].generation)) continue
      if (slotBusy(want[j].ssh)) continue
      var free = freeSlot()
      if (free < 0) break
      startSlot(free, want[j])
    }
  }

  function stopRemotes() {
    for (var i = 0; i < remoteSlots.length; i++) {
      try { if (currentMark(i)) stopSlot(i, false) } catch (err) { console.warn("mainframe remote cleanup:", err) }
    }
  }

  function onRemoteStarted(mark) {
    if (!mark) return
    var proc = slotProc(mark.index)
    var pid = Number(proc.processId)
    if (pid > 1) mark.pid = pid
    storeMark(mark)
    if (mark.stopping) {
      startGroupCleanup(mark)
      return
    }
    var src = ""
    try {
      src = collectorSource.text()
    } catch (err) {
      src = ""
    }
    if (!src) {
      mark.err = "collector source missing"
      Hosts.noteExit(fleet, mark.ssh, mark.gen, 1, mark.err, Date.now())
      stopSlot(mark.index, false)
      refreshChrome()
      if (!slotKillTimer.running) slotKillTimer.start()
      return
    }
    proc.write("_SCRIPT_SOURCE = " + JSON.stringify(src) + "\n" + src)
    // Script EOF. Teardown is the process-group kill, not this.
    proc.stdinEnabled = false
  }

  function onRemoteErr(mark, line) {
    if (!mark || mark.stopping || !line) return
    noteHostLine(mark.ssh, line)
    var clean = Hosts.sanitizeError(line)
    if (!clean) return
    mark.err = clean
    storeMark(mark)
  }

  function ingestRemote(mark, line) {
    if (quitting || !mark || mark.stopping || !line) return
    var current = currentMark(mark.index)
    if (!current || current.token !== mark.token || current.stopping) return
    var ssh = mark.ssh
    var gen = mark.gen
    if (!ssh) return
    var raw = null
    try {
      raw = JSON.parse(line)
    } catch (err) {
      return
    }
    if (!raw || typeof raw !== "object") return
    var now = Date.now()
    if (!Hosts.noteSample(fleet, ssh, gen, raw, now)) return
    if (Object.prototype.hasOwnProperty.call(raw, "agents_live")) { remoteLiveAgents = LiveAgents.remember(remoteLiveAgents, ssh, raw.agents_live, now, gen) }
    if (raw.usage) { var usageMap = copyMap(remoteUsage); usageMap[ssh] = {generation:gen, usage:raw.usage}; remoteUsage = usageMap }
    setRemoteLine(ssh, now)
    var buckets = remoteBuckets || {}
    var bucket = buckets[ssh]
    var state = bucket && bucket.state ? bucket.state : Metrics.emptyState()
    var result = null
    try {
      result = Metrics.step(state, raw, now)
    } catch (err2) {
      setRemoteError(ssh, "sensor error")
      refreshChrome()
      return
    }
    if (sampleHasErrors(raw)) setRemoteError(ssh, "sensor error")
    else setRemoteError(ssh, "")
    if (result.skip) {
      refreshChrome()
      return
    }
    rememberRemote(ssh, result.state, result.view)
    var shown = Hosts.selectedHost(fleet)
    if (page === "machine" && shown && shown.ssh === ssh) publish(result.state, result.view)
    refreshChrome()
  }

  function ingest(line) {
    if (quitting || !line) return
    var raw = null
    try {
      raw = JSON.parse(line)
    } catch (err) {
      // Bad JSON is not liveness.
      console.log("mainframe collect: bad json")
      return
    }
    if (!raw || typeof raw !== "object") return
    if (Object.prototype.hasOwnProperty.call(raw, "agents_live")) localLiveAgents = LiveAgents.remember({}, "local", raw.agents_live, Date.now()).local
    if (raw.usage) localUsage = raw.usage
    if (smokeMode) console.log("SAMPLE t=" + Date.now())
    var now = Date.now()
    if (raw.host) {
      var prevName = fleet.localName
      var prevWsl = fleet.localWsl === true
      fleet.localOs = raw.os === "darwin" ? "macOS" : ""
      Hosts.setLocal(fleet, String(raw.host), Hosts.sampleWsl(raw))
      if (fleet.localName !== prevName || (fleet.localWsl === true) !== prevWsl) refreshChrome()
    }
    var result = null
    try {
      result = Metrics.step(localState, raw, now)
    } catch (err2) {
      // The line arrived. Keep the last view and do not spend a restart.
      console.log("mainframe step:", err2)
      localSensorError = "sensor error"
      var alive = Metrics.collectorLineAlive(now)
      lastLineMs = alive.lastLineMs
      localSilent = alive.stale === true
      refreshShownAge(now)
      if (alive.stopRestartTimer && restartTimer.running) restartTimer.stop()
      return
    }
    // Any parsed local line proves the local collector is alive, even on another tab.
    lastLineMs = now
    localSilent = false
    if (restartTimer.running) restartTimer.stop()
    var erred = sampleHasErrors(raw)
    if (erred) {
      // Liveness only. Do not clear the notice or count the line as fresh data.
      localSensorError = "sensor error"
      console.log("mainframe collect: sensor error")
    } else {
      localSensorError = ""
    }
    if (result.skip) {
      refreshShownAge(now)
      return
    }
    // Every 1 Hz sample publishes the scene when this machine's tab is showing.
    localState = result.state
    localView = result.view
    if (page === "machine" && selectedIndex === 0) publish(result.state, result.view)
    refreshShownAge(now)
    if (!erred) samples = samples + 1
  }

  // r resets the rolling window and starts a collector without spending a mark.
  // A remote tab restarts that host as well.
  function retryCollector() {
    if (quitting) return
    collectorStopped = false
    restartMarks = []
    localSensorError = ""
    localSilent = false
    if (restartTimer.running) restartTimer.stop()
    if (collector.running) {
      requestCollectorStop()
    } else {
      collector.running = true
    }
    var host = Hosts.selectedHost(fleet)
    if (host) {
      setRemoteError(host.ssh, "")
      var lines = copyMap(remoteLineAt)
      delete lines[host.ssh]
      remoteLineAt = lines
      Hosts.restartSelected(fleet, Date.now())
      showSelected()
      syncRemotes()
    } else {
      refreshShownAge(Date.now())
    }
  }

  // quit on stdin, then drop the process. The death signal and EOF end the child.
  function shutdown() {
    if (quitting) return
    quitting = true
    var fallbackReady = false
    try { shutdownFallback.start(); fallbackReady = true }
    catch (err) { console.warn("mainframe shutdown timer:", err) }
    try { if (agentRefresh.running) agentRefresh.signal(15) } catch (err) { console.warn("mainframe agents cleanup:", err) }
    try { closeStorage() } catch (err) { console.warn("mainframe storage cleanup:", err) }
    try { watchdog.stop() } catch (err) { console.warn("mainframe watchdog stop:", err) }
    try { themeTimer.stop() } catch (err) { console.warn("mainframe theme timer stop:", err) }
    try { configReloadTimer.stop() } catch (err) { console.warn("mainframe config reload stop:", err) }
    try { hostsTimer.stop() } catch (err) { console.warn("mainframe hosts timer stop:", err) }
    try { hostTimer.stop() } catch (err) { console.warn("mainframe host timer stop:", err) }
    try { restartTimer.stop() } catch (err) { console.warn("mainframe restart timer stop:", err) }
    try { killTimer.stop() } catch (err) { console.warn("mainframe kill timer stop:", err) }
    try { smokeTimer.stop() } catch (err) { console.warn("mainframe smoke timer stop:", err) }
    try { stopRemotes() } catch (err) { console.warn("mainframe remote cleanup:", err) }
    try {
      if (collector.running) {
        try { collector.write("quit\n") } finally { collector.running = false }
      }
    } catch (err) { console.warn("mainframe collector cleanup:", err) }
    try { finishShutdown() }
    catch (err) { console.warn("mainframe shutdown:", err); Qt.quit() }
    if (!fallbackReady) Qt.quit()
  }

  function finishShutdown() {
    if (quitting && remoteSlots.every(function(slot) { return !slot.mark }) && storageCleaners === 0) Qt.quit()
  }

  function floorPx(value) {
    if (!(value >= 0)) return -1
    return Math.floor(value + 0.0001)
  }

  function coreCellOverflow(cell) {
    var want = ["core-index", "core-pct", "core-freq", "core-meter"]
    var rects = []
    var kids = cell.children || []
    var i
    for (i = 0; i < kids.length; i++) {
      var kid = kids[i]
      if (!kid || !kid.visible) continue
      var nm = kid.objectName || ""
      if (want.indexOf(nm) < 0) continue
      var rect = { x: kid.x, y: kid.y, r: kid.x + kid.width, b: kid.y + kid.height }
      if (rect.x < -1 || rect.y < -1 || rect.r > cell.width + 1 || rect.b > cell.height + 1) {
        console.log("OVERFLOW core-overlap", nm, "outside")
        return 1
      }
      var j
      for (j = 0; j < rects.length; j++) {
        var other = rects[j]
        var ox = Math.min(rect.r, other.r) - Math.max(rect.x, other.x)
        var oy = Math.min(rect.b, other.b) - Math.max(rect.y, other.y)
        if (ox > 1 && oy > 1) {
          console.log("OVERFLOW core-overlap", nm, other.name)
          return 1
        }
      }
      rects.push({ name: nm, x: rect.x, y: rect.y, r: rect.r, b: rect.b })
    }
    return 0
  }

  function walkGauge(item, depth, acc) {
    if (!item || depth > 12) return
    var name = item.objectName || ""
    if (name === "core-cell") acc.overflow = acc.overflow + coreCellOverflow(item)
    if (name === "core-meter") {
      // Hidden meters (compact heat map, or a cell too short to draw) are not gauged.
      if (item.visible) {
        acc.meters = acc.meters + 1
        if (acc.minH < 0 || item.height < acc.minH) acc.minH = item.height
        if (acc.minW < 0 || item.width < acc.minW) acc.minW = item.width
      }
    } else if (name === "metric-label" && item.visible && item.text && String(item.text).length > 0 && item.font) {
      var px = item.font.pixelSize
      if (acc.minLabel < 0 || px < acc.minLabel) acc.minLabel = px
    }
    if (name === "body" && item.implicitHeight > item.height + 2) {
      acc.overflow = acc.overflow + 1
      console.log("OVERFLOW content", "implicit", item.implicitHeight, "height", item.height)
    }
    var kids = item.children
    if (!kids) return
    for (var i = 0; i < kids.length; i++) walkGauge(kids[i], depth + 1, acc)
  }

  function checkLayout() {
    var overflow = 0
    var cards = 0
    var acc = { meters: 0, minH: -1, minW: -1, minLabel: -1, overflow: 0 }
    for (var i = 0; i < grid.children.length; i++) {
      var card = grid.children[i]
      if (!card || !card.objectName || card.objectName.indexOf("card-") !== 0) continue
      cards = cards + 1
      var bottom = card.y + card.height
      var right = card.x + card.width
      if (bottom > grid.height + 1 || right > grid.width + 1 || card.x < -1 || card.y < -1) {
        overflow = overflow + 1
        console.log("OVERFLOW card", card.objectName, "rect", card.x, card.y, card.width, card.height, "grid", grid.width, grid.height)
      }
      walkGauge(card, 0, acc)
    }
    overflow = overflow + acc.overflow
    var cores = shell.coreRows ? shell.coreRows.length : 0
    console.log("LAYOUT view=machine w=" + Math.round(window.width) + " h=" + Math.round(window.height)
      + " cols=" + columns + " rows=" + (shape && shape.rows ? shape.rows : 0)
      + " cpuSpan=" + cpuSpan + " cards=" + cards + " overflow=" + overflow
      + " samples=" + samples + " cores=" + cores)
    console.log("GAUGE meters=" + acc.meters
      + " minMeterH=" + floorPx(acc.minH)
      + " minMeterW=" + floorPx(acc.minW)
      + " minLabel=" + floorPx(acc.minLabel)
      + " compact=" + (coreArea.compact ? 1 : 0))
  }

  Process {
    id: storageScanner
    running: false
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) {
        shell.storageLine(line)
        if (shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_STORAGE_QUIT") || "") === "1" && shell.storageProgress.type === "progress") {
          console.log("STORAGE_QUIT pid=" + storageScanner.processId + " running=" + (storageScanner.running ? 1 : 0))
          shell.shutdown()
        }
        if (shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_STORAGE_CANCEL") || "") === "1" && shell.storageProgress.type === "progress" && !storageCancelTimer.running) storageCancelTimer.start()
      }
    }
    onStarted: if (shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_STORAGE_CANCEL") || "") === "1") console.log("STORAGE_SCAN pid=" + processId)
    onExited: function(code, status) {
      if (shell.storagePending && shell.storageOpen && !shell.quitting) {
        shell.storagePending = false
        shell.startStorage(shell.storageForce)
      } else if (code !== 0 && shell.storageOpen && !shell.storageError) {
        shell.storageError = "Storage scan stopped. Try Rescan."
      }
    }
  }
  Component {
    id: storageCleanerComponent
    Process {
      running: false
      stdinEnabled: false
      onExited: function(code, status) {
        if (code !== 0) console.warn("mainframe storage group cleanup failed:", code)
        shell.storageCleaners--
        destroy()
        shell.finishShutdown()
      }
    }
  }
  Timer {
    id: shutdownFallback
    interval: 2000
    repeat: false
    onTriggered: Qt.quit()
  }
  Timer {
    id: storageCancelTimer
    interval: 100
    repeat: false
    onTriggered: { shell.closeStorage(); console.log("STORAGE_CANCEL closed=1") }
  }
  Process {
    id: storageOpener
    running: false
    onExited: function(code, status) {
      if (code !== 0 && shell.storageOpen) shell.storageError = "Could not open a folder viewer."
    }
  }

  Process {
    id: themeManager
    running: false
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { shell.handleThemeInfo(line) }
    }
    onExited: function(code, status) {
      if (!shell.openPickerPending) return
      shell.openPickerPending = false
      if (!shell.pickerAvailable) {
        shell.themeNotice = "Omarchy theme picker unavailable"
        return
      }
      shell.themeNotice = ""
      shell.pickedTheme = ""
      picker.command = ["omarchy-menu-images", "--print-name", "--show-labels", "--filterable", "--lazy-thumbnails", "--selected", shell.selectedPreview, shell.previewDir]
      picker.running = true
    }
  }

  Process {
    id: picker
    running: false
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { shell.pickedTheme = line.trim() }
    }
    onExited: function(code, status) {
      if (code === 0 && shell.pickedTheme !== "") shell.refreshThemes(shell.pickedTheme)
    }
  }

  FileView {
    id: colorsFile
    path: shell.themePath
    watchChanges: true
    printErrors: false
    blockLoading: true
    onLoaded: shell.consumeTheme(text())
    onFileChanged: reload()
    onLoadFailed: {
      if (shell.themeLoaded) { if (!shell.themeMissing) { shell.themeMissing = true; shell.refreshThemes("") } return }
      shell.consumeTheme("")
    }
  }

  Timer {
    id: themeTimer
    interval: 2000
    repeat: true
    running: true
    onTriggered: colorsFile.reload()
  }

  Process {
    id: collector
    command: ["python3", "-u", Quickshell.shellDir + (shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_FIXTURE_LOCAL") || "") === "1" ? "/tests/fake-local.py" : "/collect.py")]
    running: true
    stdinEnabled: true
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { shell.ingest(line) }
    }
    stderr: SplitParser {
      splitMarker: "\n"
      onRead: function(line) {
        if (!line) return
        console.log("mainframe collect stderr:", line)
      }
    }
    onStarted: {
      // The 5 s grace belongs to this process. A line from the previous one does not count.
      shell.collectorStarts = shell.collectorStarts + 1
      shell.collectorUp = true
      shell.collectorStartedMs = Date.now()
      shell.lastLineMs = 0
      shell.restarting = false
      shell.restartRequestedMs = 0
      if (killTimer.running) killTimer.stop()
    }
    onExited: function(code, status) {
      shell.collectorExits = shell.collectorExits + 1
      // A newer child is already up, or this exit has no matching start.
      if (Metrics.collectorExitIgnored(shell.collectorStarts, shell.collectorExits)) return
      shell.collectorUp = false
      if (shell.quitting) return
      if (shell.collectorStopped) return
      if (killTimer.running) killTimer.stop()
      if (shell.restarting) {
        shell.restarting = false
        shell.restartRequestedMs = 0
        collector.running = true
        return
      }
      console.log("mainframe collector exited", code)
      shell.armRestart()
    }
  }

  Component {
    id: remoteSlotComponent
    QtObject {
      id: slot
      property var mark: null
      property alias out: output
      property alias err: errors
      property alias proc: process
      property alias cleaner: cleanup
      property Process processObject: Process {
        id: process
        running: false
        stdinEnabled: true
        stdout: SplitParser { id: output; splitMarker: "\n" }
        stderr: SplitParser { id: errors; splitMarker: "\n" }
      }
      property Process cleanupObject: Process {
        id: cleanup
        running: false
        onExited: function(code, status) { if (slot.mark) shell.cleanupExited(slot.mark.index, code) }
      }
    }
  }

  Process {
    id: agentReader
    command: ["python3", Quickshell.shellDir + "/agents_usage.py"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var files = JSON.parse(text), rows = [], now = Date.now()
          for (var i = 0; i < files.length; i++) rows.push(Agents.parse(files[i].raw, files[i].file, now))
          shell.agentRows = Agents.sorted(Agents.visible(rows, shell.settingsData.settings.showUnavailable === true))
        } catch (e) { shell.agentStatus = "Can't read agent usage" }
      }
    }
  }
  Process {
    id: agentRefresh
    onExited: function(code, status) { shell.agentStatus = code === 0 || !shell.agentsVisible || shell.quitting ? "" : "Usage update failed"; shell.loadAgents(); if (!shell.agentsVisible) { shell.agentRefreshPending = false; shell.agentRefreshForce = false } if (shell.agentRefreshPending && shell.agentsVisible && !shell.quitting) { var force = shell.agentRefreshForce; shell.agentRefreshPending = false; shell.agentRefreshForce = false; Qt.callLater(function() { shell.refreshAgents(force) }) } }
  }
  Timer { interval: 600000; repeat: true; running: shell.agentsVisible && !shell.quitting; onTriggered: shell.refreshAgents(false) }
  Process {
    id: configReader
    command: ["python3", Quickshell.shellDir + "/config_manager.py", "read"]
    onStarted: shell.readingSettingsRevision = shell.settingsRevision
    stdout: StdioCollector { onStreamFinished: { try {
      var data = JSON.parse(text); if (shell.readingSettingsRevision !== shell.settingsRevision || shell.pendingSettings || configWriter.running) data.settings = shell.settingsData.settings; var changed = shell.settingsData.settings.showUnavailable !== data.settings.showUnavailable; var accountsChanged = JSON.stringify(shell.settingsData.accounts) !== JSON.stringify(data.accounts); shell.settingsData = data; if (changed && shell.agentsVisible) shell.loadAgents(); if (shell.settingsLoaded && accountsChanged && shell.agentsVisible) shell.refreshAgents(false)
      if (data.errors && Object.keys(data.errors).length) settingsOverlay.message = Object.keys(data.errors).map(function(kind) { return data.errors[kind] }).join("\n")
      if (!shell.settingsLoaded) { shell.settingsLoaded = true; if (!shell.smokeMode || !String(Quickshell.env("MAINFRAME_SMOKE_PAGE") || "")) shell.overviewView = ["systems", "storage", "agents"].indexOf(data.settings.overviewView) >= 0 ? data.settings.overviewView : "systems"; if (shell.agentsVisible) { shell.loadAgents(); if (shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_PAGE") || "") === "agents") shell.refreshAgents(false) } }
      if (shell.initialSettingsEdits) { var edits = shell.initialSettingsEdits; shell.initialSettingsEdits = null; Qt.callLater(function() { shell.saveConfig("settings", edits) }) }
    } catch (e) { settingsOverlay.message = "Cannot read settings" } } }
  }
  Process {
    id: configWriter
    onStarted: { if (stdinEnabled) { write(shell.configInput); stdinEnabled = false } }
    stdout: StdioCollector { onStreamFinished: { try { var result = JSON.parse(text); settingsOverlay.message = result.error ? Agents.safeHelp(result.error) : (result.status || (result.ok ? (shell.configAction === "test" ? "OK" : "Saved") : "Error")) } catch(e) { settingsOverlay.message = "Error" } } }
    onExited: function(code, status) {
      if (shell.agentsVisible) shell.loadAgents()
      if (shell.pendingSettings) Qt.callLater(function() { if (shell.pendingSettings && !configWriter.running) shell.saveConfig("settings", shell.pendingSettings) })
      else if (!configReader.running) configReader.running = true
    }
  }
  // FileView watches existing files; periodic reload also discovers newly created files.
  // Only a content change starts the validated configuration reader.
  FileView { id: accountConfig; path: shell.configDir + "accounts.json"; watchChanges: true; printErrors: false
    onLoaded: shell.configChanged("accounts", text()); onLoadFailed: shell.configChanged("accounts", ""); onFileChanged: reload() }
  FileView { id: settingsConfig; path: shell.configDir + "settings.json"; watchChanges: true; printErrors: false
    onLoaded: shell.configChanged("settings", text()); onLoadFailed: shell.configChanged("settings", ""); onFileChanged: reload() }
  Timer { id: configReloadTimer; interval: 100; repeat: false
    onTriggered: { if (!configReader.running && !configWriter.running) configReader.running = true; else restart() } }
  Timer { interval: 2000; repeat: true; running: !shell.quitting
    onTriggered: { accountConfig.reload(); settingsConfig.reload() } }

  FileView {
    id: collectorSource
    path: Quickshell.shellDir + "/collect.py"
    watchChanges: false
    printErrors: false
    blockLoading: true
  }

  FileView {
    id: hostsFile
    path: Hosts.hostsPath(String(Quickshell.env("XDG_CONFIG_HOME") || ""), shell.homeDir)
    watchChanges: true
    printErrors: false
    blockLoading: true
    onLoaded: { shell.configChanged("hosts", text()); shell.applyHostsText(text(), false) }
    onFileChanged: reload()
    onLoadFailed: { shell.configChanged("hosts", ""); shell.applyHostsText("", true) }
  }

  Timer {
    id: hostsTimer
    interval: 2000
    repeat: true
    running: true
    onTriggered: hostsFile.reload()
  }

  Timer {
    id: hostTimer
    interval: 1000
    repeat: true
    running: true
    onTriggered: {
      if (shell.quitting) return
      shell.syncRemotes()
      shell.refreshChrome()
    }
  }

  Timer {
    id: slotKillTimer
    interval: 500
    repeat: true
    onTriggered: shell.escalateSlots()
  }

  Timer {
    id: killTimer
    interval: 2000
    repeat: false
    onTriggered: {
      if (shell.quitting || !shell.restarting) return
      if (!Metrics.collectorKillDue(Date.now(), shell.restartRequestedMs, shell.collectorUp)) return
      // SIGKILL. A SIGSTOPped child ignores the terminate that running=false sent.
      if (collector.running || shell.collectorUp) collector.signal(9)
      shell.restarting = false
      shell.restartRequestedMs = 0
    }
  }

  Timer {
    id: watchdog
    interval: 1000
    repeat: true
    running: true
    onTriggered: {
      if (shell.quitting || shell.collectorStopped || shell.restarting) return
      var now = Date.now()
      var silent = false
      if (shell.lastLineMs > 0) silent = (now - shell.lastLineMs) > 5000
      else if (shell.collectorStartedMs > 0) silent = (now - shell.collectorStartedMs) > 5000
      if (!collector.running || silent) {
        shell.localSilent = true
        shell.refreshShownAge(now)
        shell.armRestart()
      }
    }
  }

  Timer {
    id: restartTimer
    repeat: false
    onTriggered: shell.doRestart()
  }

  Timer {
    id: smokeTimer
    interval: shell.smokeHoldMs
    repeat: false
    onTriggered: {
      if (shell.page === "machine" && !shell.settingsOpen) shell.checkLayout()
      else {
        var pageOverflow = shell.settingsOpen ? (settingsOverlay.width > window.width || settingsOverlay.height > window.height ? 1 : 0) : shell.agentsVisible ? agentsView.checkLayout() : shell.overviewView === "storage" ? fleetStorage.checkLayout() : systemsView.checkLayout()
        var pageRows = shell.agentsVisible ? shell.agentRows.length : shell.overviewRows.length
        console.log("LAYOUT view=" + (shell.settingsOpen ? "settings" : shell.overviewView) + " w=" + Math.round(window.width) + " h=" + Math.round(window.height) + " rows=" + pageRows + " overflow=" + pageOverflow + " samples=" + samples)
        console.log("PAGE name=" + shell.overviewView + " rows=" + pageRows + " overflow=" + pageOverflow + " drives=" + shell.overviewRows.reduce(function(n, row) { return n + (row.view && row.view.filesystems ? row.view.filesystems.length : 0) }, 0) + " unreachable=" + shell.overviewRows.filter(function(row) { return row.status === "unreachable" }).length + " broken=" + shell.agentRows.filter(function(row) { return row.broken }).length + " connected=" + shell.overviewRows.filter(function(row) { return row.status === "connected" }).length)
        if (shell.agentsVisible) {
          function limitText(item) {
            if (item.objectName === 'agents-limit-percent') return item.text
            var children = item.children || []
            for (var i = 0; i < children.length; i++) {
              var found = limitText(children[i])
              if (found !== null) return found
            }
            return null
          }
          console.log('AGENT_LIMIT text=' + limitText(agentsView))
        }
      }
      if (shell.storageOpen) console.log("STORAGE w=" + Math.round(storageView.width) + " h=" + Math.round(storageView.height) + " visible=" + (storageView.visible ? 1 : 0) + " data=" + (shell.storageData ? 1 : 0) + " rows=" + storageView.rows.length + " patterns=" + storageView.rows.filter(function(row) { return row.pattern }).length + " overflow=" + ((storageView.width > window.width || storageView.height > window.height ? 1 : 0) + storageView.checkStorageLayout()))
      var previewOutput = String(Quickshell.env("MAINFRAME_PREVIEW_OUTPUT") || "")
      if (previewOutput) {
        var item = windowContent
        if (!item.grabToImage(function(result) {
          if (!result.saveToFile(previewOutput)) console.log("PREVIEW save failed")
          shell.shutdown()
        }, Qt.size(1600, 1000))) { console.log("PREVIEW grab failed"); shell.shutdown() }
      } else shell.shutdown()
    }
  }

  Component.onCompleted: {
    if (!String(Quickshell.env("MAINFRAME_PREVIEW_OUTPUT") || "")) refreshThemes("")
    configReader.running = true
    var smoke = String(Quickshell.env("MAINFRAME_SMOKE") || "")
    if (smoke !== "1") return
    var w = Number(Quickshell.env("MAINFRAME_SMOKE_W") || 0)
    var h = Number(Quickshell.env("MAINFRAME_SMOKE_H") || 0)
    if (w > 0) window.implicitWidth = w
    if (h > 0) window.implicitHeight = h
    console.log("SMOKE appId=" + Quickshell.appId + " shellId=" + Quickshell.shellId)
    var tabKey = Number(Quickshell.env("MAINFRAME_SMOKE_TAB") || 0)
    if (tabKey >= 1) smokeWantTab = Math.round(tabKey) - 1
    smokeWantName = String(Quickshell.env("MAINFRAME_SMOKE_TAB_NAME") || "")
    var smokePage = String(Quickshell.env("MAINFRAME_SMOKE_PAGE") || "")
    if (["agents", "storage", "systems"].indexOf(smokePage) >= 0) { shell.page = "overview"; shell.overviewView = smokePage }
    if (smokePage === "settings") shell.settingsOpen = true
    if (String(Quickshell.env("MAINFRAME_SMOKE_CONFIG_WRITE") || "") === "1") Qt.callLater(function() { shell.saveConfig("settings", {overviewView:"systems", showUnavailable:true}) })
    refreshChrome()
    maybeSmokeTab()
    if (String(Quickshell.env("MAINFRAME_SMOKE_STORAGE") || "") === "1") diskCard.activated()
    smokeTimer.start()
  }

  FloatingWindow {
    id: window
    title: "Mainframe"
    color: shell.themeBg
    implicitWidth: 1280
    implicitHeight: 800
    minimumSize: Qt.size(700, 560)

    // The attached Qt window exposes the actual scene-graph swap signal.
    // Only the offscreen diagnostic connects it; the normal UI does no work here.
    Item {
      Component.onCompleted: {
        if (String(Quickshell.env("MAINFRAME_FRAME_DIAGNOSTIC") || "") !== "1") return
        Qt.callLater(function() {
          var target = windowProbe.Window.window
          if (!target || !target.frameSwapped) {
            console.log("FRAME_DIAGNOSTIC unavailable")
            return
          }
          console.log("FRAME_DIAGNOSTIC connected")
          target.frameSwapped.connect(function() { console.log("FRAME t=" + Date.now()) })
        })
      }
      id: windowProbe
    }

    onClosed: {
      // Closing the window during an in-progress quit must not shut down twice.
      if (shell.quitting) return
      shell.shutdown()
    }

    // One binding per action. sequences covers the letter and its shift form.
    Shortcut {
      sequences: ["Escape"]
      context: Qt.WindowShortcut
      autoRepeat: false
      onActivated: if (shell.helpOpen) shell.helpOpen = false; else if (shell.settingsOpen) shell.settingsOpen = false; else if (shell.storageOpen) shell.closeStorage(); else shell.shutdown()
    }
    Shortcut { sequences: ["q", "Q"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (shell.storageOpen) shell.closeStorage(); else shell.shutdown() }
    Shortcut { sequences: ["t", "T"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: shell.openThemePicker() }
    Shortcut {
      sequences: ["r", "R"]
      autoRepeat: false
      context: Qt.WindowShortcut
      enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused()
      onActivated: { if (!shell.settingsOpen) { if (shell.agentsVisible) shell.refreshAgents(true); else shell.retryCollector() } }
    }
    Shortcut { sequences: ["Ctrl+,"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.helpOpen; onActivated: shell.settingsOpen = !shell.settingsOpen }
    Shortcut { sequences: [","]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: shell.settingsOpen = true }
    Shortcut { sequences: ["s"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen && shell.page === "overview") shell.setOverviewView("systems") }
    Shortcut { sequences: ["d"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen && shell.page === "overview") shell.setOverviewView("storage") }
    Shortcut { sequences: ["a"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen && shell.page === "overview") shell.setOverviewView("agents") }
    Shortcut { sequences: ["Tab"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen && shell.page === "overview") shell.cycleOverview(1) }
    Shortcut { sequences: ["Shift+Tab", "Backtab"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen && shell.page === "overview") shell.cycleOverview(-1) }
    Shortcut { sequences: ["1"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(0) }
    Shortcut { sequences: ["2"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(1) }
    Shortcut { sequences: ["3"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(2) }
    Shortcut { sequences: ["4"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(3) }
    Shortcut { sequences: ["5"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(4) }
    Shortcut { sequences: ["6"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(5) }
    Shortcut { sequences: ["7"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(6) }
    Shortcut { sequences: ["8"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(7) }
    Shortcut { sequences: ["9"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.settingsOpen) shell.selectTab(8) }
    Shortcut {
      sequences: ["Ctrl+Tab"]
      autoRepeat: false
      context: Qt.WindowShortcut
      enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused()
      onActivated: if (!shell.storageOpen) shell.cycleTab(1)
    }
    Shortcut { sequences: ["Left", "h"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (shell.storageOpen) shell.goBack(); else shell.cycleTab(-1) }
    Shortcut { sequences: ["Right", "l"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.storageOpen) shell.cycleTab(1) }
    Shortcut { sequences: ["Ctrl+Shift+Tab", "Ctrl+Backtab", "Ctrl+PgUp"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.storageOpen) shell.cycleTab(-1) }
    Shortcut { sequences: ["Ctrl+PgDown"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (!shell.storageOpen) shell.cycleTab(1) }
    Shortcut { sequences: ["Backspace", "Alt+Left"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: shell.goBack() }
    Shortcut { sequences: ["Down", "j"]; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.moveVertical(1) }
    Shortcut { sequences: ["Up", "k"]; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.moveVertical(-1) }
    Shortcut { sequences: ["PgDown", "Space"]; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.scrollActive("page-down") }
    Shortcut { sequences: ["PgUp", "Shift+Space"]; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.scrollActive("page-up") }
    Shortcut { sequences: ["Home", "g"]; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.scrollActive("top") }
    Shortcut { sequences: ["End", "Shift+G"]; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.scrollActive("bottom") }
    Shortcut { sequences: ["Enter", "Return"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: shell.storageOpen && !shell.settingsOpen && !shell.helpOpen && !shell.textFieldFocused(); onActivated: if (shell.storageOpen) storageView.openCurrentRow() }
    Shortcut { sequences: ["?", "F1"]; autoRepeat: false; context: Qt.WindowShortcut; enabled: !shell.settingsOpen && !shell.textFieldFocused(); onActivated: shell.helpOpen = !shell.helpOpen }

    Rectangle {
      id: windowContent
      anchors.fill: parent
      color: String(Quickshell.env("MAINFRAME_PREVIEW_OUTPUT") || "") ? shell.themeBg : "transparent"
    Cyber.CyberStyle {
      id: cyberAppearance
      settings: shell.settingsData.settings
      windowActive: windowProbe.Window.window && windowProbe.Window.window.visible && windowProbe.Window.window.visibility !== Window.Minimized && !shell.quitting
      sampleTick: shell.samples
      glitchOffset: ambient.item ? ambient.item.glitchOffset : 0
    }
    Loader {
      id: ambient
      objectName: "cyber-ambient-loader"
      anchors.fill: parent; z: 190
      active: cyberAppearance.windowActive && (cyberAppearance.titleGlitch || cyberAppearance.scanlineSweep)
      sourceComponent: Cyber.Ambient {
        accent: shell.themeAccent
        smokeAmbientNow: shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_AMBIENT_NOW") || "") === "1"
        glitchEnabled: cyberAppearance.titleGlitch
        sweepEnabled: cyberAppearance.scanlineSweep
      }
    }
    Loader {
      id: boot
      objectName: "cyber-boot-loader"
      property bool pending: !(shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_SKIP_BOOT") || "") === "1")
      property bool started: false
      onActiveChanged: { if (active) started = true; else if (started) pending = false }
      anchors.fill: parent; z: 300
      active: pending && shell.settingsLoaded && cyberAppearance.windowActive && cyberAppearance.bootSequence
      sourceComponent: Cyber.Boot { ink: shell.themeFg; accent: shell.themeAccent; color: shell.themeBg; onFinished: boot.pending = false }
      Connections {
        target: shell
        function onSettingsLoadedChanged() {
          if (shell.settingsLoaded && !cyberAppearance.bootSequence) boot.pending = false
          if (shell.settingsLoaded && String(Quickshell.env("MAINFRAME_SMOKE_STYLE_EXPECTED") || "")) {
            console.log("CYBER static=" + [cyberAppearance.hudFrames, cyberAppearance.neonGlow, cyberAppearance.gridBackdrop, cyberAppearance.displayFont, cyberAppearance.segmentedMeters].every(function(v) { return v })
              + " motion=" + [cyberAppearance.dataAnimations, cyberAppearance.titleGlitch, cyberAppearance.scanlineSweep, cyberAppearance.pulsingStatusDots, cyberAppearance.bootSequence].filter(function(v) { return v }).length)
          }
        }
      }
      Connections {
        target: cyberAppearance
        function onWindowActiveChanged() { if (!cyberAppearance.windowActive && shell.settingsLoaded) boot.pending = false }
      }
    }
    Loader {
      objectName: "cyber-grid-loader"
      anchors.fill: parent
      active: cyberAppearance.gridBackdrop
      sourceComponent: Cyber.GridBackdrop { accent: shell.themeAccent }
    }
    Rectangle {
      id: helpOverlay
      anchors.fill: parent; z: 200; visible: shell.helpOpen
      Keys.onPressed: function(event) { event.accepted = true }
      color: Qt.rgba(0, 0, 0, 0.55)
      MouseArea {
        anchors.fill: parent
        onWheel: (wheel) => wheel.accepted = true
        onClicked: function(mouse) {
          if (mouse.x < helpCard.x || mouse.x >= helpCard.x + helpCard.width || mouse.y < helpCard.y || mouse.y >= helpCard.y + helpCard.height) shell.helpOpen = false
        }
      }
      Card {
        id: helpCard
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 720); height: Math.min(parent.height - 32, 650)
        title: "KEYBOARD HELP"; color: shell.themeCard; borderColor: shell.themeBorder; labelColor: shell.themeLabel
        Flickable {
          id: helpFlick
          anchors.fill: parent; contentWidth: width; contentHeight: helpColumn.implicitHeight; clip: true
          boundsBehavior: Flickable.StopAtBounds
          Column {
            id: helpColumn; width: parent.width; spacing: 5
            Repeater {
              model: Navigation.keyHelp
              delegate: Column {
                required property var modelData
                required property int index
                width: helpColumn.width; spacing: 3
                Text {
                  visible: index === 0 || Navigation.keyHelp[index - 1].group !== modelData.group
                  textFormat: Text.PlainText; text: modelData.group; color: shell.themeAccent; font.family: "monospace"; font.bold: true; font.pixelSize: shell.pxLabel
                }
                Text {
                  width: parent.width; text: modelData.keys.join(" / ") + " — " + modelData.action
                  color: shell.themeFg; font.family: "monospace"; font.pixelSize: shell.pxLabel; wrapMode: Text.Wrap; textFormat: Text.PlainText
                }
              }
            }
          }
        }
      }
    }
    SettingsOverlay {
      id: settingsOverlay; anchors.fill: parent; visible: shell.settingsOpen
      config: shell.settingsData; ink: shell.themeFg; mutedInk: shell.themeLabel; accent: shell.themeAccent; cardColor: shell.themeCard; borderColor: shell.themeBorder
      onClose: shell.settingsOpen = false
      onSave: function(kind, value) { shell.saveConfig(kind, value); if (kind === "settings" && value.overviewView) shell.overviewView = value.overviewView }
      onTestHost: function(alias) { shell.testConfig("host", alias) }
      onTestAccount: function(account) { shell.testConfig("account", account) }
    }
    ColumnLayout {
      anchors.fill: parent
      anchors.margins: 14
      spacing: 8

      RowLayout {
        Layout.fillWidth: true
        spacing: 6

        Repeater {
          id: tabRepeater
          model: shell.tabs
          delegate: Rectangle {
            required property int index
            required property var modelData
            readonly property bool active: index === shell.displayTabIndex()
            radius: 8
            color: active ? shell.themeCard : "transparent"
            border.width: 1
            border.color: active ? shell.themeAccent : shell.themeBorder
            implicitHeight: Math.max(28, shell.pxLabel + 14)
            implicitWidth: Math.min(tabInner.implicitWidth + 16, Math.max(65, (window.width - 225) / Math.max(1, shell.tabs.length)))

            RowLayout {
              id: tabInner
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: 8
              anchors.rightMargin: 8
              spacing: 6

              Rectangle {
                visible: modelData.status !== ""
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 7
                Layout.preferredHeight: 7
                radius: 3.5
                opacity: dotPulse.item ? dotPulse.item.opacity : 1
                Loader { id: dotPulse; objectName: "cyber-dot-loader"; active: cyberAppearance.windowActive && cyberAppearance.pulsingStatusDots && parent.visible; sourceComponent: Cyber.Pulse { sampleTick: cyberAppearance.sampleTick } }
                color: {
                  if (modelData.status === "connected") return shell.themeAccent
                  if (modelData.status.indexOf("connecting") === 0) return Metrics.qtColor(shell.themeColors && shell.themeColors.yellow ? shell.themeColors.yellow : "#e0c36a")
                  return shell.sensorColor
                }
              }
              Text {
                text: Agents.safeHelp(modelData.name || "")
                Layout.fillWidth: true
                elide: Text.ElideRight
                textFormat: Text.PlainText
                color: shell.themeFg
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
              }
              Text {
                visible: modelData.wsl === true
                text: "WSL"
                textFormat: Text.PlainText
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: Math.max(10, shell.pxLabel - 2)
                Layout.alignment: Qt.AlignVCenter
              }
            }

            MouseArea {
              anchors.fill: parent
              onClicked: shell.selectTab(index)
            }
          }
        }

        Text {
          visible: shell.hostsHint && window.width >= 1100
          text: "add machines: see README"
          textFormat: Text.PlainText
          color: shell.themeLabel
          font.family: "monospace"
          font.pixelSize: shell.pxLabel
          Layout.alignment: Qt.AlignVCenter
        }
        Item { Layout.fillWidth: true }
        Rectangle {
          implicitHeight: Math.max(28, shell.pxLabel + 14)
          implicitWidth: themeButton.implicitWidth + 16
          radius: 8
          color: "transparent"
          border.width: 1
          border.color: shell.themeBorder
          Text {
            textFormat: Text.PlainText
            id: themeButton
            anchors.centerIn: parent
            text: "◐  " + shell.activeTheme + "  [t]"
            color: shell.themeLabel
            font.family: "monospace"
            font.pixelSize: shell.pxLabel
          }
          MouseArea { anchors.fill: parent; onClicked: shell.openThemePicker() }
        }
      }

      Text {
        textFormat: Text.PlainText
        visible: shell.themeNotice !== ""
        text: shell.themeNotice
        color: shell.themeLabel
        font.family: "monospace"
        font.pixelSize: shell.pxLabel
        Layout.fillWidth: true
      }

      Text {
        visible: shell.connectingTo !== ""
        text: "connecting to " + shell.connectingTo + (shell.connectingSlow ? " (slow link)" : "")
        textFormat: Text.PlainText
        color: shell.themeLabel
        font.family: "monospace"
        font.pixelSize: shell.pxLabel
        Layout.fillWidth: true
      }

      RowLayout {
        Layout.fillWidth: true
        visible: shell.themeMissing || shell.stale
        spacing: 14

        Text {
          textFormat: Text.PlainText
          visible: shell.themeMissing
          text: "theme not found"
          color: shell.themeLabel
          font.family: "monospace"
          font.pixelSize: shell.pxLabel
        }
        Text {
          visible: shell.stale
          text: "stale"
          textFormat: Text.PlainText
          color: shell.sensorColor
          font.family: "monospace"
          font.pixelSize: shell.pxLabel
        }
        Item { Layout.fillWidth: true }
      }

      Text {
        visible: shell.collectorStopped
        text: "collector stopped — press r to retry"
        textFormat: Text.PlainText
        color: shell.sensorColor
        font.family: "monospace"
        font.pixelSize: shell.pxLabel
        Layout.fillWidth: true
      }

      Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: shell.reachTitle !== ""

        Column {
          anchors.centerIn: parent
          spacing: 8
          width: Math.min(parent.width, 520)

          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: shell.reachTitle
            textFormat: Text.PlainText
            color: shell.themeFg
            font.family: "monospace"
            font.pixelSize: shell.pxFigure
            wrapMode: Text.WordWrap
          }
          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: shell.reachDetail
            textFormat: Text.PlainText
            color: shell.themeLabel
            font.family: "monospace"
            font.pixelSize: shell.pxLabel
            wrapMode: Text.WordWrap
          }
        }
      }

      StorageView {
        id: storageView
        objectName: "storage-view"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: shell.storageOpen
        data: shell.storageData
        palette: shell.smokeMode && String(Quickshell.env("MAINFRAME_SMOKE_STORAGE_MONO") || "") === "1" ? ({ accent: "#777777", muted: "#777777" }) : shell.themeColors
        ink: shell.themeFg
        mutedInk: shell.themeLabel
        accent: shell.themeAccent
        track: shell.themeTrack
        color: shell.themeCard
        labelColor: shell.themeLabel
        borderColor: shell.themeBorder
        remote: shell.selectedIndex !== 0
        scanning: storageScanner.running && shell.storageProgress.type === "progress"
        progress: shell.storageProgress
        scanError: shell.storageError
        onBack: shell.closeStorage()
        onRescan: shell.startStorage(true)
        onOpenCategory: function(category) {
          if (storageOpener.running) return
          storageOpener.command = ["python3", Quickshell.shellDir + "/collect.py", "--storage-open", category]
          storageOpener.running = true
        }
      }

      RowLayout {
        visible: shell.page === "overview"; Layout.fillWidth: true
        Text { transform: Translate { x: cyberAppearance.glitchOffset } textFormat: Text.PlainText; text: "OVERVIEW"; color: shell.themeLabel; font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"; font.pixelSize: shell.pxLabel; Layout.fillWidth: true }
        Repeater { model: ["systems", "storage", "agents"]; delegate: Text {
          textFormat: Text.PlainText
          required property var modelData; text: (modelData === "systems" ? "" : " · ") + modelData.charAt(0).toUpperCase() + modelData.slice(1)
          color: shell.overviewView === modelData ? shell.themeFg : shell.themeLabel; font.family: "monospace"; font.pixelSize: shell.pxLabel
          MouseArea { anchors.fill: parent; onClicked: shell.setOverviewView(modelData) }
        } }
      }
      OverviewView {
        cyberStyle: cyberAppearance
        id: systemsView
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: shell.page === "overview" && shell.overviewView === "systems"
        rows: shell.overviewRows
        warning: Metrics.qtColor(shell.themeColors.yellow || "#e0c36a"); critical: shell.sensorColor
        ink: shell.themeFg; mutedInk: shell.themeLabel; accent: shell.themeAccent; secondary: shell.themeCyan
        cardColor: shell.themeCard; borderColor: shell.themeBorder; track: shell.themeTrack
        onOpenMachine: function(index) { shell.selectTab(index + 1) }
      }
      FleetStorage {
        cyberStyle: cyberAppearance
        id: fleetStorage
        Layout.fillWidth: true; Layout.fillHeight: true
        visible: shell.page === "overview" && shell.overviewView === "storage"
        rows: shell.overviewRows; ink: shell.themeFg; mutedInk: shell.themeLabel; accent: shell.themeAccent
        warning: Metrics.qtColor(shell.themeColors.yellow || "#e0c36a"); critical: shell.sensorColor
        cardColor: shell.themeCard; borderColor: shell.themeBorder; track: shell.themeTrack
      }
      AgentsView {
        cyberStyle: cyberAppearance
        id: agentsView
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: shell.agentsVisible
        rows: shell.agentRows
        valueData: shell.fleetUsageValue
        fleetLiveAgents: shell.fleetLiveAgents
        ink: shell.themeFg; mutedInk: shell.themeLabel; accent: shell.themeAccent
        warning: Metrics.qtColor(shell.themeColors.yellow || "#e0c36a")
        critical: shell.sensorColor
        cardColor: shell.themeCard; borderColor: shell.themeBorder; track: shell.themeTrack
        busy: agentRefresh.running
        status: shell.agentStatus
        onRefresh: shell.refreshAgents(true)
      }

      GridLayout {
        id: grid
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: shell.page === "machine" && shell.reachTitle === "" && !shell.storageOpen
        opacity: shell.stale ? 0.45 : 1
        columnSpacing: 14
        rowSpacing: 14
        columns: shell.columns

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          objectName: "card-cpu"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.columnSpan: shell.cpuSpan
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "CPU"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            CpuHeader {
              Layout.fillWidth: true
              cpuView: shell.cpuView
              cyberStyle: cyberAppearance
              foreground: shell.themeFg
              labelColor: shell.themeLabel
              hotColor: shell.sensorColor
              warmColor: Metrics.qtColor(shell.themeColors.yellow || "#e0c36a")
              heroSize: shell.pxHero
              valueSize: shell.pxValue
              labelSize: shell.pxLabel
            }

            Text { textFormat: Text.PlainText; visible: shell.cpuView && !!shell.cpuView.windowsText; text: shell.cpuView ? (shell.cpuView.windowsText || "") : ""; color: shell.themeLabel; font.family: "monospace"; font.pixelSize: shell.pxLabel }
            Sparkline {
              objectName: "cpu-sparkline"
              cyberStyle: cyberAppearance
              ink: shell.themeFg
              mutedInk: shell.themeLabel
              tooltipBg: shell.themeCard
              Layout.fillWidth: true
              Layout.fillHeight: false
              Layout.preferredHeight: steady ? 16 : 36
              Layout.minimumHeight: steady ? 16 : 28
              Layout.maximumHeight: 40
              samples: shell.cpuView ? shell.cpuView.history : []
              samplesB: shell.cpuView ? shell.cpuView.tempHistory || [] : []
              labelA: "CPU"
              labelB: "temp"
              unitB: "°C"
              strokeColor: shell.themeAccent
              strokeColorB: shell.themeCyan
              yMin: 0
              yMax: 100
            }

            Item {
              id: coreArea
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.minimumHeight: 36

              readonly property int n: shell.coreRows ? shell.coreRows.length : 0
              // Width 0 on the first pass: estimate from the window, and never divide by 0.
              readonly property var layout: {
                var w = width
                var h = height
                if (!(w >= 40)) {
                  var gridW = window.width - 28
                  if (gridW < 0) gridW = 0
                  var gaps = (shell.columns - 1) * 14
                  var col = shell.columns > 0 ? (gridW - gaps) / shell.columns : gridW
                  w = col * shell.cpuSpan + (shell.cpuSpan - 1) * 14 - 24
                  if (!(w > 0)) w = 0
                }
                if (!(h > 0)) h = 0
                return Metrics.coreLayout(n, w, h)
              }
              readonly property int cols: (layout && layout.columns >= 1) ? layout.columns : 1
              readonly property int rows: (layout && layout.rows >= 1) ? layout.rows : 1
              readonly property int colGap: (layout && layout.colGap != null) ? layout.colGap : 6
              readonly property int rowGap: (layout && layout.rowGap != null) ? layout.rowGap : 4
              readonly property bool compact: layout ? layout.compact === true : false
              readonly property real cellW: {
                var v = layout ? Number(layout.cellW) : 0
                if (!(v > 0)) return 0
                return v
              }
              readonly property real cellH: {
                var v = layout ? Number(layout.cellH) : 0
                if (!(v > 0)) return 0
                return v
              }

              Repeater {
                model: coreArea.n
                delegate: Item {
                  id: coreCell
                  objectName: "core-cell"
                  property var core: {
                    var list = shell.coreRows
                    if (!list || index < 0 || index >= list.length) return null
                    return list[index]
                  }
                  property real pct: {
                    var p = 0
                    if (core && core.percent != null) p = Number(core.percent)
                    if (!isFinite(p) || p < 0) p = 0
                    if (p > 100) p = 100
                    return p / 100
                  }
                  x: coreArea.cols >= 1 ? (index % coreArea.cols) * (coreArea.cellW + coreArea.colGap) : 0
                  y: coreArea.cols >= 1 ? Math.floor(index / coreArea.cols) * (coreArea.cellH + coreArea.rowGap) : 0
                  width: coreArea.cellW > 0 ? coreArea.cellW : 0
                  height: coreArea.cellH > 0 ? coreArea.cellH : 0

                  // Dense machines (>32 logical cores) draw a heat tile instead of a meter.
                  // The loader stays inactive otherwise so those items are not updated.
                  Loader {
                    active: coreArea.compact
                    anchors.fill: parent
                    sourceComponent: Component {
                      Item {
                        Rectangle {
                          anchors.fill: parent
                          radius: 2
                          border.width: coreCell.pct >= 0.9 ? 2 : 0
                          border.color: shell.themeFg
                          color: {
                            var sample = coreCell.core
                            if (!(sample && sample.percent != null) || !isFinite(Number(sample.percent))) return shell.themeTrack
                            return Metrics.qtColor(Metrics.meterColor(coreCell.pct, shell.themeColors))
                          }
                        }
                        Text {
                          // Hide rather than ellipsize: a cut-off percent is a broken number.
                          visible: parent.height >= 12 && parent.width >= 18 && implicitWidth <= Math.max(0, parent.width - 2)
                          anchors.centerIn: parent
                          text: coreCell.core && coreCell.core.percentText ? coreCell.core.percentText : "—"
                          textFormat: Text.PlainText
                          color: shell.themeFg
                          font.family: "monospace"
                          font.pixelSize: parent.height >= 18 ? 9 : 8
                        }
                      }
                    }
                  }

                  // Index stays left (at most ~45% of the cell) and percent stays
                  // right (at most ~50%). Digits shrink down to a floor instead of
                  // gaining an ellipsis; clip covers whatever still sticks out, so
                  // the two never overlap. Frequency (already "3.2G" / "800M") is
                  // drawn only when that whole token fits in the gap between them.
                  // These are not metric-label: the gauge floor is for the card titles.
                  // Hidden when the cell is too short to hold a line of text.
                  readonly property real freqRoom: {
                    if (coreArea.compact || height < 16) return 0
                    return width - coreIndex.width - corePct.width - 6
                  }

                  Text {
                    id: coreIndex
                    objectName: "core-index"
                    visible: !coreArea.compact && parent.height >= 16
                    anchors.left: parent.left
                    anchors.top: parent.top
                    // Natural width, capped. implicitWidth stays the unfitted size,
                    // so this does not chase the shrunk font.
                    width: Math.min(implicitWidth, Math.max(0, parent.width * 0.45))
                    clip: true
                    elide: Text.ElideNone
                    text: index < 10 ? ("0" + index) : ("" + index)
                    textFormat: Text.PlainText
                    color: shell.themeLabel
                    font.family: "monospace"
                    font.pixelSize: shell.pxLabel
                    fontSizeMode: Text.HorizontalFit
                    minimumPixelSize: 8
                  }

                  Text {
                    id: corePct
                    objectName: "core-pct"
                    visible: !coreArea.compact && parent.height >= 16
                    anchors.right: parent.right
                    anchors.top: parent.top
                    width: Math.min(implicitWidth, Math.max(0, parent.width * 0.50))
                    clip: true
                    elide: Text.ElideNone
                    horizontalAlignment: Text.AlignRight
                    text: core && core.percentText ? core.percentText : "—"
                    textFormat: Text.PlainText
                    color: shell.themeFg
                    font.family: "monospace"
                    font.pixelSize: shell.pxLabel
                    fontSizeMode: Text.HorizontalFit
                    minimumPixelSize: 8
                  }

                  Text {
                    id: coreFreq
                    objectName: "core-freq"
                    anchors.top: parent.top
                    visible: !coreArea.compact && parent.height >= 16 && text !== "" && implicitWidth <= parent.freqRoom
                    x: coreIndex.width + 3 + Math.max(0, (parent.freqRoom - implicitWidth) / 2)
                    text: core && core.freqText ? core.freqText : ""
                    textFormat: Text.PlainText
                    color: shell.themeLabel
                    font.family: "monospace"
                    font.pixelSize: shell.pxLabel
                  }

                  Meter {
                    cyberStyle: cyberAppearance
                    objectName: "core-meter"
                    vertical: true
                    // anchors.bottom made a short cell negative. Height is clamped,
                    // and it does not read y, so visible cannot loop.
                    visible: !coreArea.compact && parent.height >= 32
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: coreIndex.bottom
                    anchors.topMargin: 4
                    height: {
                      var room = parent.height - shell.pxLabel - 10
                      if (!(room >= 14)) return 0
                      return room
                    }
                    width: {
                      var cell = parent.width
                      if (!(cell >= 14)) return 0
                      var wanted = cell * 0.36
                      if (wanted < 14) wanted = 14
                      if (wanted > 28) wanted = 28
                      if (wanted > cell) wanted = cell
                      return wanted
                    }
                    fraction: pct
                    warningInk: shell.themeFg
                    fill: Metrics.qtColor(Metrics.meterColor(pct, shell.themeColors))
                    track: shell.themeTrack
                  }
                }
              }
            }
          }
        }

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          objectName: "card-mem"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Memory"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            Cyber.DataText {

              cyberStyle: cyberAppearance
              textFormat: Text.PlainText
              sourceText: shell.memView ? (shell.memView.headerText || shell.memView.usedText) : "—"
              color: shell.themeFg
              font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
              font.pixelSize: shell.pxFigure
              font.weight: Font.Medium
              elide: Text.ElideRight
              Layout.fillWidth: true
            }

            Text { textFormat: Text.PlainText; visible: shell.memView && !!shell.memView.wslText; text: shell.memView ? (shell.memView.windowsUnavailable ? "Windows totals unavailable" : (shell.memView.wslText || "")) : ""; color: shell.themeLabel; font.family: "monospace"; font.pixelSize: shell.pxLabel; Layout.fillWidth: true; elide: Text.ElideRight }
            Meter {
              cyberStyle: cyberAppearance
              Layout.fillWidth: true
              Layout.preferredHeight: 12
              fraction: shell.memView ? shell.memView.fraction : 0
              fill: Metrics.qtColor(Metrics.meterColor(shell.memView ? shell.memView.fraction : 0, shell.themeColors))
              warningInk: shell.themeFg
              track: shell.themeTrack
              Rectangle {
                id: wslSegment
                visible: shell.memView && !shell.memView.windowsUnavailable && shell.memView.wslFraction > 0
                anchors.right: parent.right
                anchors.rightMargin: parent.width * (1 - parent.fraction)
                width: parent.width * (shell.memView ? (shell.memView.wslFraction || 0) : 0)
                height: parent.height
                color: shell.themeCyan
              }
              Rectangle {
                x: parent.width * parent.shown
                width: parent.width * Math.min(1 - parent.shown, shell.memView ? (shell.memView.cacheFraction || 0) : 0)
                height: parent.height
                color: parent.fill
                opacity: 0.3
              }
            }

            Sparkline {
              cyberStyle: cyberAppearance
              ink: shell.themeFg
              mutedInk: shell.themeLabel
              tooltipBg: shell.themeCard
              Layout.fillWidth: true
              Layout.fillHeight: !steady
              Layout.preferredHeight: steady ? 16 : 28
              Layout.minimumHeight: steady ? 16 : 28
              samples: shell.memView ? shell.memView.history : []
              strokeColor: shell.themeAccent
              yMin: 0
              yMax: 100
            }

            ColumnLayout {
              Layout.fillWidth: true
              spacing: 2
              Text {
                textFormat: Text.PlainText
                objectName: "metric-label"
                text: (shell.memView && shell.memView.wslText ? "WSL avail  " : "available  ") + (shell.memView ? shell.memView.availableText : "—")
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
              Text {
                textFormat: Text.PlainText
                objectName: "metric-label"
                text: (shell.memView && shell.memView.wslText ? "WSL cached " : "cached     ") + (shell.memView ? shell.memView.cachedText : "—")
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
              Text {
                textFormat: Text.PlainText
                objectName: "metric-label"
                text: "swap       " + (shell.memView ? shell.memView.swapText : "—")
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
            }
          }
        }

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          objectName: "card-gpu"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: (shell.gpuView && shell.gpuView.driver) ? ("GPU  " + shell.gpuView.driver) : "GPU"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            Cyber.DataText {

              cyberStyle: cyberAppearance
              textFormat: Text.PlainText
              readonly property bool gpuLive: shell.gpuView != null && shell.gpuView.unsupported !== true && shell.gpuView.na !== true
              sourceText: shell.gpuView == null ? "not available" : shell.gpuView.percentText
              color: gpuLive ? shell.themeFg : shell.themeLabel
              font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
              font.pixelSize: gpuLive ? shell.pxHero : shell.pxLabel
              font.weight: Font.Medium
            }

            Text {
              textFormat: Text.PlainText
              objectName: "metric-label"
              visible: shell.gpuView != null && shell.gpuView.na !== true
              text: shell.gpuView != null ? shell.gpuView.freqText : ""
              color: shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
            }

            Sparkline {
              cyberStyle: cyberAppearance
              ink: shell.themeFg
              mutedInk: shell.themeLabel
              tooltipBg: shell.themeCard
              visible: shell.gpuView != null && shell.gpuView.unsupported !== true && shell.gpuView.na !== true
              Layout.fillWidth: true
              Layout.fillHeight: !steady
              Layout.preferredHeight: steady ? 16 : 28
              Layout.minimumHeight: steady ? 16 : (shell.gpuView != null && shell.gpuView.unsupported !== true && shell.gpuView.na !== true) ? 28 : 0
              samples: shell.gpuView != null ? shell.gpuView.history : []
              strokeColor: shell.themeAccent
              yMin: 0
              yMax: 100
            }
          }
        }

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          id: diskCard
          objectName: "card-disk"
          clickable: true
          onActivated: shell.showStorage()
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Disk"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            RowLayout {
              Layout.fillWidth: true
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                RowLayout {
                  Layout.fillWidth: true
                  Layout.minimumWidth: 0
                  spacing: 5
                  Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 1; color: shell.themeAccent }
                  Cyber.DataText {
                    cyberStyle: cyberAppearance
                    textFormat: Text.PlainText
                    sourceText: shell.diskView ? shell.diskView.readText : "unavailable"
                    color: shell.themeFg
                    font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
                    font.pixelSize: shell.pxFigure
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    Layout.minimumWidth: 0
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  objectName: "metric-label"
                  text: shell.diskView && shell.diskView.readLabel ? shell.diskView.readLabel : "read"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                RowLayout {
                  Layout.fillWidth: true
                  Layout.minimumWidth: 0
                  spacing: 5
                  Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 1; color: shell.themeCyan }
                  Cyber.DataText {
                    cyberStyle: cyberAppearance
                    textFormat: Text.PlainText
                    sourceText: shell.diskView ? shell.diskView.writeText : "unavailable"
                    color: shell.themeFg
                    font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
                    font.pixelSize: shell.pxFigure
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    Layout.minimumWidth: 0
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  objectName: "metric-label"
                  text: "write"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
            }

            Text {
              textFormat: Text.PlainText
              text: shell.diskView ? shell.diskView.usageText : "—"
              color: shell.themeFg
              font.family: "monospace"
              font.pixelSize: shell.pxValue
              elide: Text.ElideRight
              Layout.fillWidth: true
              Layout.preferredWidth: 0
              Layout.minimumWidth: 0
            }

            Meter {
              cyberStyle: cyberAppearance
              Layout.fillWidth: true
              Layout.preferredHeight: 12
              fraction: shell.diskView ? shell.diskView.fraction : 0
              fill: Metrics.qtColor(Metrics.meterColor(shell.diskView ? shell.diskView.fraction : 0, shell.themeColors))
              warningInk: shell.themeFg
              track: shell.themeTrack
            }

            Sparkline {
              cyberStyle: cyberAppearance
              ink: shell.themeFg
              mutedInk: shell.themeLabel
              tooltipBg: shell.themeCard
              Layout.fillWidth: true
              Layout.fillHeight: !steady
              Layout.preferredHeight: steady ? 16 : 28
              Layout.minimumHeight: steady ? 16 : 28
              samples: shell.diskView ? shell.diskView.readHistory : []
              samplesB: shell.diskView ? shell.diskView.writeHistory : []
              rateChart: true
              labelA: "read"
              labelB: "write"
              strokeColor: shell.themeAccent
              strokeColorB: shell.themeCyan
              yMin: 0
              yMax: -1
            }

            RowLayout {
              Layout.fillWidth: true
              Text {
                textFormat: Text.PlainText
                visible: shell.diskView && shell.diskView.tempText && shell.diskView.tempText !== "—"
                text: shell.diskView ? shell.diskView.tempText : ""
                color: shell.themeFg
                font.family: "monospace"
                font.pixelSize: shell.pxValue
              }
              Item { Layout.fillWidth: true }
              Text {
                objectName: "metric-label"
                text: shell.diskView && shell.diskView.device ? shell.diskView.device : "—"
                textFormat: Text.PlainText
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignRight
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                Layout.minimumWidth: 0
              }
            }
          }
        }

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          objectName: "card-net"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Network"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            id: netBody
            objectName: "body"
            anchors.fill: parent
            spacing: 6
            readonly property var detail: Metrics.netDetailLines(
              shell.netView ? shell.netView.perIface : [],
              shell.netView && shell.netView.iface ? shell.netView.iface : ""
            )

            Text {
              objectName: "metric-label"
              text: shell.netView && shell.netView.iface ? shell.netView.iface : "—"
              textFormat: Text.PlainText
              color: shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
              elide: Text.ElideRight
              Layout.fillWidth: true
              Layout.preferredWidth: 0
              Layout.minimumWidth: 0
            }

            RowLayout {
              Layout.fillWidth: true
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                RowLayout {
                  Layout.fillWidth: true
                  Layout.minimumWidth: 0
                  spacing: 5
                  Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 1; color: shell.themeAccent }
                  Cyber.DataText {
                    cyberStyle: cyberAppearance
                    textFormat: Text.PlainText
                    sourceText: shell.netView ? shell.netView.downText : "—"
                    color: shell.themeFg
                    font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
                    font.pixelSize: shell.pxFigure
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    Layout.minimumWidth: 0
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  objectName: "metric-label"
                  text: "down"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                RowLayout {
                  Layout.fillWidth: true
                  Layout.minimumWidth: 0
                  spacing: 5
                  Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 1; color: shell.themeCyan }
                  Cyber.DataText {
                    cyberStyle: cyberAppearance
                    textFormat: Text.PlainText
                    sourceText: shell.netView ? shell.netView.upText : "—"
                    color: shell.themeFg
                    font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
                    font.pixelSize: shell.pxFigure
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    Layout.minimumWidth: 0
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  objectName: "metric-label"
                  text: "up"
                  color: shell.themeLabel
                  font.family: "monospace"
                  font.pixelSize: shell.pxLabel
                }
              }
            }

            Repeater {
              model: netBody.detail ? netBody.detail.length : 0
              delegate: Text {
                property var ifaceRow: {
                  var rows = netBody.detail
                  if (!rows || index < 0 || index >= rows.length) return null
                  return rows[index]
                }
                objectName: "metric-label"
                visible: text !== ""
                textFormat: Text.PlainText
                text: {
                  if (!ifaceRow) return ""
                  if (ifaceRow.more) return ifaceRow.text ? ifaceRow.text : ""
                  return ifaceRow.name + "  " + ifaceRow.downText + "  " + ifaceRow.upText
                }
                color: shell.themeLabel
                font.family: "monospace"
                font.pixelSize: shell.pxLabel
                elide: Text.ElideRight
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                Layout.minimumWidth: 0
              }
            }

            Sparkline {
              cyberStyle: cyberAppearance
              ink: shell.themeFg
              mutedInk: shell.themeLabel
              tooltipBg: shell.themeCard
              Layout.fillWidth: true
              Layout.fillHeight: !steady
              Layout.preferredHeight: steady ? 16 : 28
              Layout.minimumHeight: steady ? 16 : 28
              samples: shell.netView ? shell.netView.rxHistory : []
              samplesB: shell.netView ? shell.netView.txHistory : []
              rateChart: true
              labelA: "down"
              labelB: "up"
              strokeColor: shell.themeAccent
              strokeColorB: shell.themeCyan
              yMin: 0
              yMax: -1
            }
          }
        }

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          objectName: "card-bat"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Battery"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          ColumnLayout {
            objectName: "body"
            anchors.fill: parent
            spacing: 6

            Cyber.DataText {

              cyberStyle: cyberAppearance
              textFormat: Text.PlainText
              sourceText: shell.batView != null ? shell.batView.percentText : "no battery"
              color: shell.batView != null ? shell.themeFg : shell.themeLabel
              font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
              font.pixelSize: shell.batView != null ? shell.pxHero : shell.pxLabel
              font.weight: Font.Medium
            }

            Text {
              objectName: "metric-label"
              visible: shell.batView != null
              text: shell.batView != null ? shell.batView.statusText : ""
              textFormat: Text.PlainText
              color: shell.themeLabel
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
            }

            Text {
              textFormat: Text.PlainText
              visible: shell.batView != null
              text: shell.batView != null ? shell.batView.powerText : ""
              color: shell.themeFg
              font.family: cyberAppearance.displayFont ? cyberAppearance.fontFamily : "monospace"
              font.pixelSize: shell.pxFigure
            }

            Meter {
              cyberStyle: cyberAppearance
              visible: shell.batView != null
              Layout.fillWidth: true
              Layout.preferredHeight: shell.batView != null ? 12 : 0
              fraction: shell.batView != null ? shell.batView.fraction : 0
              critical: shell.batView != null && shell.batView.fraction < 0.15
              fill: Metrics.qtColor(Metrics.batteryMeterColor(shell.batView != null ? shell.batView.fraction : 0, shell.themeColors))
              warningInk: shell.themeFg
              track: shell.themeTrack
            }

            Sparkline {
              cyberStyle: cyberAppearance
              ink: shell.themeFg
              mutedInk: shell.themeLabel
              tooltipBg: shell.themeCard
              visible: shell.batView != null
              Layout.fillWidth: true
              Layout.fillHeight: !steady
              Layout.preferredHeight: steady ? 16 : 28
              Layout.minimumHeight: shell.batView != null ? (steady ? 16 : 28) : 0
              samples: shell.batView != null ? shell.batView.history : []
              strokeColor: shell.themeAccent
              // A flat 100% history would otherwise fill this plot solid.
              fillOpacity: 0.08
              strokeOnlyWhenFlat: true
              yMin: 0
              yMax: 100
            }
          }
        }

        Card {
          cyberStyle: cyberAppearance; accent: shell.themeAccent
          objectName: "card-proc"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredWidth: 220
          Layout.preferredHeight: 180
          Layout.minimumWidth: 120
          Layout.minimumHeight: 48
          title: "Processes"
          titleSize: shell.pxLabel
          color: shell.themeCard
          labelColor: shell.themeLabel
          borderColor: shell.themeBorder
          hint: shell.sensorError
          hintColor: shell.sensorColor

          // Top-down. A GridLayout centers a short column in the card, which
          // left the lists sitting in the lower half. Both lists start under
          // the title; spare height only loosens row spacing a little.
          Item {
            id: procBody
            objectName: "body"
            anchors.fill: parent
            readonly property bool sideBySide: width >= 260
            readonly property real listTop: procStale.visible ? procStale.implicitHeight + 4 : 0
            readonly property real listRoom: Math.max(0, height - listTop)

            Text {
              id: procStale
              visible: shell.procStale
              x: 0
              y: 0
              width: parent.width
              text: "stale"
              textFormat: Text.PlainText
              color: shell.sensorColor
              font.family: "monospace"
              font.pixelSize: shell.pxLabel
            }

            ProcList {
              id: cpuList
              opacity: shell.procStale ? 0.45 : 1
              x: 0
              y: procBody.listTop
              width: procBody.sideBySide ? Math.max(0, Math.floor((procBody.width - 12) / 2)) : procBody.width
              // A layout inside a plain Item does not adopt its implicit height.
              height: implicitHeight
              availHeight: procBody.sideBySide ? procBody.listRoom : Math.max(0, (procBody.listRoom - 4) / 2)
              heading: "cpu"
              rows: shell.procView && shell.procView.byCpu ? shell.procView.byCpu : []
              labelColor: shell.themeLabel
              textColor: shell.themeFg
              labelPx: shell.pxLabel
              rowPx: shell.pxLabel
              valueWidth: Math.round(shell.pxLabel * 5.5)
            }
            ProcList {
              id: memList
              opacity: shell.procStale ? 0.45 : 1
              x: procBody.sideBySide ? cpuList.width + 12 : 0
              y: procBody.sideBySide ? procBody.listTop : (cpuList.y + cpuList.height + 4)
              width: cpuList.width
              height: implicitHeight
              availHeight: procBody.sideBySide ? procBody.listRoom : Math.max(0, procBody.height - y)
              heading: "memory"
              rows: shell.procView && shell.procView.byMem ? shell.procView.byMem : []
              labelColor: shell.themeLabel
              textColor: shell.themeFg
              labelPx: shell.pxLabel
              rowPx: shell.pxLabel
              valueWidth: Math.round(shell.pxLabel * 5.5)
            }
          }
        }
      }
    }
    }
  }
}
