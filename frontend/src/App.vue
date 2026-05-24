<template>
  <AuthGate v-if="$store.authRequired" />
  <div v-else class="app-layout" :class="{ 'mobile-drawer-open': $store.leftDrawerOpen && $store.isMobile }">
    <transition name="sidebar-slide">
      <Sidebar v-show="shouldShowLeftSidebar" />
    </transition>
    <div v-if="$store.isMobile && $store.leftDrawerOpen" class="mobile-overlay" @click="$store.leftDrawerOpen = false"></div>
    <template v-if="$store.currentView === 'chat'">
      <div
        v-if="!$store.isMobile && $store.leftSidebarCollapsed"
        class="edge-restore edge-restore-left"
        @click="toggleLeftSidebar"
        title="显示左边侧栏"
      >
        <i class="fa-solid fa-chevron-right"></i>
      </div>
      <ChatView />
      <ContextPanel v-if="!$store.rightSidebarCollapsed" />
      <div
        v-if="!$store.isMobile && $store.rightSidebarCollapsed"
        class="edge-restore edge-restore-right"
        @click="toggleRightSidebar"
        title="显示工具栏"
      >
        <i class="fa-solid fa-chevron-left"></i>
      </div>
    </template>
    <template v-else-if="$store.currentView === 'skills'">
      <SkillsView />
    </template>
    <template v-else-if="$store.currentView === 'automation'">
      <AutomationView />
    </template>
    <template v-else-if="$store.currentView === 'database'">
      <DatabaseView />
    </template>
    <template v-else-if="$store.currentView === 'settings'">
      <SettingsView />
    </template>
  </div>
</template>

<script>
import { computed, onMounted, onUnmounted } from 'vue'
import { store } from './store.js'
import AuthGate from './components/AuthGate.vue'
import Sidebar from './components/Sidebar.vue'
import ChatView from './components/ChatView.vue'
import SkillsView from './components/SkillsView.vue'
import ContextPanel from './components/ContextPanel.vue'
import AutomationView from './components/AutomationView.vue'
import DatabaseView from './components/DatabaseView.vue'
import SettingsView from './components/SettingsView.vue'
import { syncViewport, loadSettingsFromStorage, fetchModels, loadPersonas } from './composables/useSettings.js'
import { refreshHistoryGroups } from './composables/useHistory.js'
import { apiFetch } from './utils/sse.js'
import { loadUserPreferences } from './composables/usePreferences.js'
import { reInitAllCharts, resizeAllCharts } from './utils/charts.js'

export default {
  name: 'App',
  components: { AuthGate, Sidebar, ChatView, SkillsView, ContextPanel, AutomationView, DatabaseView, SettingsView },
  setup() {
    const shouldShowLeftSidebar = computed(() => {
      if (store.isMobile) return store.leftDrawerOpen
      return !store.leftSidebarCollapsed
    })

    onMounted(async () => {
      await loadSettingsFromStorage()
      fetchModels()  // 不 await，后台加载不阻塞 UI
      loadPersonas()
      loadUserPreferences()

      // 探测定是否需要鉴权：带已有 code 请求 /api/conversations
      try {
        await apiFetch('/api/conversations')
        store.authRequired = false
      } catch (e) {
        if (e.message && String(e.message).includes('401')) {
          store.authRequired = true
          return // 暂停初始化，等待用户通过 AuthGate
        }
        store.authRequired = false
      }

      refreshHistoryGroups()

      window.addEventListener('resize', handleResize)
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', handleThemeChange)
    })

    onUnmounted(() => {
      window.removeEventListener('resize', handleResize)
      window.matchMedia('(prefers-color-scheme: dark)').removeEventListener('change', handleThemeChange)
    })

    function handleResize() {
      syncViewport()
      resizeAllCharts()
    }

    function handleThemeChange() {
      reInitAllCharts()
    }

    function toggleLeftSidebar() {
      if (store.isMobile) {
        store.leftDrawerOpen = !store.leftDrawerOpen
        return
      }
      store.leftSidebarCollapsed = !store.leftSidebarCollapsed
    }

    function toggleRightSidebar() {
      store.rightSidebarCollapsed = !store.rightSidebarCollapsed
    }

    return { $store: store, shouldShowLeftSidebar, toggleLeftSidebar, toggleRightSidebar }
  }
}
</script>

<style>
@tailwind base;
@tailwind components;
@tailwind utilities;

* { margin: 0; padding: 0; box-sizing: border-box }

html, body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  font-size: 14px; line-height: 1.5; color: #1e293b;
  background: #f1f5f9;
}

.app-layout { display: flex; height: 100vh; overflow: hidden; position: relative }

.edge-restore {
  position: absolute;
  top: 0;
  z-index: 20;
  width: 18px;
  height: 56px;
  background: rgba(15, 23, 42, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  color: #94a3b8;
  font-size: 9px;
}
.edge-restore:hover {
  background: rgba(15, 23, 42, 0.12);
  color: #475569;
  width: 22px;
}
.edge-restore-left { left: 0; border-radius: 0 8px 8px 0 }
.edge-restore-right {
  right: 0;
  border-radius: 8px 0 0 8px;
}

.mobile-overlay {
  display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  z-index: 40;
}

@media (max-width: 1023px) {
  .edge-restore { display: none }
  .sidebar-slide-enter-active,
  .sidebar-slide-leave-active {
    transition: transform 0.25s ease;
  }
  .sidebar-slide-enter-from,
  .sidebar-slide-leave-to {
    transform: translateX(-100%);
  }
  .mobile-overlay { display: block }
}

@media (prefers-color-scheme: dark) {
  html, body { background: #020617; color: #e2e8f0 }
  .edge-restore {
    background: rgba(148, 163, 184, 0.06);
    color: #475569;
  }
  .edge-restore:hover { background: rgba(148, 163, 184, 0.14); color: #94a3b8 }
}
</style>
