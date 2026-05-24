import { store } from '../store.js'
import { encrypt, decrypt } from '../utils/crypto.js'
import { apiFetch } from '../utils/sse.js'

const KEY_PREFIX = 'ENC:'

function isEncryptedBlob(value) {
  if (!value) return false
  return value.startsWith(KEY_PREFIX)
}

export async function saveSettings(silent = false) {
  if (!silent) {
    store.settingsSaving = true
    store.settingsSaved = false
    store.settingsError = ''
  }

  const dashscopeEnc = store.apiKeys.dashscope ? KEY_PREFIX + await encrypt(store.apiKeys.dashscope) : ''
  const openaiEnc = store.apiKeys.openai ? KEY_PREFIX + await encrypt(store.apiKeys.openai) : ''
  const deepseekEnc = store.apiKeys.deepseek ? KEY_PREFIX + await encrypt(store.apiKeys.deepseek) : ''

  localStorage.setItem('dashscope_key', dashscopeEnc)
  localStorage.setItem('openai_key', openaiEnc)
  localStorage.setItem('deepseek_key', deepseekEnc)
  localStorage.setItem('selected_model', store.apiKeys.selectedModel)

  try {
    await apiFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dashscope_key: store.apiKeys.dashscope,
        openai_key: store.apiKeys.openai,
        deepseek_key: store.apiKeys.deepseek,
        selected_model: store.apiKeys.selectedModel
      })
    })
    if (!silent) {
      store.settingsSaved = true
      setTimeout(() => { store.settingsSaved = false }, 4000)
    }
  } catch (e) {
    if (!silent) {
      store.settingsError = '网络连接失败，请检查服务是否启动'
      setTimeout(() => { store.settingsError = '' }, 4000)
    }
  } finally {
    if (!silent) {
      store.settingsSaving = false
    }
  }
}

function maybeUpgradeOldPlaintext(keyName) {
  const raw = localStorage.getItem(keyName)
  if (!raw || isEncryptedBlob(raw)) return raw
  encrypt(raw).then(enc => {
    localStorage.setItem(keyName, KEY_PREFIX + enc)
  })
  return raw
}

async function loadKey(name) {
  let raw = localStorage.getItem(name)
  if (!raw) return ''
  if (!isEncryptedBlob(raw)) {
    return maybeUpgradeOldPlaintext(name) || raw
  }
  const decrypted = await decrypt(raw.slice(KEY_PREFIX.length))
  return decrypted
}

export async function loadSettingsFromStorage() {
  const [dashscope, openai, deepseek] = await Promise.all([
    loadKey('dashscope_key'),
    loadKey('openai_key'),
    loadKey('deepseek_key'),
  ])
  store.apiKeys.dashscope = dashscope
  store.apiKeys.openai = openai
  store.apiKeys.deepseek = deepseek
  store.apiKeys.selectedModel = localStorage.getItem('selected_model') || 'qwen3.5-plus'
  saveSettings(true)
}

export function syncViewport() {
  store.isMobile = window.innerWidth < 1024
  if (!store.isMobile) store.leftDrawerOpen = false
}

export function loadPersonas() {
  try {
    const raw = localStorage.getItem('spectra_personas')
    if (raw) {
      store.personas = JSON.parse(raw)
    }
  } catch (e) {
    store.personas = []
  }
}

export function savePersonas() {
  localStorage.setItem('spectra_personas', JSON.stringify(store.personas))
}

export function generatePersonaId() {
  return 'persona_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
}

export async function fetchModels() {
  try {
    const res = await apiFetch('/api/models')
    const data = await res.json()
    if (data.models && data.models.length > 0) {
      store.models = data.models
      // 如果当前选中的模型不在可用列表中，回退到第一个
      if (!store.models.find(m => m.id === store.apiKeys.selectedModel)) {
        store.apiKeys.selectedModel = data.models[0].id
      }
    }
  } catch (e) {
    console.warn('获取模型列表失败，使用默认', e)
  }
}
