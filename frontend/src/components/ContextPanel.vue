<template>
  <aside class="context-panel">
    <div class="panel-header">
      <button @click="collapsePanel" class="panel-collapse-btn" title="隐藏工具栏">
        <i class="fa-solid fa-chevron-right"></i>
      </button>
    </div>
    <div class="panel-section">
      <div class="section-title-row">
        <i class="fa-solid fa-list-check section-icon" style="color: #3b82f6"></i>
        <span class="section-title">待办</span>
        <span v-if="$store.taskTodos.length" class="section-badge">{{ doneCount }}/{{ $store.taskTodos.length }}</span>
      </div>
      <div class="section-body">
        <!-- Phase 2: 有 plan 时展示 plan steps -->
        <template v-if="$store.taskPlan.steps.length > 0">
          <div v-for="s in $store.taskPlan.steps" :key="s.id" class="todo-item">
            <i :class="['todo-status', s.status === 'done' ? 'fa-solid fa-circle-check done' : s.status === 'running' ? 'fa-solid fa-spinner fa-spin running' : s.status === 'failed' ? 'fa-solid fa-circle-xmark failed' : 'fa-regular fa-circle pending']"></i>
            <span :class="['todo-text', { done: s.status === 'done', running: s.status === 'running', failed: s.status === 'failed' }]">{{ s.description }}</span>
          </div>
        </template>
        <template v-else>
          <div v-if="$store.taskTodos.length === 0" class="empty-hint">
            <i class="fa-solid fa-inbox"></i>
            <span>暂无待办任务</span>
            <small>Agent 执行任务时会自动展示</small>
          </div>
          <div v-for="todo in $store.taskTodos" :key="todo.id" class="todo-item">
            <i :class="['todo-status', todo.status === 'done' ? 'fa-solid fa-circle-check done' : todo.status === 'running' ? 'fa-solid fa-spinner fa-spin running' : 'fa-regular fa-circle pending']"></i>
            <span :class="['todo-text', { done: todo.status === 'done', running: todo.status === 'running' }]">{{ todo.text }}</span>
          </div>
        </template>
      </div>
    </div>

    <div class="section-divider"></div>

    <div class="panel-section">
      <div class="section-title-row">
        <i class="fa-solid fa-box-archive section-icon" style="color: #8b5cf6"></i>
        <span class="section-title">任务产物</span>
        <span v-if="$store.taskArtifacts.length" class="section-badge">{{ $store.taskArtifacts.length }}</span>
      </div>
      <div class="section-body">
        <div v-if="$store.taskArtifacts.length === 0" class="empty-hint">
          <i class="fa-solid fa-cube"></i>
          <span>暂无产物</span>
          <small>生成的图表、文件将显示在这里</small>
        </div>
        <div v-for="art in $store.taskArtifacts" :key="art.id" class="artifact-item">
          <i :class="artifactIcon(art.type)"></i>
          <span class="artifact-name">{{ art.name }}</span>
        </div>
      </div>
    </div>

    <div class="section-divider"></div>

    <div class="panel-section">
      <div class="section-title-row">
        <i class="fa-solid fa-circle-info section-icon" style="color: #06b6d4"></i>
        <span class="section-title">参考信息</span>
      </div>
      <div class="section-body">
        <div v-if="$store.referenceSkills.length">
          <div class="ref-subtitle">🛠 技能</div>
          <div v-for="s in $store.referenceSkills" :key="s.name" class="ref-item skill-ref">
            <i class="fa-solid fa-puzzle-piece"></i>
            <span>{{ s.name }}</span>
          </div>
        </div>
        <div v-if="$store.referenceLinks.length">
          <div class="ref-subtitle" style="margin-top: 12px">🌐 联网搜索</div>
          <div v-for="link in $store.referenceLinks" :key="link.url" class="ref-item link-ref">
            <i class="fa-solid fa-link"></i>
            <a :href="link.url" target="_blank" class="ref-link">{{ link.title || link.url }}</a>
          </div>
        </div>
        <div v-if="$store.referenceSkills.length === 0 && $store.referenceLinks.length === 0" class="empty-hint">
          <i class="fa-solid fa-book"></i>
          <span>暂无参考信息</span>
          <small>使用的技能和搜索网页将显示在这里</small>
        </div>
      </div>
    </div>
  </aside>
