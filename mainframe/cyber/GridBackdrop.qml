import QtQuick

Canvas {
  id: root
  property color accent
  onAccentChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()
  onPaint: {
    var ctx = getContext("2d")
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = accent
    ctx.globalAlpha = 0.06
    for (var x = 0; x < width; x += 40) ctx.fillRect(x, 0, 1, height)
    for (var y = 0; y < height; y += 4) {
      ctx.globalAlpha = y % 40 === 0 ? 0.06 : 0.025
      ctx.fillRect(0, y, width, 1)
    }
  }
}
