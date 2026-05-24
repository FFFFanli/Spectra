<template>
  <aside :class="['runtime-panel', { collapsed: $store.rightSidebarCollapsed }]">
    <div v-if="!$store.rightSidebarCollapsed" class="rp-content">
      <div class="rp-header">
        <span class="rp-title">Runtime 工作台</span>
        <button @click="$store.rightSidebarCollapsed = true" class="rp-close"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <!-- Phase 2: 任务规划 checklist -->
      <div v-if="$store.taskPlan.steps.length > 0" class="rp-section rp-plan-section">
        <h4 class="rp-section-title">
          任务规划
          <span class="rp-plan-count">{{ completedStepCount }}/{{ $store.taskPlan.steps.length }}</span>
          <span v-if="$store.taskPlan.finished" class="rp-plan-done-badge">完成</span>
          <span v-if="$store.taskPlan.revision > 0" class="rp-plan-rev-badge">v{{ $store.taskPlan.revision + 1 }}</span>
        </h4>
        <div class="rp-plan-progress">
          <div class="rp-plan-bar">
            <div class="rp-plan-bar-fill" :style="{ width: $store.taskPlan.progress + '%' }"></div>
          </div>
          <span class="rp-plan-pct">{{ $store.taskPlan.progress }}%</span>
        </div>
        <div class="rp-plan-steps">
          <div
            v-for="s in $store.taskPlan.steps"
            :key="s.id"
            :class="['rp-plan-step', 'rp-plan-step--' + s.status]"
          >
            <span class="rp-plan-step-icon">{{ stepIcon(s.status) }}</span>
            <span class="rp-plan-step-desc">{{ s.description }}</span>
            <span v-if="s.note" class="rp-plan-step-note">{{ s.note }}</span>
          </div>
        </div>
        <div v-if="$store.taskPlan.finished && $store.taskPlan.summary" class="rp-plan-summary">
          {{ $store.taskPlan.summary }}
        </div>
      </div>

      <div class="rp-section">
        <h4 class="rp-section-title">执行状态</h4>
        <div class="rp-grid">
          <div class="rp-field">
            <span class="rp-label">模式</span>
            <span class="rp-value">Solo Agent</span>
          </div>
          <div class="rp-field">
            <span class="rp-label">当前节点</span>
            <span class="rp-value">{{ $store.runtimeState.node || '-' }}</span>
          </div>
          <div class="rp-field">
            <span class="rp-label">活跃 Agent</span>
            <span class="rp-value">{{ $store.runtimeState.activeAgent || '-' }}</span>
          </div>
          <div class="rp-field">
            <span class="rp-label">Skill</span>
            <span class="rp-value">{{ $store.runtimeState.selectedSkillName || '-' }}</span>
          </div>
        </div>
      </div>
      <div class="rp-section">
        <h4 class="rp-section-title">Token 用量</h4>
        <div class="rp-grid">
          <div class="rp-field">
            <span class="rp-label">输入</span>
            <span class="rp-value">{{ formatTokens($store.usageStats.total.input_tokens) }}</span>
          </div>
          <div class="rp-field">
            <span class="rp-label">输出</span>
            <span class="rp-value">{{ formatTokens($store.usageStats.total.output_tokens) }}</span>
          </div>
          <div class="rp-field">
            <span class="rp-label">合计</span>
            <span class="rp-value rp-value-strong">{{ formatTokens($store.usageStats.total.total_tokens) }}</span>
          </div>
        </div>
        <div v-if="hasMultiModelUsage" class="rp-usage-breakdown">
          <div v-for="(u, m) in $store.usageStats.by_model" :key="m" class="rp-usage-row">
            <span class="rp-usage-model">{{ m }}</span>
            <span class="rp-usage-tokens">{{ formatTokens(u.input_tokens) }} 入 / {{ formatTokens(u.output_tokens) }} 出</span>
          </div>
        </div>
      </div>
      <div class="rp-section">
        <h4 class="rp-section-title">生命周期事件</h4>
        <div class="rp-timeline">
          <div v-if="$store.runtimeTimeline.length === 0" class="rp-empty">暂无事件</div>
          <div v-for="(evt, idx) in $store.runtimeTimeline" :key="evt.key + idx" class="rp-tl-item">
            <div class="rp-tl-dot"></div>
            <div class="rp-tl-line" v-if="idx < $store.runtimeTimeline.length - 1"></div>
            <div class="rp-tl-content">
              <span class="rp-tl-event">{{ runtimeLifecycleLabel(evt.lifecycleEvent) }}</span>
              <span class="rp-tl-detail">{{ evt.node || evt.activeAgent }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="$store.charts.length > 0 || $store.files.length > 0" class="rp-section">
        <h4 class="rp-section-title">产出文件</h4>
        <div class="rp-files">
          <div v-for="f in $store.files" :key="f.path" class="rp-file-item">
            <i class="fa-solid fa-file"></i>
            <a :href="`/files/${f.path}`" target="_blank" class="rp-file-link">{{ f.name }}</a>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="rp-collapsed-bar">
      <button @click="$store.rightSidebarCollapsed = false" class="rp-expand-btn" title="展开 Runtime 工作台">
        <i class="fa-solid fa-panel-closed"></i>
      </button>
    </div>
  </aside>
</template>

<script>
import { computed } from 'vue'
import { store } from '../store.js'
import { runtimeLifecycleLabel } from '../composables/useHistory.js'

export default {
  name: 'RuntimePanel',
  setup() {
    function formatTokens(n) {
      const v = Number(n || 0)
      if (v >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M'
      if (v >= 10_000) return (v / 1000).toFixed(1) + 'k'
      return v.toLocaleString()
    }
    const hasMultiModelUsage = computed(
      () => Object.keys(store.usageStats?.by_model || {}).length > 1
    )
    const completedStepCount = computed(
      () => store.taskPlan.steps.filter(s => s.status === 'done' || s.status === 'failed').length
    )
    function stepIcon(status) {
      switch (status) {
        case 'done': return '✓'
        case 'running': return '⟳'
        case 'failed': return '✗'
        default: return '○'
      }
    }
    return {
      $store: store,
      runtimeLifecycleLabel,
      formatTokens,
      hasMultiModelUsage,
      completedStepCount,
      stepIcon,
    }
  }
}
</script>

<style scoped>
.runtime-panel {
  width: 280px; height: 100vh; border-left: 1px solid #e2e8f0;
  background: #f8fafc; overflow: hidden; display: flex; flex-direction: column;
  transition: width 0.25s ease;
}
.runtime-panel.collapsed { width: 40px }
.rp-content { flex: 1; overflow-y: auto; padding: 12px }
.rp-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px;
}
.rp-title { font-size: 14px; font-weight: 600; color: #1e293b }
.rp-close { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 14px }
.rp-section { margin-bottom: 16px }
.rp-section-title { font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; margin-bottom: 8px }
.rp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px }
.rp-field { background: #fff; padding: 8px; border-radius: 6px; border: 1px solid #e2e8f0 }
.rp-label { display: block; font-size: 10px; color: #94a3b8; margin-bottom: 2px }
.rp-value { font-size: 12px; color: #1e293b; font-weight: 500 }
.rp-value-strong { color: #2563eb; font-weight: 600 }
.rp-usage-breakdown { margin-top: 8px; display: flex; flex-direction: column; gap: 4px }
.rp-usage-row {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; color: #475569; padding: 4px 8px;
  background: #f1f5f9; border-radius: 4px;
}
.rp-usage-model { font-weight: 500 }
.rp-usage-tokens { color: #64748b; font-feature-settings: 'tnum' }
.rp-timeline { position: relative }
.rp-empty { font-size: 12px; color: #94a3b8; padding: 8px }
.rp-tl-item { position: relative; padding-left: 20px; margin-bottom: 10px }
.rp-tl-dot {
  position: absolute; left: 2px; top: 4px; width: 8px; height: 8px;
  border-radius: 50%; background: #3b82f6;
}
.rp-tl-line {
  position: absolute; left: 5px; top: 14px; width: 2px;
  height: calc(100% + 2px); background: #e2e8f0;
}
.rp-tl-content { display: flex; flex-direction: column }
.rp-tl-event { font-size: 12px; color: #1e293b }
.rp-tl-detail { font-size: 11px; color: #94a3b8 }
.rp-files { display: flex; flex-direction: column; gap: 4px }
.rp-file-item { display: flex; align-items: center; gap: 6px; font-size: 12px }
.rp-file-link { color: #3b82f6; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.rp-file-link:hover { text-decoration: underline }
.rp-collapsed-bar {
  display: flex; justify-content: center; padding: 12px 0;
}
.rp-expand-btn { background: none; border: none; color: #64748b; cursor: pointer; font-size: 16px }
/* Phase 2: plan section */
.rp-plan-section {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px;
}
.rp-plan-count {
  font-size: 11px; font-weight: 400; color: #64748b; margin-left: 6px;
}
.rp-plan-done-badge {
  font-size: 10px; background: #dcfce7; color: #16a34a; padding: 1px 6px; border-radius: 4px; margin-left: 6px;
}
.rp-plan-rev-badge {
  font-size: 10px; background: #fef3c7; color: #d97706; padding: 1px 6px; border-radius: 4px; margin-left: 4px;
}
.rp-plan-progress {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.rp-plan-bar {
  flex: 1; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden;
}
.rp-plan-bar-fill {
  height: 100%; background: #3b82f6; border-radius: 3px; transition: width 0.3s ease;
}
.rp-plan-pct {
  font-size: 11px; color: #64748b; font-feature-settings: 'tnum'; min-width: 32px; text-align: right;
}
.rp-plan-steps {
  display: flex; flex-direction: column; gap: 4px;
}
.rp-plan-step {
  display: flex; align-items: flex-start; gap: 6px; font-size: 12px; padding: 4px 6px; border-radius: 4px;
  border-left: 3px solid transparent;
}
.rp-plan-step--running {
  background: #eff6ff; border-left-color: #3b82f6;
}
.rp-plan-step--failed {
  background: #fef2f2; border-left-color: #ef4444;
}
.rp-plan-step--done {
  opacity: 0.65;
}
.rp-plan-step-icon {
  flex-shrink: 0; width: 16px; text-align: center; font-size: 11px;
}
.rp-plan-step--running .rp-plan-step-icon { color: #3b82f6; font-weight: 700 }
.rp-plan-step--done .rp-plan-step-icon { color: #16a34a }
.rp-plan-step--failed .rp-plan-step-icon { color: #ef4444; font-weight: 700 }
.rp-plan-step--pending .rp-plan-step-icon { color: #94a3b8 }
.rp-plan-step-desc { flex: 1; color: #1e293b; line-height: 1.4 }
.rp-plan-step-note {
  display: block; font-size: 10px; color: #ef4444; margin-top: 2px; word-break: break-all;
}
.rp-plan-step--failed .rp-plan-step-note { display: block }
.rp-plan-summary {
  margin-top: 8px; padding: 6px 8px; font-size: 11px; color: #16a34a; background: #f0fdf4;
  border-radius: 4px; line-height: 1.4;
}

@media (prefers-color-scheme: dark) {
  .runtime-panel { background: #0f172a; border-color: #1e293b }
  .rp-title { color: #e2e8f0 }
  .rp-field { background: #1e293b; border-color: #334155 }
  .rp-value { color: #e2e8f0 }
  .rp-value-strong { color: #60a5fa }
  .rp-usage-row { background: #1e293b; color: #cbd5e1 }
  .rp-usage-tokens { color: #94a3b8 }
  .rp-tl-event { color: #e2e8f0 }
  .rp-tl-line { background: #334155 }
  .rp-plan-section { background: #1e293b; border-color: #334155 }
  .rp-plan-count { color: #94a3b8 }
  .rp-plan-bar { background: #334155 }
  .rp-plan-pct { color: #94a3b8 }
  .rp-plan-step--running { background: #1e3a5f; border-left-color: #60a5fa }
  .rp-plan-step--failed { background: #3b1a1a; border-left-color: #f87171 }
  .rp-plan-step-desc { color: #e2e8f0 }
  .rp-plan-summary { background: #0f2b1f; color: #4ade80 }
}
</style>
