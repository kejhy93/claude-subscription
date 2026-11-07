import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "claude.subscription"

  function injectPanel() {
    if (!panelLoader.item) return
    if ("bar" in panelLoader.item) panelLoader.item.bar = root.bar
    if ("settings" in panelLoader.item) panelLoader.item.settings = root.settings
    if ("anchorItem" in panelLoader.item) panelLoader.item.anchorItem = button
  }

  function refresh() { if (panelLoader.item) panelLoader.item.refresh() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing : false
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("UsagePanel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
      item.refresh()
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "✳"
    slotSize: Style.bar.statusSlot
    tooltipText: "Claude subscription usage"
    onPressed: function(b) {
      if (b === Qt.MiddleButton) root.refresh()
      else root.togglePanel()
    }
  }
}