</template>

<script>
import { computed } from 'vue'
import { store } from '../store.js'

export default {
  name: 'ContextPanel',
  setup() {
    const doneCount = computed(() => store.taskTodos.filter(t => t.status === 'done').length)

    function artifactIcon(type) {
      switch (type) {
        case 'chart': return 'fa-solid fa-chart-simple'
        case 'file': return 'fa-solid fa-file'
        case 'report': return 'fa-solid fa-file-pdf'
        default: return 'fa-solid fa-file'
      }
    }

    function collapsePanel() {
      store.rightSidebarCollapsed = true
    }

    return { $store: store, doneCount, artifactIcon, collapsePanel }
  }
}
</script>

<style scoped>
.context-panel {
  width: 280px; height: 100vh; overflow-y: auto;
  background: #fafafa; border-left: 1px solid #f1f5f9;
  display: flex; flex-direction: column; flex-shrink: 0;
}
.panel-header {
  display: flex; justify-content: flex-end;
  padding: 8px 12px 4px;
}
.panel-collapse-btn {
  width: 24px; height: 24px;
  border: none; border-radius: 6px;
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
  font-size: 11px;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.panel-collapse-btn:hover { background: #f1f5f9; color: #64748b }
.panel-section { padding: 0; flex-shrink: 0 }
.section-title-row {
  display: flex; align-items: center; gap: 8px;
  padding: 14px 16px 10px;
}
.section-icon { font-size: 14px }
.section-title { font-size: 13px; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: 0.5px }
.section-badge { font-size: 11px; color: #64748b; background: #f1f5f9; padding: 1px 7px; border-radius: 8px; margin-left: auto }
.section-body { padding: 0 16px 12px }
.empty-hint {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 20px 12px; color: #64748b; text-align: center;
}
.empty-hint i { font-size: 20px; opacity: 0.5 }
.empty-hint span { font-size: 12px }
.empty-hint small { font-size: 10px; color: #94a3b8 }
.todo-item { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0 }
.todo-status { font-size: 13px; margin-top: 1px; flex-shrink: 0 }
.todo-status.done { color: #22c55e }
.todo-status.running { color: #3b82f6; animation: fa-spin 1s linear infinite }
.todo-status.pending { color: #cbd5e1 }
.todo-text { font-size: 12px; color: #334155; line-height: 1.5 }
.todo-text.done { color: #94a3b8; text-decoration: line-through }
.todo-text.running { color: #1d4ed8; font-weight: 500 }
.todo-text.failed { color: #ef4444; font-weight: 500 }
.todo-status.failed { color: #ef4444 }
.section-divider { height: 1px; background: #f1f5f9; margin: 0 }
.artifact-item { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; color: #334155 }
.artifact-item i { color: #8b5cf6; font-size: 12px; width: 16px; text-align: center }
.artifact-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.ref-subtitle { font-size: 11px; color: #64748b; font-weight: 500; margin-bottom: 4px }
.ref-item { display: flex; align-items: flex-start; gap: 7px; padding: 3px 0; font-size: 11px; color: #334155 }
.ref-item i { font-size: 10px; color: #64748b; margin-top: 2px; flex-shrink: 0 }
.ref-link { color: #3b82f6; text-decoration: none; word-break: break-all; line-height: 1.5 }
.ref-link:hover { text-decoration: underline }
@media (max-width: 1023px) {
  .context-panel { width: 260px }
}
@media (prefers-color-scheme: dark) {
  .context-panel { background: #0f172a; border-color: #1e293b }
  .section-title { color: #94a3b8 }
  .section-badge { background: #1e293b; color: #64748b }
  .section-divider { background: #1e293b }
  .todo-text { color: #94a3b8 }
  .todo-text.running { color: #60a5fa }
  .todo-status.pending { color: #475569 }
  .empty-hint { color: #64748b }
  .empty-hint small { color: #475569 }
  .artifact-item { color: #94a3b8 }
  .ref-item { color: #94a3b8 }
  .ref-item i { color: #64748b }
  .ref-link { color: #60a5fa }
  .panel-collapse-btn { color: #334155 }
  .panel-collapse-btn:hover { background: #1e293b; color: #94a3b8 }
}
</style>
