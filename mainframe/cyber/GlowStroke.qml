import QtQuick
import QtQuick.Shapes

Shape {
  id: root
  property string path: ""
  property color stroke
  preferredRendererType: Shape.SoftwareRenderer
  asynchronous: false
  antialiasing: false
  ShapePath {
    fillColor: "transparent"
    strokeColor: Qt.rgba(root.stroke.r, root.stroke.g, root.stroke.b, 0.22)
    strokeWidth: 5
    capStyle: ShapePath.RoundCap
    joinStyle: ShapePath.RoundJoin
    PathSvg { path: root.path }
  }
}
