<template>
  <div class="automation-view">
    <div class="auto-header">
      <h2 class="auto-title">🤖 自动化工作台</h2>
      <p class="auto-subtitle">创建定时巡检任务，让 AI Agent 自动执行</p>
    </div>
    <div class="auto-tabs">
      <button @click="$store.currentAutomationTab = 'templates'" :class="['auto-tab', { active: $store.currentAutomationTab === 'templates' }]">📋 任务模板</button>
      <button @click="$store.currentAutomationTab = 'schedule'" :class="['auto-tab', { active: $store.currentAutomationTab === 'schedule' }]">⏰ 创建任务</button>
      <button @click="$store.currentAutomationTab = 'history'" :class="['auto-tab', { active: $store.currentAutomationTab === 'history' }]">📊 执行历史</button>
    </div>
    <div class="auto-content">
      <div v-if="$store.currentAutomationTab === 'templates'" class="templates-grid">
        <div v-for="(tpl, i) in $store.automationTemplates" :key="i" class="template-card" @click="useWorkflow(tpl)">
          <div class="tpl-icon" v-html="tpl.icon"></div>
          <div class="tpl-info">
            <h4 class="tpl-title">{{ tpl.title }}</h4>
            <p class="tpl-desc">{{ tpl.desc }}</p>
          </div>
          <i class="fa-solid fa-arrow-right tpl-arrow"></i>
        </div>
      </div>
      <div v-else-if="$store.currentAutomationTab === 'schedule'" class="schedule-form">
        <div class="form-group">
          <label class="form-label">任务描述 / Prompt</label>
          <textarea v-model="$store.scheduleConfig.prompt"
            class="form-textarea" rows="4"
            placeholder="描述你希望自动执行的任务，例如：每天 9:00 搜索最新的 AI 行业新闻并汇总"></textarea>
        </div>
        <div class="form-group">
          <label class="form-label">执行周期 (Cron 表达式)</label>
          <div class="cron-input-row">
            <input v-model="$store.scheduleConfig.cron" class="form-input cron-input"
              placeholder="*/1 * * * *">
            <span class="cron-hint">每分钟 | 每天9点: 0 9 * * * | 每小时: 0 * * * *</span>
          </div>
        </div>
        <button @click="createSchedule" class="create-schedule-btn" :disabled="$store.loading">
          <i class="fa-solid fa-play"></i> 创建定时任务
        </button>
      </div>
      <div v-else class="history-list">
        <div v-if="$store.alerts.length === 0" class="empty-history">暂无执行记录</div>
        <div v-for="(alert, idx) in $store.alerts" :key="idx" class="alert-card">
          <div class="alert-header">
            <span class="alert-time">{{ new Date(alert.created_at).toLocaleString() }}</span>
            <span :class="['alert-status', alert.status]">{{ alert.status }}</span>
          </div>
          <p class="alert-prompt">{{ alert.prompt }}</p>
          <div v-if="alert.report" class="alert-report" v-html="alert.report.replace(/\\n/g, '<br>')"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { store } from '../store.js'
import { useWorkflow, createSchedule, fetchAlerts } from '../composables/useChat.js'
import { onMounted } from 'vue'

export default {
  name: 'AutomationView',
  setup() {
    onMounted(() => {
      fetchAlerts()
    })
    return { $store: store, useWorkflow, createSchedule }
  }
}
</script>

<style scoped>
.automation-view {
  flex: 1; height: 100vh; overflow-y: auto; padding: 24px;
  background: #fff;
}
.auto-header { margin-bottom: 20px }
.auto-title { font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 4px }
.auto-subtitle { font-size: 13px; color: #94a3b8 }
.auto-tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid #e2e8f0; padding-bottom: 0 }
.auto-tab {
  padding: 8px 16px; border: none; background: none; color: #64748b;
  cursor: pointer; font-size: 13px; border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.auto-tab:hover { color: #3b82f6 }
.auto-tab.active { color: #3b82f6; border-bottom-color: #3b82f6; font-weight: 600 }
.auto-content { max-width: 800px }
.templates-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px }
.template-card {
  display: flex; align-items: center; gap: 12px; padding: 16px;
  border: 1px solid #e2e8f0; border-radius: 12px; cursor: pointer;
  background: #f8fafc; transition: all 0.2s;
}
.template-card:hover { border-color: #3b82f6; background: #eff6ff; transform: translateY(-1px); box-shadow: 0 2px 8px rgba(59,130,246,0.1) }
.tpl-icon { font-size: 24px; flex-shrink: 0 }
.tpl-info { flex: 1; min-width: 0 }
.tpl-title { font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 2px }
.tpl-desc { font-size: 12px; color: #94a3b8 }
.tpl-arrow { color: #94a3b8; font-size: 14px; flex-shrink: 0 }
.schedule-form { display: flex; flex-direction: column; gap: 16px }
.form-group { display: flex; flex-direction: column; gap: 6px }
.form-label { font-size: 13px; font-weight: 600; color: #475569 }
.form-textarea, .form-input {
  padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 10px;
  font-size: 14px; background: #fff; color: #1e293b; outline: none;
  font-family: inherit; transition: border-color 0.15s;
}
.form-textarea:focus, .form-input:focus { border-color: #3b82f6 }
.cron-input-row { display: flex; flex-direction: column; gap: 4px }
.cron-input { font-family: monospace }
.cron-hint { font-size: 11px; color: #94a3b8 }
.create-schedule-btn {
  padding: 12px 24px; background: #3b82f6; color: #fff; border: none;
  border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 600;
  transition: all 0.15s; align-self: flex-start;
}
.create-schedule-btn:hover { background: #2563eb }
.create-schedule-btn:disabled { background: #94a3b8; cursor: not-allowed }
.alert-card {
  padding: 16px; border: 1px solid #e2e8f0; border-radius: 12px;
  background: #f8fafc; margin-bottom: 12px;
}
.alert-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px }
.alert-time { font-size: 12px; color: #94a3b8 }
.alert-status { font-size: 11px; padding: 2px 8px; border-radius: 8px; font-weight: 600 }
.alert-status.completed { background: #dcfce7; color: #16a34a }
.alert-status.failed { background: #fee2e2; color: #dc2626 }
.alert-status.running { background: #dbeafe; color: #2563eb }
.alert-prompt { font-size: 13px; color: #475569; margin-bottom: 8px }
.alert-report { font-size: 12px; color: #64748b; max-height: 200px; overflow-y: auto }
.empty-history { padding: 40px; text-align: center; color: #94a3b8; font-size: 14px }
@media (prefers-color-scheme: dark) {
  .automation-view { background: #0f172a }
  .auto-title { color: #e2e8f0 }
  .auto-tabs { border-color: #1e293b }
  .auto-tab { color: #64748b }
  .auto-tab:hover, .auto-tab.active { color: #60a5fa }
  .auto-tab.active { border-color: #60a5fa }
  .template-card { background: #1e293b; border-color: #334155 }
  .template-card:hover { background: #1e3a5f; border-color: #3b82f6 }
  .tpl-title { color: #e2e8f0 }
  .form-label { color: #94a3b8 }
  .form-textarea, .form-input { background: #1e293b; border-color: #334155; color: #e2e8f0 }
  .alert-card { background: #1e293b; border-color: #334155 }
  .alert-prompt { color: #94a3b8 }
}
</style>
