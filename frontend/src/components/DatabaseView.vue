<template>
  <div class="database-view">
    <div class="db-header">
      <h2 class="db-title">🗄️ 数据库连接</h2>
      <p class="db-subtitle">连接外部数据库，让 AI 直接查询和分析数据</p>
    </div>
    <div class="db-card">
      <div class="form-group">
        <label class="form-label">数据库类型</label>
        <select v-model="$store.dbConfig.type" class="form-select">
          <option value="mysql">MySQL</option>
          <option value="postgresql">PostgreSQL</option>
          <option value="sqlite">SQLite</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">连接字符串</label>
        <input v-model="$store.dbConfig.connectionString" class="form-input"
          placeholder="mysql://user:pass@host:3306/dbname" />
      </div>
      <div class="form-group">
        <label class="form-label">数据库别名</label>
        <input v-model="$store.dbConfig.alias" class="form-input"
          placeholder="例如: my_project_db" />
      </div>
      <div v-if="$store.uploadStatus" :class="['upload-status', { error: $store.uploadError }]">
        {{ $store.uploadStatus }}
      </div>
      <button @click="connectDatabase" class="connect-btn" :disabled="$store.loading">
        <i class="fa-solid fa-plug"></i> 连接数据库
      </button>
    </div>
  </div>
</template>

<script>
import { store } from '../store.js'
import { connectDatabase } from '../composables/useChat.js'

export default {
  name: 'DatabaseView',
  setup() {
    return { $store: store, connectDatabase }
  }
}
</script>

<style scoped>
.database-view {
  flex: 1; height: 100vh; overflow-y: auto; padding: 24px;
  background: #fff;
}
.db-header { margin-bottom: 24px }
.db-title { font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 4px }
.db-subtitle { font-size: 13px; color: #94a3b8 }
.db-card {
  max-width: 520px; padding: 24px; border: 1px solid #e2e8f0;
  border-radius: 14px; background: #f8fafc; display: flex; flex-direction: column; gap: 16px;
}
.form-group { display: flex; flex-direction: column; gap: 6px }
.form-label { font-size: 13px; font-weight: 600; color: #475569 }
.form-input, .form-select {
  padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 10px;
  font-size: 14px; background: #fff; color: #1e293b; outline: none;
  font-family: inherit; transition: border-color 0.15s;
}
.form-input:focus, .form-select:focus { border-color: #3b82f6 }
.upload-status { font-size: 12px; color: #22c55e }
.upload-status.error { color: #ef4444 }
.connect-btn {
  padding: 12px 24px; background: #3b82f6; color: #fff; border: none;
  border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 600;
  transition: all 0.15s; align-self: flex-start;
}
.connect-btn:hover { background: #2563eb }
.connect-btn:disabled { background: #94a3b8; cursor: not-allowed }
@media (prefers-color-scheme: dark) {
  .database-view { background: #0f172a }
  .db-title { color: #e2e8f0 }
  .db-card { background: #1e293b; border-color: #334155 }
  .form-label { color: #94a3b8 }
  .form-input, .form-select { background: #0f172a; border-color: #334155; color: #e2e8f0 }
}
</style>
