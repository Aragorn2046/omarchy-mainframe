// Signal hooks for one ssh slot start.
// A QML property read can drop function identity, and disconnect() needs
// the same function that connect() stored. This map keeps that identity.

var hooks = {}
var sessions = {}

function reserve(alias, token) {
  var key = "$" + alias
  if (sessions[key]) return false
  sessions[key] = { token: token, state: "running" }
  return true
}

function stopping(alias, token) {
  var entry = sessions["$" + alias]
  if (entry && entry.token === token) entry.state = "stopping"
}

function release(alias, token, leaderExited, groupGone) {
  var key = "$" + alias
  if (!sessions[key] || sessions[key].token !== token || !leaderExited || !groupGone) return false
  delete sessions[key]
  return true
}

function busy(alias) { return !!sessions["$" + alias] }

function save(token, bag) {
  hooks[String(token)] = bag
}

function take(token) {
  var key = String(token)
  var bag = hooks[key] || null
  if (bag) delete hooks[key]
  return bag
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { reserve: reserve, stopping: stopping, release: release, busy: busy }
}
