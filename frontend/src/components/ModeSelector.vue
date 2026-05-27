<template>
  <div class="mode-selector">
    <button
      :class="['mode-btn', { active: $store.agentMode === 'solo' }]"
      @click="setAgentMode('solo')"
      :title="modeTitle('solo')"
    >
      <span class="mode-label">Solo</span>
      <span
        v-if="soloStreaming && $store.agentMode !== 'solo'"
        class="mode-dot pulsing"
        title="Solo 模式正在工作中"
      ></span>
    </button>
    <button
      :class="['mode-btn', { active: $store.agentMode === 'team' }]"
      @click="setAgentMode('team')"
      :title="modeTitle('team')"
    >
      <span class="mode-label">Team</span>
      <span
        v-if="teamStreaming && $store.agentMode !== 'team'"
        class="mode-dot pulsing"
        title="Team 模式正在工作中"
      ></span>
    </button>
  </div>
</template>

<script>
import { computed } from 'vue'
import { store, switchAgentMode } from '../store.js'

export default {
  name: 'ModeSelector',
  setup() {
    // 当前活跃的 loading 反映的是顶层 store.loading；非活跃 mode 的流式状态
    // 暂存在 session 容器的 isStreaming 字段中（Phase B 启用后才会真正写值）。
    const soloStreaming = computed(() => {
      if (store.agentMode === 'solo') return store.loading
      return !!(store.soloSession && store.soloSession.isStreaming)
    })

    const teamStreaming = computed(() => {
      if (store.agentMode === 'team') return store.loading
      return !!(store.teamSession && store.teamSession.isStreaming)
    })

    function setAgentMode(mode) {
      if (store.agentMode === mode) return
      // 流式中允许切换：原 mode 的 stream 持有 ownerSession 引用，
      // 后续 SSE 事件继续写入对应 session 不会污染新 mode 的对话。
      switchAgentMode(mode)
    }

    function modeTitle(mode) {
      return mode === 'solo' ? '单一 Agent 独立执行' : '多 Agent 团队协作'
    }

    return {
      $store: store,
      soloStreaming,
      teamStreaming,
      setAgentMode,
      modeTitle,
    }
  },
}
</script>

<style scoped>
.mode-selector {
  display: flex;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid #f1f5f9;
  background: #fafafa;
  gap: 0;
}
.mode-btn {
  position: relative;
  padding: 2px 14px;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 11px;
  transition: all 0.15s;
  font-weight: 500;
  white-space: nowrap;
  line-height: 1.8;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.mode-btn.active {
  background: #ffffff;
  color: #1e293b;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.mode-btn:hover:not(.active):not(:disabled) {
  color: #475569;
}
.mode-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.mode-label {
  display: inline-block;
}
.mode-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
}
.mode-dot.pulsing {
  animation: dot-pulse 1.4s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.15); }
}
@media (prefers-color-scheme: dark) {
  .mode-selector { border-color: #1e293b; background: #1e293b; }
  .mode-btn { color: #64748b; }
  .mode-btn.active {
    background: #334155;
    color: #e2e8f0;
    box-shadow: none;
  }
  .mode-btn:hover:not(.active):not(:disabled) { color: #94a3b8; }
}
</style>
