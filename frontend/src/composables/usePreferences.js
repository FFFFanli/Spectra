import { store } from '../store.js'

const PREFS_KEY = 'agent_user_preferences'

export function loadUserPreferences() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (raw) {
      store.userPreferences = JSON.parse(raw)
    }
  } catch (e) {
    store.userPreferences = {
      preferredChartType: null,
      language: 'zh-CN',
      preferences: {}
    }
  }
}

export function saveUserPreferences() {
  localStorage.setItem(PREFS_KEY, JSON.stringify(store.userPreferences))
}

export function setPreference(key, value) {
  store.userPreferences.preferences[key] = value
  saveUserPreferences()
}

export function injectPreferences(systemPrompt) {
  const prefs = store.userPreferences.preferences
  if (!prefs || Object.keys(prefs).length === 0) return systemPrompt

  const lines = []
  for (const [key, value] of Object.entries(prefs)) {
    lines.push(`- ${key}: ${value}`)
  }
  const prefsBlock = `\n\n【用户偏好】\n用户已保存以下偏好设置，请在回复时优先考虑：\n${lines.join('\n')}\n`
  return systemPrompt + prefsBlock
}

export function rememberUserPreference(text) {
  const patterns = {
    preferredChartType: /我(比较|更|最)?喜欢(用|使用)?(\S*图)/,
    'language_pref': /我喜欢用(中文|英文|日文)/,
    'style_pref': /我喜欢(简洁|详细|幽默|专业)的/,
  }

  for (const [key, pattern] of Object.entries(patterns)) {
    const match = text.match(pattern)
    if (match) {
      if (key === 'preferredChartType') {
        store.userPreferences.preferences['图表类型偏好'] = match[3]
      }
      saveUserPreferences()
      return
    }
  }
}
