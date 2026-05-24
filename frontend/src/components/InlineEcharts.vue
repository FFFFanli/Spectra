<template>
  <div :id="chartId" class="inline-echarts-container" :style="{ width: '100%', height: chartHeight + 'px' }">
    <div v-if="loading" class="chart-loading-skeleton">
      <div class="skeleton-pulse">
        <div class="skeleton-text skeleton-text-short"></div>
        <div class="skeleton-chart-area"></div>
        <div class="skeleton-text skeleton-text-long"></div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import {
  isDarkMode, setChartInstance, disposeChart, getChartInstance
} from '../utils/charts.js'

export default {
  name: 'InlineEcharts',
  props: {
    chartId: { type: String, required: true },
    jsonStr: { type: String, default: '' },
    title: { type: String, default: '' },
    height: { type: Number, default: 400 },
    streaming: { type: Boolean, default: false }
  },
  setup(props) {
    const loading = ref(true)
    const chartHeight = ref(props.height)
    let chart = null

    watch(() => props.jsonStr, async (newVal) => {
      if (newVal && newVal.trim()) {
        await nextTick()
        initOrUpdateChart(newVal)
      }
    })

    watch(() => props.chartId, async (newId, oldId) => {
      if (newId !== oldId && props.jsonStr && props.jsonStr.trim()) {
        if (oldId) {
          disposeChart(oldId)
        }
        await nextTick()
        initOrUpdateChart(props.jsonStr)
      }
    })

    watch(() => props.streaming, (val) => {
      if (!val && props.jsonStr) {
        initOrUpdateChart(props.jsonStr)
      }
    })

    async function initOrUpdateChart(jsonStr) {
      const dom = document.getElementById(props.chartId)
      if (!dom) return

      try {
        let option = JSON.parse(jsonStr)
        option = applyDefaults(option)

        const dark = isDarkMode()

        const existing = getChartInstance(props.chartId)
        if (existing) {
          existing.chart.setOption(option, { notMerge: false })
          existing.option = option
          loading.value = false
          return
        }

        const existingDom = echarts.getInstanceByDom(dom)
        if (existingDom) existingDom.dispose()

        chart = echarts.init(dom, dark ? 'dark' : undefined)
        chart.setOption(option)
        setChartInstance(props.chartId, chart, option)
        loading.value = false
      } catch (e) {
        console.warn('ECharts JSON 解析失败，等待完整数据...', e.message)
        if (props.streaming) {
          loading.value = true
        }
      }
    }

    function applyDefaults(option) {
      if (!option.tooltip) {
        option.tooltip = { trigger: option.xAxis ? 'axis' : 'item' }
      }
      if (!option.toolbox) {
        option.toolbox = {
          show: true,
          right: 12,
          top: 4,
          feature: {
            dataZoom: { yAxisIndex: 'none' },
            dataView: { readOnly: false },
            saveAsImage: { pixelRatio: 2 }
          }
        }
      }
      if (!option.legend && option.series && option.series.length > 0) {
        const first = option.series[0]
        if (first.name) {
          option.legend = { show: true, top: 4, left: 'center' }
        }
      }
      if (option.grid === undefined) {
        option.grid = { left: '3%', right: '4%', bottom: '12%', top: 40, containLabel: true }
      }
      if (!option.animation) {
        option.animation = true
      }
      option.backgroundColor = 'transparent'
      return option
    }

    function handleResize() {
      if (chart && !chart.isDisposed()) {
        chart.resize()
      }
    }

    onMounted(() => {
      window.addEventListener('resize', handleResize)
      if (props.jsonStr && props.jsonStr.trim()) {
        initOrUpdateChart(props.jsonStr)
      }
    })

    onUnmounted(() => {
      window.removeEventListener('resize', handleResize)
      disposeChart(props.chartId)
      chart = null
    })

    return { loading, chartHeight }
  }
}
</script>

<style scoped>
.inline-echarts-container {
  margin: 16px 0;
  border-radius: 12px;
  min-height: 120px;
  transition: all 0.3s ease;
}
.chart-loading-skeleton {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 200px;
  background: rgba(128, 128, 128, 0.06);
  border-radius: 12px;
  border: 1px dashed rgba(128, 128, 128, 0.2);
}
.skeleton-pulse {
  width: 100%;
  padding: 24px;
  animation: skeleton-pulse 1.8s ease-in-out infinite;
}
.skeleton-chart-area {
  width: 100%;
  height: 240px;
  background: rgba(128, 128, 128, 0.1);
  border-radius: 8px;
  margin: 16px 0;
}
.skeleton-text {
  height: 14px;
  background: rgba(128, 128, 128, 0.15);
  border-radius: 4px;
  margin: 8px auto;
}
.skeleton-text-short { width: 30% }
.skeleton-text-long { width: 70% }
@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5 }
  50% { opacity: 1 }
}
</style>
