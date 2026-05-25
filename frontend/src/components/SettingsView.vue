<template>
  <div class="settings-view">
    <div class="settings-header">
      <h2 class="settings-title">⚙️ 系统设置</h2>
    </div>

    <!-- 标签切换 -->
    <div class="settings-tabs">
      <button :class="['tab-btn', { active: activeTab === 'api' }]" @click="activeTab = 'api'">
        <i class="fa-solid fa-key"></i> API 密钥
      </button>
      <button :class="['tab-btn', { active: activeTab === 'personas' }]" @click="activeTab = 'personas'">
        <i class="fa-solid fa-user-astronaut"></i> 助手配置
      </button>
      <button :class="['tab-btn', { active: activeTab === 'prefs' }]" @click="activeTab = 'prefs'">
        <i class="fa-solid fa-sliders"></i> 偏好设置
      </button>
      <button :class="['tab-btn', { active: activeTab === 'team' }]" @click="activeTab = 'team'">
        <i class="fa-solid fa-people-group"></i> Agent 团队
      </button>
    </div>

    <!-- API 密钥 Tab -->
    <div v-if="activeTab === 'api'" class="settings-card">
      <div class="form-group">
        <label class="form-label">DASHSCOPE API Key (通义千问)</label>
        <input v-model="$store.apiKeys.dashscope" class="form-input" type="password" :placeholder="dashscopePlaceholder" />
        <span class="form-hint">从阿里云 DashScope 控制台获取</span>
      </div>
      <div class="form-group">
        <label class="form-label">OpenAI API Key</label>
        <input v-model="$store.apiKeys.openai" class="form-input" type="password" :placeholder="openaiPlaceholder" />
        <span class="form-hint">从 OpenAI Platform 获取</span>
      </div>
      <div class="form-group">
        <label class="form-label">DeepSeek API Key</label>
        <input v-model="$store.apiKeys.deepseek" class="form-input" type="password" :placeholder="deepseekPlaceholder" />
        <span class="form-hint">从 DeepSeek 开放平台获取</span>
      </div>
      <div class="form-group">
        <label class="form-label">默认模型</label>
        <select v-model="$store.apiKeys.selectedModel" class="form-select">
          <option v-for="m in $store.models" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>
      </div>
      <div v-if="$store.settingsSaved" class="save-success">✅ 设置已保存</div>
      <div v-if="$store.settingsError" class="save-error">❌ {{ $store.settingsError }}</div>
      <button @click="saveSettings" class="save-btn" :disabled="$store.settingsSaving">
        <i class="fa-solid fa-floppy-disk"></i>
        {{ $store.settingsSaving ? '保存中...' : '保存设置' }}
      </button>
    </div>

    <!-- 助手配置 Tab -->
    <div v-if="activeTab === 'personas'" class="settings-card">
      <div class="persona-header">
        <h3 class="section-title">🤖 自定义助手角色</h3>
        <span class="form-hint">创建不同的 AI 角色，在对话中切换使用</span>
      </div>

      <div v-if="$store.personas.length === 0 && !showPersonaForm" class="prefs-empty">
        暂无自定义角色。点击下方按钮创建第一个角色。
      </div>

      <div v-for="(p, idx) in $store.personas" :key="p.id" class="persona-item">
        <template v-if="editingPersonaId === p.id">
          <div class="persona-edit">
            <input v-model="editName" class="form-input" placeholder="角色名称" />
            <textarea v-model="editPrompt" class="form-textarea" rows="4" placeholder="系统提示词，如：你是一个专业的数据分析师，擅长用图表展示结论..."></textarea>
            <div class="persona-actions">
              <button @click="savePersonaEdit(p.id)" class="save-btn small">保存</button>
              <button @click="cancelPersonaEdit()" class="cancel-btn">取消</button>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="persona-info">
            <div class="persona-name">
              <span :class="['persona-active-dot', { active: $store.selectedPersonaId === p.id }]"></span>
              {{ p.name }}
            </div>
            <div class="persona-prompt-preview">{{ p.systemPrompt.slice(0, 80) }}{{ p.systemPrompt.length > 80 ? '...' : '' }}</div>
          </div>
          <div class="persona-actions">
            <button v-if="$store.selectedPersonaId !== p.id" @click="selectPersona(p.id)" class="icon-btn" title="启用此角色">
              <i class="fa-solid fa-check"></i>
            </button>
            <button v-else @click="deselectPersona()" class="icon-btn active" title="取消使用">
              <i class="fa-solid fa-check-double"></i>
            </button>
            <button @click="startEditPersona(p)" class="icon-btn" title="编辑">
              <i class="fa-solid fa-pen-to-square"></i>
            </button>
            <button @click="deletePersona(idx)" class="icon-btn danger" title="删除">
              <i class="fa-solid fa-trash"></i>
            </button>
          </div>
        </template>
      </div>

      <div v-if="showPersonaForm" class="persona-edit">
        <input v-model="newName" class="form-input" placeholder="角色名称，如：数据分析师" />
        <textarea v-model="newPrompt" class="form-textarea" rows="5" placeholder="系统提示词，定义角色的能力和风格。例如：&#10;你是一个资深数据分析师，擅长用 Python 处理数据并生成可视化图表。回答问题时优先使用量化分析，并总是给出数据来源和置信度。"></textarea>
        <div class="persona-actions">
          <button @click="createPersona" class="save-btn small" :disabled="!newName.trim() || !newPrompt.trim()">创建角色</button>
          <button @click="showPersonaForm = false" class="cancel-btn">取消</button>
        </div>
      </div>

      <button v-if="!showPersonaForm" @click="showPersonaForm = true" class="save-btn secondary">
        <i class="fa-solid fa-plus"></i> 新建角色
      </button>
    </div>

    <!-- 偏好设置 Tab -->
    <div v-if="activeTab === 'prefs'" class="prefs-card">
      <h3 class="section-title">📝 用户偏好 (Agent 记忆)</h3>
      <p class="form-hint" style="margin-bottom:12px">以下偏好会在对话中自动应用，帮助 Agent 更好地理解你</p>
      <div v-if="Object.keys($store.userPreferences.preferences).length === 0" class="prefs-empty">
        暂无偏好设置。在对话中告诉 Agent 你的喜好（如"我更喜欢饼图"），Agent 会自动记住。
      </div>
      <div v-else class="prefs-list">
        <div v-for="(value, key) in $store.userPreferences.preferences" :key="key" class="pref-item">
          <span class="pref-key">{{ key }}</span>
          <span class="pref-value">{{ value }}</span>
          <button @click="removePreference(key)" class="pref-remove"><i class="fa-solid fa-xmark"></i></button>
        </div>
      </div>
    </div>

    <!-- Agent 团队 Tab -->
    <div v-if="activeTab === 'team'" class="prefs-card">
      <h3 class="section-title">Agent 工作模式</h3>
      <p class="form-hint" style="margin-bottom:16px">选择单一 Agent 独立工作或多 Agent 团队协作。切换后立即生效。</p>
      <div class="mode-cards">
        <div
          :class="['mode-card', { active: $store.agentMode === 'solo' }]"
          @click="setAgentMode('solo')"
        >
          <div class="mode-card-header">
            <i class="fa-solid fa-user"></i>
            <span class="mode-card-title">Solo 模式</span>
            <i v-if="$store.agentMode === 'solo'" class="fa-solid fa-circle-check mode-check"></i>
          </div>
          <p class="mode-card-desc">单一 Agent 独立执行任务。响应快，适合简单对话、问答、翻译等场景。</p>
        </div>
        <div
          :class="['mode-card', { active: $store.agentMode === 'team' }]"
          @click="setAgentMode('team')"
        >
          <div class="mode-card-header">
            <i class="fa-solid fa-people-group"></i>
            <span class="mode-card-title">Team 模式</span>
            <i v-if="$store.agentMode === 'team'" class="fa-solid fa-circle-check mode-check"></i>
          </div>
          <p class="mode-card-desc">Supervisor 协调多个专业 Agent (Coder/Researcher/Writer/Responder) 协作完成复杂任务。适合深度分析、多步骤报告等场景。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { store } from '../store.js'
