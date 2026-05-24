<template>
  <div class="auth-gate-overlay">
    <div class="auth-gate-card">
      <div class="auth-gate-icon">🔐</div>
      <h2 class="auth-gate-title">Spectra</h2>
      <p class="auth-gate-desc">请输入 Access Code 以继续</p>
      <form @submit.prevent="submitCode" class="auth-gate-form">
        <input
          ref="inputEl"
          v-model="code"
          type="password"
          placeholder="Access Code"
          class="auth-gate-input"
          :class="{ 'input-error': error }"
          autofocus
        />
        <div v-if="error" class="auth-gate-error">{{ error }}</div>
        <button type="submit" class="auth-gate-btn" :disabled="!code.trim() || loading">
          <i v-if="loading" class="fa-solid fa-spinner fa-spin"></i>
          <span v-else>验证</span>
        </button>
      </form>
      <p class="auth-gate-hint">在 .env 文件中配置 SPECTRA_ACCESS_CODE</p>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { setAccessCode, apiFetch } from '../utils/sse.js'

export default {
  name: 'AuthGate',
  setup() {
    const code = ref('')
    const error = ref('')
    const loading = ref(false)
    const inputEl = ref(null)

    onMounted(() => {
      if (inputEl.value) inputEl.value.focus()
    })

    async function submitCode() {
      if (!code.value.trim() || loading.value) return
      loading.value = true
      error.value = ''

      // 先用这个 code 做一次探测请求
      const prevCode = localStorage.getItem('spectra_access_code')
      setAccessCode(code.value.trim())

      try {
        await apiFetch('/api/conversations')
        // 成功 — 重载页面完成完整初始化
        window.location.reload()
      } catch (e) {
        localStorage.setItem('spectra_access_code', prevCode || '')
        error.value = e.message && e.message.includes('401')
          ? 'Access Code 错误，请重试'
          : '连接失败，请确认后端服务已启动'
      } finally {
        loading.value = false
      }
    }

    return { code, error, loading, inputEl, submitCode }
  }
}
</script>

<style scoped>
.auth-gate-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  z-index: 9999;
}
.auth-gate-card {
  width: 380px;
  max-width: 90vw;
  padding: 36px 32px;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.04);
  text-align: center;
}
.auth-gate-icon { font-size: 40px; margin-bottom: 12px }
.auth-gate-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 6px;
}
.auth-gate-desc {
  font-size: 13px;
  color: #64748b;
  margin: 0 0 20px;
}
.auth-gate-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.auth-gate-input {
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  transition: border-color .15s;
}
.auth-gate-input:focus { border-color: #3b82f6 }
.auth-gate-input.input-error { border-color: #ef4444 }
.auth-gate-error {
  font-size: 12px;
  color: #ef4444;
  text-align: left;
}
.auth-gate-btn {
  padding: 10px 0;
  border: none;
  border-radius: 10px;
  background: #0f172a;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background .15s;
}
.auth-gate-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.auth-gate-btn:not(:disabled):hover { background: #1e293b }
.auth-gate-hint {
  font-size: 11px;
  color: #94a3b8;
  margin: 16px 0 0;
}

@media (prefers-color-scheme: dark) {
  .auth-gate-overlay { background: #0f172a }
  .auth-gate-card { background: #1e293b; box-shadow: 0 1px 3px rgba(255,255,255,.04), 0 8px 24px rgba(255,255,255,.02) }
  .auth-gate-title { color: #f1f5f9 }
  .auth-gate-desc { color: #94a3b8 }
  .auth-gate-input { background: #0f172a; border-color: #334155; color: #e2e8f0 }
  .auth-gate-input:focus { border-color: #3b82f6 }
  .auth-gate-btn { background: #e2e8f0; color: #0f172a }
  .auth-gate-btn:not(:disabled):hover { background: #f1f5f9 }
}
</style>
