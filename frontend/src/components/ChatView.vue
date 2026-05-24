<template>
  <div class="chat-view">
    <div class="chat-header">
      <div class="header-left">
        <button v-if="$store.isMobile" @click="$store.leftDrawerOpen = true" class="mobile-menu-btn">
          <i class="fa-solid fa-bars"></i>
        </button>
        <div v-if="$store.currentWorkflow" class="workflow-badge">
          <i class="fa-solid fa-diagram-project"></i>
          <span>{{ $store.currentWorkflow }}</span>
          <button @click="clearWorkflow" class="workflow-clear"><i class="fa-solid fa-xmark"></i></button>
        </div>
      </div>
    </div>
    <div class="chat-messages" id="chat-container">
      <template v-for="(msg, idx) in $store.messages" :key="$store.conversationRenderKey + '-' + idx">
        <ChatMessage
          :msg="msg"
          :msg-index="idx"
          :thinking="idx === $store.messages.length - 1 ? $store.thinkingStatus : ''"
          :streaming="$store.loading && msg.role === 'assistant' && idx === $store.messages.length - 1"
        />
      </template>
      <div v-if="$store.messages.length === 0" class="empty-chat">
        <div class="empty-icon">✦</div>
        <h3 class="empty-title">开始对话</h3>
        <p class="empty-desc">向 Spectra 提问，我会调用工具来帮助你</p>
      </div>
      <div v-if="$store.loading && $store.messages.length === 0" class="loading-indicator">
        <div class="dots-loader">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>
    <div class="chat-input-area">
      <div v-if="$store.attachedFiles.length > 0" class="attached-files">
        <div v-for="(f, i) in $store.attachedFiles" :key="i" class="attached-file-chip">
          <i class="fa-solid fa-file"></i>
          <span>{{ f.name }}</span>
          <button @click="removeFile(i)" class="remove-file-chip"><i class="fa-solid fa-xmark"></i></button>
        </div>
      </div>
      <div v-if="$store.uploadStatus" :class="['upload-status', { error: $store.uploadError }]">
        {{ $store.uploadStatus }}
      </div>
      <div class="input-shell">
        <div class="input-controls">
<label class="model-select-label">
            <select v-model="$store.apiKeys.selectedModel" @change="saveSettingsSilent" class="model-select">
              <option v-for="m in $store.models" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
          </label>
          <label v-if="$store.personas.length > 0" class="persona-select-label" title="选择助手角色">
            <select v-model="$store.selectedPersonaId" class="persona-select">
              <option :value="null">🧑 默认</option>
              <option v-for="p in $store.personas" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
        </div>
        <div class="input-row">
          <label class="upload-btn" title="上传文件">
            <i class="fa-solid fa-paperclip"></i>
            <input type="file" @change="handleFileUpload" hidden>
          </label>
          <textarea
            ref="inputEl"
            v-model="$store.userInput"
            class="chat-textarea"
            placeholder="输入消息..."
            rows="1"
            @keydown.enter.exact.prevent="onEnterKey"
            @input="resizeTextarea"
            :disabled="$store.loading"
          ></textarea>
          <button v-if="$store.loading" @click="handleStop" class="stop-btn" title="停止">
            <i class="fa-solid fa-stop"></i>
          </button>
          <button v-else @click="handlePrimarySend" class="send-btn" :disabled="!$store.userInput.trim()" title="发送">
            <i class="fa-solid fa-paper-plane"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { store } from '../store.js'
import ChatMessage from './ChatMessage.vue'
import {
  handlePrimarySend, handleStop, handleFileUpload, removeFile,
  resizeTextarea, clearWorkflow
} from '../composables/useChat.js'
import { saveSettings } from '../composables/useSettings.js'

export default {
  name: 'ChatView',
  components: { ChatMessage },
  setup() {
    const inputEl = ref(null)

    onMounted(() => {
      store.inputArea = inputEl.value
    })

    function saveSettingsSilent() {
      localStorage.setItem('selected_model', store.apiKeys.selectedModel)
      saveSettings(true)
    }

    function onEnterKey(e) {
      if (e.isComposing || e.keyCode === 229) return
      handlePrimarySend()
    }

    return {
      $store: store,
      inputEl,
      handlePrimarySend,
      handleStop,
      handleFileUpload,
      removeFile,
      resizeTextarea,
      clearWorkflow,
      saveSettingsSilent,
      onEnterKey,
    }
  }
}
</script>

