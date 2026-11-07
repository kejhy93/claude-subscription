import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Panel {
  id: root
  moduleName: "claude.subscription"
  ipcTarget: "claude.subscription"
  manageIpc: false

  property var anchorItem: null
  property string plan: strings.t("panel.planFallback")
  property string statusText: strings.t("panel.loading")
  property string errorText: ""
  property string lastUpdated: ""
  property var fiveHour: null
  property var sevenDay: null
  property bool loading: false
  property bool popoutSwitchClosing: false
  property double clockTick: Date.now()
  readonly property int maxPanelHeight: popup.screen ? Math.max(Style.space(280), popup.screen.height - Style.gapsOut * 4) : Style.space(560)

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  function refresh() {
    if (loading) return
    loading = true
    errorText = ""
    fetchProc.command = ["python3", Qt.resolvedUrl("fetch.py").toString().replace("file://", "")]
    fetchProc.running = true
  }

  function open() { root.controller.show(); root.refresh() }
  function openFromHotkey() { open() }
  function close() { root.controller.hide() }
  function toggle() { if (root.opened) close(); else open() }
  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root, direction)
    return false
  }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }
  function resetLabel(value) {
    var stamp = Number(value)
    if (!isFinite(stamp) || stamp <= 0) return strings.t("panel.resetUnavailable")
    var time = Qt.formatDateTime(new Date(stamp * 1000), Qt.locale(Commons.I18n.formatLocale), "ddd HH:mm")
    if (stamp <= root.clockTick / 1000) return strings.t("panel.resetDue").arg(time)
    return strings.t("panel.resetIn").arg(remainingDuration(stamp)).arg(time)
  }
  function remainingDuration(stamp) {
    var seconds = Math.max(0, Math.floor(Number(stamp) - root.clockTick / 1000))
    var days = Math.floor(seconds / 86400)
    var hours = Math.floor((seconds % 86400) / 3600)
    var minutes = Math.floor((seconds % 3600) / 60)
    if (days > 0)
      return strings.t("panel.durationDaysHours").arg(Commons.I18n.formatNumber(days)).arg(Commons.I18n.formatNumber(hours))
    if (hours > 0)
      return strings.t("panel.durationHoursMinutes").arg(Commons.I18n.formatNumber(hours)).arg(Commons.I18n.formatNumber(minutes))
    return strings.t("panel.durationMinutes").arg(Commons.I18n.formatNumber(Math.max(1, minutes)))
  }
  function usedPercentage(row) {
    if (!row || !isFinite(Number(row.used_percentage))) return 0
    return Math.max(0, Math.min(100, Number(row.used_percentage)))
  }
  function remainingPercentage(row) {
    return 100 - usedPercentage(row)
  }

  IpcHandler {
    target: "claude.subscription"
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh() }
  }

  Process {
    id: fetchProc
    running: false
    stdout: StdioCollector { onStreamFinished: root.handleResponse(String(text || "")) }
    stderr: StdioCollector { onStreamFinished: function(text) { if (String(text || "").trim() !== "") root.errorText = "Could not read Claude Code usage." } }
    onExited: function(exitCode) {
      root.loading = false
      if (exitCode !== 0 && root.errorText === "") root.errorText = "Could not read Claude Code usage (exit " + exitCode + ")"
      if (root.errorText !== "") root.statusText = root.errorText
    }
  }

  function handleResponse(raw) {
    var data = null
    try { data = JSON.parse(raw) } catch (e) {
      errorText = strings.t("panel.readError")
      statusText = errorText
      return
    }
    if (!data || data.error) {
      errorText = data && data.error ? String(data.error).slice(0, 180) : strings.t("panel.noUsage")
      statusText = errorText
      return
    }
    plan = typeof data.plan === "string" ? data.plan.slice(0, 48) : strings.t("panel.planFallback")
    fiveHour = data.five_hour && typeof data.five_hour === "object" ? data.five_hour : null
    sevenDay = data.seven_day && typeof data.seven_day === "object" ? data.seven_day : null
    var stamp = Number(data.updated_at)
    lastUpdated = isFinite(stamp) && stamp > 0
      ? Qt.formatDateTime(new Date(stamp * 1000), Qt.locale(Commons.I18n.formatLocale), "ddd HH:mm")
      : ""
    statusText = lastUpdated !== "" ? strings.t("panel.updated").arg(lastUpdated) : strings.t("panel.latest")
    errorText = ""
  }

  onOpenedChanged: if (opened) root.refresh()

  Timer {
    interval: 60000
    repeat: true
    running: root.opened
    onTriggered: {
      root.clockTick = Date.now()
      root.refresh()
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(420))
    contentHeight: popup.fittedContentHeight(Math.min(contentColumn.implicitHeight, root.maxPanelHeight))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: contentColumn
          width: parent.width
          spacing: Style.space(14)

          Row {
            width: parent.width
            spacing: Style.space(12)
            Text {
              textFormat: Text.PlainText
              text: "✳"
              color: root.bar ? root.bar.foreground : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.display
              anchors.verticalCenter: parent.verticalCenter
            }
            Column {
              anchors.verticalCenter: parent.verticalCenter
              Text {
                textFormat: Text.PlainText
                text: strings.t("panel.title")
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.title
                font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                text: root.plan + " · " + root.statusText
                color: root.bar ? Qt.darker(root.bar.foreground, 1.45) : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.caption
                wrapMode: Text.Wrap
              }
            }
          }

          Rectangle { width: parent.width; height: Style.spacing.hairline; color: root.bar ? root.bar.foreground : Color.foreground; opacity: 0.12 }

          Repeater {
            model: [
              { key: "five_hour", row: root.fiveHour, title: strings.t("panel.fiveHour") },
              { key: "seven_day", row: root.sevenDay, title: strings.t("panel.sevenDay") }
            ]
            delegate: Rectangle {
              required property var modelData
              width: contentColumn.width
              height: Style.space(90)
              radius: Style.cornerRadius
              color: root.bar ? Qt.alpha(root.bar.foreground, 0.055) : "#11000000"

              Column {
                anchors.fill: parent
                anchors.margins: Style.space(13)
                spacing: Style.space(8)

                RowLayout {
                  width: parent.width
                  spacing: Style.space(10)
                  Text {
                    id: windowLabel
                    textFormat: Text.PlainText
                    text: modelData.title
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    color: root.bar ? Qt.darker(root.bar.foreground, 1.45) : Color.foreground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.caption
                    font.letterSpacing: 1
                  }
                  Text {
                    id: usageLabel
                    textFormat: Text.PlainText
                    text: modelData.row ? strings.t("panel.remaining").arg(Commons.I18n.formatNumber(root.remainingPercentage(modelData.row), 0)) : strings.t("panel.noSnapshot")
                    color: root.bar ? root.bar.foreground : Color.foreground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    Layout.alignment: Qt.AlignRight
                  }
                }

                Rectangle {
                  width: parent.width
                  height: Style.space(7)
                  radius: height / 2
                  color: root.bar ? Qt.alpha(root.bar.foreground, 0.12) : "#22000000"
                  Rectangle {
                    width: parent.width * root.usedPercentage(modelData.row) / 100
                    height: parent.height
                    radius: parent.radius
                    color: Commons.Color.accent
                  }
                }

                Text {
                  textFormat: Text.PlainText
                  text: modelData.row ? root.resetLabel(modelData.row.resets_at) : strings.t("panel.noSnapshotHelp")
                  color: root.bar ? Qt.darker(root.bar.foreground, 1.4) : Color.foreground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }
              }
            }
          }

          Text {
            width: parent.width
            visible: root.errorText !== ""
            textFormat: Text.PlainText
            text: root.errorText
            wrapMode: Text.Wrap
            color: root.bar ? root.bar.urgent : Color.urgent
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Row {
            spacing: Style.space(8)
            Text {
              textFormat: Text.PlainText
              text: root.loading ? strings.t("panel.reading") : strings.t("panel.refresh")
              color: root.bar ? Qt.darker(root.bar.foreground, 1.35) : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              textFormat: Text.PlainText
              text: root.lastUpdated !== "" ? strings.t("panel.lastReport").arg(root.lastUpdated) : ""
              visible: root.lastUpdated !== ""
              color: root.bar ? Qt.darker(root.bar.foreground, 1.6) : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
            }
            TapHandler { onTapped: root.refresh() }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
          }
        }
      }
    }
  }
}
