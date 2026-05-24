<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="logo-area">
        <span class="logo-icon">✦</span>
        <span class="logo-text">Spectra</span>
        <button @click="collapseSidebar" class="sidebar-collapse-btn" title="隐藏左边侧栏">
          <i class="fa-solid fa-chevron-left"></i>
        </button>
      </div>
      <button @click="newChat" class="new-chat-btn" title="新对话">
        <i class="fa-solid fa-pen-to-square"></i>
        <span class="btn-label">新对话</span>
      </button>
    </div>
    <nav class="sidebar-nav">
      <button v-for="item in navItems" :key="item.view"
        @click="switchView(item.view)"
        :class="['nav-item', { active: $store.currentView === item.view }]">
        <i :class="item.icon"></i>
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>
    <div class="sidebar-section">
      <div class="section-header">
        <span class="section-title">历史记录</span>
        <button @click="refreshHistory" class="refresh-btn" title="刷新">
          <i class="fa-solid fa-rotate"></i>
        </button>
      </div>
      <div class="history-list">
        <div v-for="group in $store.historyGroups" :key="group.label" class="history-group">
          <div class="group-label">{{ group.label }}</div>
          <div v-for="item in group.items" :key="item.id"
            @click="loadConversation(item.id)"
            :class="['history-item', { active: $store.activeHistoryId === item.id }]">
            <span class="history-title">{{ item.title }}</span>
            <button @click="deleteConversation(item.id, $event)" class="history-del" title="删除">
              <i class="fa-solid fa-xmark"></i>
            </button>
          </div>
        </div>
        <div v-if="$store.historyGroups.length === 0" class="empty-history">暂无历史记录</div>
      </div>
    </div>
    <div class="sidebar-footer">
      <span class="version-text">Spectra v1.0</span>
    </div>
  </aside>
</template>

<script>
import { store } from '../store.js'
import { newChat, refreshHistoryGroups, loadConversation, deleteConversation } from '../composables/useHistory.js'

export default {
  name: 'AppSidebar',
  data() {
    return {
      $store: store,
      navItems: [
        { view: 'chat', icon: 'fa-solid fa-comments', label: '对话' },
        { view: 'skills', icon: 'fa-solid fa-wand-magic-sparkles', label: '技能' },
        { view: 'automation', icon: 'fa-solid fa-robot', label: '自动化' },
        { view: 'database', icon: 'fa-solid fa-database', label: '数据库' },
        { view: 'settings', icon: 'fa-solid fa-gear', label: '设置' },
      ]
    }
  },
  methods: {
    switchView(view) {
      store.currentView = view
      if (store.isMobile) store.leftDrawerOpen = false
    },
    collapseSidebar() {
      store.leftSidebarCollapsed = true
    },
    newChat,
    refreshHistory() { refreshHistoryGroups() },
    loadConversation,
    deleteConversation,
  }
}
</script>

<style scoped>
.sidebar {
  width: 260px; height: 100vh; background: #f8fafc;
  border-right: 1px solid #e2e8f0; display: flex; flex-direction: column;
  overflow: hidden;
}
.sidebar-header { padding: 16px; border-bottom: 1px solid #e2e8f0 }
.logo-area { display: flex; align-items: center; gap: 8px; margin-bottom: 12px }
.logo-icon { font-size: 22px; color: #3b82f6 }
.logo-text { font-size: 18px; font-weight: 700; color: #1e293b }
.sidebar-collapse-btn {
  margin-left: auto;
  width: 24px; height: 24px;
  border: none; border-radius: 6px;
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
  font-size: 11px;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.sidebar-collapse-btn:hover { background: #e2e8f0; color: #64748b }
.new-chat-btn {
  width: 100%; padding: 10px; border: 1px dashed #94a3b8; border-radius: 10px;
  background: #fff; color: #475569; cursor: pointer; font-size: 13px;
  display: flex; align-items: center; justify-content: center; gap: 6px;
  transition: all 0.15s;
}
.new-chat-btn:hover { border-color: #3b82f6; color: #3b82f6; background: #eff6ff }
.sidebar-nav {
  display: flex; flex-direction: column; gap: 2px; padding: 8px;
  border-bottom: 1px solid #e2e8f0;
}
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border: none; border-radius: 8px; background: transparent;
  color: #475569; cursor: pointer; font-size: 14px; text-align: left;
  transition: all 0.15s;
}
.nav-item:hover { background: #e2e8f0 }
.nav-item.active { background: #3b82f6; color: #fff }
.sidebar-section { flex: 1; overflow: hidden; display: flex; flex-direction: column; padding: 8px }
.section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 8px 4px;
}
.section-title { font-size: 12px; font-weight: 600; color: #94a3b8; text-transform: uppercase }
.refresh-btn { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 12px }
.history-list { flex: 1; overflow-y: auto; padding: 4px 0 }
.history-group { margin-bottom: 8px }
.group-label { font-size: 11px; color: #94a3b8; padding: 4px 8px }
.history-item {
  display: flex; align-items: center; padding: 8px 12px;
  border-radius: 8px; cursor: pointer; transition: all 0.15s; gap: 8px;
}
.history-item:hover { background: #e2e8f0 }
.history-item.active { background: #dbeafe }
.history-title { flex: 1; font-size: 13px; color: #475569; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.history-del { background: none; border: none; color: #94a3b8; cursor: pointer; opacity: 0; transition: opacity 0.15s; font-size: 12px; padding: 2px }
.history-item:hover .history-del { opacity: 1 }
.history-del:hover { color: #ef4444 }
.empty-history { padding: 16px; text-align: center; color: #94a3b8; font-size: 13px }
.sidebar-footer { padding: 12px 16px; border-top: 1px solid #e2e8f0 }
.version-text { font-size: 11px; color: #94a3b8 }
@media (prefers-color-scheme: dark) {
  .sidebar { background: #0f172a; border-color: #1e293b }
  .sidebar-header { border-color: #1e293b }
  .logo-text { color: #e2e8f0 }
  .new-chat-btn { background: #1e293b; border-color: #334155; color: #94a3b8 }
  .new-chat-btn:hover { border-color: #3b82f6; color: #60a5fa; background: #1e3a5f }
  .sidebar-nav { border-color: #1e293b }
  .nav-item { color: #94a3b8 }
  .nav-item:hover { background: #1e293b }
  .sidebar-section, .section-header, .sidebar-footer { border-color: #1e293b }
  .history-item:hover { background: #1e293b }
  .history-item.active { background: #1e3a5f }
  .history-title { color: #94a3b8 }
  .sidebar-collapse-btn { color: #334155 }
  .sidebar-collapse-btn:hover { background: #1e293b; color: #94a3b8 }
}
</style>
