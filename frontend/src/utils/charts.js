const _chartInstances = {}

export function hashStr(str) {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i)
    hash = ((hash << 5) - hash) + c
    hash |= 0
  }
  return Math.abs(hash).toString(16)
}

export function isDarkMode() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function disposeChart(chartId) {
  if (_chartInstances[chartId]) {
    try { _chartInstances[chartId].chart.dispose() } catch (e) {}
    delete _chartInstances[chartId]
  }
}

export function disposeAllCharts() {
  Object.keys(_chartInstances).forEach(disposeChart)
}

export function reInitAllCharts() {
  if (typeof echarts === 'undefined') return
  const dark = isDarkMode()
  Object.entries(_chartInstances).forEach(([id, entry]) => {
    try { entry.chart.dispose() } catch (e) {}
    const dom = document.getElementById(id)
    if (!dom) { delete _chartInstances[id]; return }
    try {
      const chart = echarts.init(dom, dark ? 'dark' : undefined)
      chart.setOption(entry.option)
      _chartInstances[id] = { chart, option: entry.option }
    } catch (e) {
      console.error('主题切换重渲染失败', e)
      delete _chartInstances[id]
    }
  })
}

export function getChartInstance(chartId) {
  return _chartInstances[chartId]
}

export function setChartInstance(chartId, chart, option) {
  _chartInstances[chartId] = { chart, option }
}

export function resizeAllCharts() {
  Object.values(_chartInstances).forEach(entry => {
    try { entry.chart.resize() } catch (e) {}
  })
}