<style scoped>
.chat-view {
  flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden;
  background: #ffffff;
}
.chat-header {
  padding: 10px 16px; border-bottom: 1px solid #f1f5f9;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  flex-shrink: 0;
  background: #ffffff;
}
.header-left { display: flex; align-items: center; gap: 8px }
.mobile-menu-btn {
  display: none; background: none; border: none; color: #475569;
  cursor: pointer; font-size: 18px;
}
.mode-selector { display: flex; border-radius: 14px; overflow: hidden; border: 1px solid #f1f5f9; background: #fafafa; gap: 0 }
.mode-btn {
  padding: 2px 9px; border: none; background: transparent; color: #94a3b8;
  cursor: pointer; font-size: 11px; transition: all 0.15s; font-weight: 500;
  white-space: nowrap; line-height: 1.8;
}
.mode-btn.active { background: #ffffff; color: #1e293b; box-shadow: 0 1px 3px rgba(0,0,0,0.06) }
.mode-btn:hover:not(.active) { color: #475569 }
.workflow-badge {
  display: flex; align-items: center; gap: 6px; padding: 4px 10px;
  background: #dbeafe; border-radius: 8px; font-size: 12px; color: #1d4ed8;
}
.workflow-clear { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 11px }
.model-select {
  padding: 3px 8px; border-radius: 14px; border: 1px solid #f1f5f9;
  font-size: 11px; background: #fafafa; color: #475569; font-weight: 500;
  cursor: pointer; outline: none;
  min-width: 90px;
}
.model-select:focus { border-color: #cbd5e1 }
.persona-select {
  padding: 3px 8px; border-radius: 14px; border: 1px solid #f1f5f9;
  font-size: 11px; background: #fafafa; color: #8b5cf6; font-weight: 500;
  cursor: pointer; outline: none;
  min-width: 70px; max-width: 110px;
}
.persona-select:focus { border-color: #c4b5fd }
.chat-messages {
  flex: 1; overflow-y: auto; padding: 16px 24px;
  display: flex; flex-direction: column; gap: 4px;
  background: #ffffff;
}
.empty-chat { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
.empty-icon { font-size: 48px; color: #94a3b8 }
.empty-title { font-size: 20px; font-weight: 600; color: #1e293b }
.empty-desc { color: #64748b; font-size: 14px }
.loading-indicator { display: flex; justify-content: center; padding: 24px }
.dots-loader { display: flex; gap: 6px }
.dots-loader span { width: 8px; height: 8px; border-radius: 50%; background: #3b82f6; animation: dot-bounce 1.3s infinite }
.dots-loader span:nth-child(2) { animation-delay: 0.15s }
.dots-loader span:nth-child(3) { animation-delay: 0.3s }
@keyframes dot-bounce {
  0%, 100% { opacity: 0.3; transform: translateY(0) }
  50% { opacity: 1; transform: translateY(-6px) }
}
.chat-input-area {
  padding: 12px 16px 18px;
  border-top: 1px solid #f1f5f9;
  background: #ffffff;
  flex-shrink: 0;
}
.chat-input-area > * {
  width: min(760px, 100%);
  margin-left: auto;
  margin-right: auto;
}
.attached-files { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px }
.attached-file-chip {
  display: flex; align-items: center; gap: 4px; padding: 3px 10px;
  background: #e2e8f0; border-radius: 8px; font-size: 12px; color: #475569;
}
.remove-file-chip { background: none; border: none; color: #64748b; cursor: pointer; font-size: 10px }
.upload-status { font-size: 12px; color: #475569; margin-bottom: 4px }
.upload-status.error { color: #ef4444 }
.input-shell {
  border: 1px solid #f1f5f9;
  background: #ffffff;
  border-radius: 22px;
  padding: 10px 12px 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.03);
}
.input-controls {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 10px;
}
.input-row { display: flex; align-items: flex-end; gap: 8px }
.upload-btn {
  width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; cursor: pointer; border-radius: 10px; transition: all 0.15s;
}
.upload-btn:hover { background: #f1f5f9; color: #475569 }
.chat-textarea {
  flex: 1; padding: 12px 14px; border: 1px solid #f1f5f9; border-radius: 18px;
  font-size: 14px; resize: none; outline: none; background: #f8fafc; color: #0f172a;
  transition: border-color 0.15s, box-shadow 0.15s; max-height: 200px; font-family: inherit;
  box-shadow: none;
}
.chat-textarea:focus { border-color: #cbd5e1; box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.1) }
.send-btn, .stop-btn {
  width: 36px; height: 36px; border-radius: 14px; border: none;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; font-size: 14px; transition: all 0.15s;
}
.send-btn { background: #3b82f6; color: #fff }
.send-btn:hover { background: #2563eb }
.send-btn:disabled { background: #94a3b8; cursor: not-allowed }
.stop-btn { background: #ef4444; color: #fff }
.stop-btn:hover { background: #dc2626 }
@media (max-width: 1023px) {
  .mobile-menu-btn { display: block }
  .chat-messages { padding: 12px 8px }
  .input-controls { flex-direction: column; align-items: stretch }
}
@media (prefers-color-scheme: dark) {
  .chat-view { background: #0f172a }
  .chat-header { border-color: #1e293b; background: #0f172a }
  .mode-selector { border-color: #1e293b; background: #1e293b }
  .mode-btn { color: #64748b }
  .mode-btn.active { background: #334155; color: #e2e8f0; box-shadow: none }
  .mode-btn:hover:not(.active) { color: #94a3b8 }
  .model-select { border-color: #334155; background: #1e293b; color: #e2e8f0 }
  .persona-select { border-color: #334155; background: #1e293b; color: #a78bfa }
  .chat-messages { color: #e2e8f0; background: #0f172a }
  .empty-title { color: #e2e8f0 }
  .empty-desc { color: #64748b }
  .chat-input-area { border-color: #1e293b; background: #0f172a }
  .input-shell { border-color: #1e293b; background: #1e293b }
  .chat-textarea { border-color: #334155; background: #0f172a; color: #e2e8f0 }
  .chat-textarea:focus { border-color: #475569; box-shadow: 0 0 0 3px rgba(71, 85, 105, 0.18) }
  .workflow-badge { background: #1e3a5f; color: #60a5fa }
  .upload-btn { color: #64748b }
  .upload-btn:hover { background: #334155; color: #94a3b8 }
  .attached-file-chip { background: #1e293b; color: #94a3b8 }
  .send-btn:disabled { background: #475569 }
}
</style>