import { saveSettings, loadPersonas, savePersonas, generatePersonaId } from '../composables/useSettings.js'
import { saveUserPreferences } from '../composables/usePreferences.js'
import { maskKey } from '../utils/crypto.js'

export default {
  name: 'SettingsView',
  setup() {
    const activeTab = ref('api')
    const showPersonaForm = ref(false)
    const newName = ref('')
    const newPrompt = ref('')
    const editingPersonaId = ref(null)
    const editName = ref('')
    const editPrompt = ref('')

    loadPersonas()

    const dashscopePlaceholder = computed(() =>
      store.apiKeys.dashscope ? '已保存: ' + maskKey(store.apiKeys.dashscope) : 'sk-...'
    )
    const openaiPlaceholder = computed(() =>
      store.apiKeys.openai ? '已保存: ' + maskKey(store.apiKeys.openai) : 'sk-...'
    )
    const deepseekPlaceholder = computed(() =>
      store.apiKeys.deepseek ? '已保存: ' + maskKey(store.apiKeys.deepseek) : 'sk-...'
    )

    function createPersona() {
      if (!newName.value.trim() || !newPrompt.value.trim()) return
      store.personas.push({
        id: generatePersonaId(),
        name: newName.value.trim(),
        systemPrompt: newPrompt.value.trim(),
        createdAt: Date.now(),
      })
      savePersonas()
      newName.value = ''
      newPrompt.value = ''
      showPersonaForm.value = false
    }

    function startEditPersona(persona) {
      editingPersonaId.value = persona.id
      editName.value = persona.name
      editPrompt.value = persona.systemPrompt
    }

    function savePersonaEdit(id) {
      const p = store.personas.find(x => x.id === id)
      if (p) {
        p.name = editName.value.trim()
        p.systemPrompt = editPrompt.value.trim()
        savePersonas()
      }
      editingPersonaId.value = null
    }

    function cancelPersonaEdit() {
      editingPersonaId.value = null
    }

    function deletePersona(idx) {
      const p = store.personas[idx]
      if (store.selectedPersonaId === p.id) {
        store.selectedPersonaId = null
      }
      store.personas.splice(idx, 1)
      savePersonas()
    }

    function selectPersona(id) {
      store.selectedPersonaId = id
    }

    function deselectPersona() {
      store.selectedPersonaId = null
    }

    function removePreference(key) {
      delete store.userPreferences.preferences[key]
      saveUserPreferences()
    }

    function setAgentMode(mode) {
      store.agentMode = mode
      localStorage.setItem('spectra_agent_mode', mode)
    }

    return {
      $store: store, activeTab, showPersonaForm, newName, newPrompt,
      editingPersonaId, editName, editPrompt,
      saveSettings, createPersona, startEditPersona, savePersonaEdit,
      cancelPersonaEdit, deletePersona, selectPersona, deselectPersona,
      removePreference, setAgentMode, dashscopePlaceholder, openaiPlaceholder, deepseekPlaceholder,
    }
  }
}
</script>

<style scoped>
.settings-view {
  flex: 1; height: 100vh; overflow-y: auto; padding: 24px;
  background: #fff;
}
.settings-header { margin-bottom: 16px }
.settings-title { font-size: 22px; font-weight: 700; color: #1e293b }

/* Tabs */
.settings-tabs {
  display: flex; gap: 4px; margin-bottom: 20px;
  border-bottom: 2px solid #e2e8f0; padding-bottom: 0;
}
.tab-btn {
  padding: 10px 18px; border: none; background: none; font-size: 13px;
  font-weight: 500; color: #64748b; cursor: pointer; border-bottom: 2px solid transparent;
  margin-bottom: -2px; transition: all 0.15s; font-family: inherit;
}
.tab-btn:hover { color: #334155 }
.tab-btn.active { color: #3b82f6; border-bottom-color: #3b82f6 }
.tab-btn i { margin-right: 6px }

.settings-card, .prefs-card {
  max-width: 560px; padding: 24px; border: 1px solid #e2e8f0;
  border-radius: 14px; background: #f8fafc; display: flex; flex-direction: column; gap: 16px;
  margin-bottom: 20px;
}
.section-title { font-size: 15px; font-weight: 600; color: #1e293b }
.form-group { display: flex; flex-direction: column; gap: 6px }
.form-label { font-size: 13px; font-weight: 600; color: #475569 }
.form-input, .form-select {
  padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 10px;
  font-size: 14px; background: #fff; color: #1e293b; outline: none;
  font-family: inherit; transition: border-color 0.15s;
}
.form-input:focus, .form-select:focus { border-color: #3b82f6 }
.form-textarea {
  padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 10px;
  font-size: 13px; background: #fff; color: #1e293b; outline: none;
  font-family: inherit; resize: vertical; transition: border-color 0.15s;
}
.form-textarea:focus { border-color: #3b82f6 }
.form-hint { font-size: 11px; color: #94a3b8 }
.save-success { font-size: 13px; color: #16a34a; padding: 4px 0 }
.save-error { font-size: 13px; color: #dc2626; padding: 4px 0 }
.save-btn {
  padding: 12px 24px; background: #3b82f6; color: #fff; border: none;
  border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 600;
  transition: all 0.15s; align-self: flex-start; font-family: inherit;
}
.save-btn:hover { background: #2563eb }
.save-btn:disabled { background: #94a3b8; cursor: not-allowed }
.save-btn.small { padding: 8px 16px; font-size: 13px }
.save-btn.secondary { background: #e2e8f0; color: #475569; align-self: stretch; text-align: center; display: flex; align-items: center; justify-content: center; gap: 6px }
.save-btn.secondary:hover { background: #cbd5e1 }
.cancel-btn {
  padding: 8px 16px; background: none; border: 1px solid #e2e8f0; border-radius: 10px;
  color: #64748b; cursor: pointer; font-size: 13px; font-family: inherit;
}
.cancel-btn:hover { background: #f1f5f9 }

/* Persona */
.persona-header { margin-bottom: 4px }
.persona-item {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
}
.persona-info { flex: 1; min-width: 0 }
.persona-name { font-size: 14px; font-weight: 600; color: #1e293b; display: flex; align-items: center; gap: 6px }
.persona-active-dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; flex-shrink: 0 }
.persona-active-dot.active { background: #22c55e }
.persona-prompt-preview { font-size: 12px; color: #94a3b8; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.persona-edit { display: flex; flex-direction: column; gap: 10px; width: 100% }
.persona-actions { display: flex; gap: 6px; align-items: center; flex-shrink: 0 }
.icon-btn {
  width: 30px; height: 30px; border: 1px solid #e2e8f0; border-radius: 8px;
  background: #fff; color: #64748b; cursor: pointer; display: flex;
  align-items: center; justify-content: center; font-size: 12px; transition: all 0.15s;
}
.icon-btn:hover { background: #f1f5f9; color: #334155 }
.icon-btn.active { background: #dbeafe; color: #3b82f6; border-color: #3b82f6 }
.icon-btn.danger:hover { background: #fef2f2; color: #ef4444; border-color: #fca5a5 }

.prefs-empty { font-size: 13px; color: #94a3b8; padding: 8px 0 }
.prefs-list { display: flex; flex-direction: column; gap: 8px }
.pref-item {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  background: #e2e8f0; border-radius: 8px; font-size: 13px;
}
.pref-key { color: #64748b; font-weight: 500 }
.pref-value { color: #1e293b; flex: 1 }
.pref-remove { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 11px }
.pref-remove:hover { color: #ef4444 }

.mode-cards { display: flex; flex-direction: column; gap: 12px }
.mode-card {
  padding: 16px; border: 2px solid #e2e8f0; border-radius: 12px; cursor: pointer;
  transition: all 0.15s; background: #fff;
}
.mode-card:hover { border-color: #cbd5e1 }
.mode-card.active { border-color: #3b82f6; background: #eff6ff }
.mode-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 15px; font-weight: 600; color: #1e293b }
.mode-card-header i:first-child { font-size: 18px; color: #64748b }
.mode-card.active .mode-card-header i:first-child { color: #3b82f6 }
.mode-check { margin-left: auto; color: #3b82f6; font-size: 18px }
.mode-card-desc { font-size: 13px; color: #64748b; line-height: 1.6 }

@media (prefers-color-scheme: dark) {
  .settings-view { background: #0f172a }
  .settings-title { color: #e2e8f0 }
  .settings-tabs { border-bottom-color: #334155 }
  .tab-btn { color: #64748b }
  .tab-btn:hover { color: #94a3b8 }
  .tab-btn.active { color: #60a5fa; border-bottom-color: #60a5fa }
  .settings-card, .prefs-card { background: #1e293b; border-color: #334155 }
  .section-title { color: #e2e8f0 }
  .form-label { color: #94a3b8 }
  .form-input, .form-select, .form-textarea { background: #0f172a; border-color: #334155; color: #e2e8f0 }
  .pref-item { background: #334155 }
  .pref-value { color: #e2e8f0 }
  .persona-item { background: #0f172a; border-color: #334155 }
  .persona-name { color: #e2e8f0 }
  .icon-btn { background: #1e293b; border-color: #334155; color: #64748b }
  .save-btn.secondary { background: #334155; color: #94a3b8 }
  .save-btn.secondary:hover { background: #475569 }
  .cancel-btn { color: #94a3b8 }
  .cancel-btn:hover { background: #1e293b }
  .mode-card { background: #0f172a; border-color: #334155 }
  .mode-card:hover { border-color: #475569 }
  .mode-card.active { border-color: #3b82f6; background: #1e3a5f }
  .mode-card-header { color: #e2e8f0 }
  .mode-card-desc { color: #94a3b8 }
}
</style>
