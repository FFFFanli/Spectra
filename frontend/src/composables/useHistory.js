import { store } from '../store.js'
import { apiFetch } from '../utils/sse.js'

// LocalStorage 仍保留作为离线兜底缓存：后端不可达时仍能读到上次同步的列表
const HISTORY_STORAGE_KEY = 'agent_chat_history'
const META_STORAGE_KEY = 'agent_chat_history_meta'

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

function readLocalCache() {
  try { return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || '[]') } catch (e) { return [] }
}

function writeLocalCache(list) {
  try { localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(list)) } catch (e) { /* quota exceeded */ }
}

function readMetaCache() {
  try { return JSON.parse(localStorage.getItem(META_STORAGE_KEY) || '[]') } catch (e) { return [] }
}

function writeMetaCache(list) {
  try { localStorage.setItem(META_STORAGE_KEY, JSON.stringify(list)) } catch (e) { /* quota exceeded */ }
}

// ── 网络层封装 ───────────────────────────────────────────

async function apiListConversations() {
  const res = await apiFetch('/api/conversations')
  const data = await res.json()
  return Array.isArray(data.items) ? data.items : []
}

async function apiGetConversation(id) {
  const res = await apiFetch(`/api/conversations/${encodeURIComponent(id)}`)
  const data = await res.json()
  if (data.error) throw new Error(data.error)
  return data
}

async function apiUpsertConversation(payload) {
  const res = await apiFetch(`/api/conversations/${encodeURIComponent(payload.id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      threadId: payload.threadId,
      title: payload.title,
      messages: payload.messages,
    })
  })
  return await res.json()
}

async function apiDeleteConversation(id) {
  await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

// ── 对外暴露：保持原签名，内部走 API + 本地兜底 ─────────────

export function loadAllHistory() {
  // 同步 API：仅返回当前内存里已知的元数据（来自 cache 或上一次 refresh）
  return readMetaCache()
}

/**
 * 把当前会话保存到后端。失败时仅写入本地缓存，不阻塞主流程。
 */
export async function saveCurrentConversation() {
  const msgs = store.messages
  if (!msgs || msgs.length === 0) return

  const userMsgs = msgs.filter(m => m.role === 'user')
  const title = userMsgs.length > 0
    ? (userMsgs[0].content.length > 30 ? userMsgs[0].content.slice(0, 30) + '...' : userMsgs[0].content)
    : '空对话'

  if (!store.activeHistoryId) {
    store.activeHistoryId = generateUUID()
  }

  const payload = {
    id: store.activeHistoryId,
    threadId: store.threadId,
    title,
    messages: JSON.parse(JSON.stringify(msgs)),
  }

  // 先写本地缓存（即使后端失败也不会丢失当前会话内容）
  const localList = readLocalCache().filter(c => c.id !== payload.id)
  localList.push({
    ...payload,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  })
  writeLocalCache(localList)

  try {
    await apiUpsertConversation(payload)
  } catch (e) {
    console.warn('[history] 服务端保存失败，已写入本地缓存', e)
  }
}

export function groupHistoryByDate(items) {
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterdayStart = todayStart - 86400000
  const weekStart = todayStart - 6 * 86400000
  const groups = { '今天': [], '昨天': [], '本周': [], '更早': [] }
  items.forEach(item => {
    // 服务端时间戳是秒，本地缓存是毫秒；兼容两种
    let t = item.updatedAt || item.createdAt || 0
    if (t > 0 && t < 1e12) t = t * 1000
    if (t >= todayStart) groups['今天'].push(item)
    else if (t >= yesterdayStart) groups['昨天'].push(item)
    else if (t >= weekStart) groups['本周'].push(item)
    else groups['更早'].push(item)
  })
  const result = []
  for (const [label, list] of Object.entries(groups)) {
    if (list.length > 0) {
      list.sort((a, b) => (b.updatedAt || b.createdAt || 0) - (a.updatedAt || a.createdAt || 0))
      result.push({ label, items: list })
    }
  }
  return result
}

export async function refreshHistoryGroups() {
  // 先用本地缓存渲染，避免页面切换时空白
  store.historyGroups = groupHistoryByDate(readMetaCache())
  try {
    const items = await apiListConversations()
    writeMetaCache(items)
    store.historyGroups = groupHistoryByDate(items)
  } catch (e) {
    console.warn('[history] 服务端列表拉取失败，使用本地缓存', e)
  }
}

export async function loadConversation(id) {
  // 切换会话前先把当前内容存到服务端
  if (store.messages.length > 0 && store.activeHistoryId !== id) {
    await saveCurrentConversation()
  }

  let item = null
  try {
    item = await apiGetConversation(id)
  } catch (e) {
    // 后端不可达：从本地缓存找
    const local = readLocalCache().find(c => c.id === id)
    if (local) item = local
    else {
      console.warn('[history] 加载对话失败', e)
      return
    }
  }

  store.activeHistoryId = id
  store.threadId = item.threadId || generateUUID()
  store.messages = JSON.parse(JSON.stringify(item.messages || []))
  store.charts = []
  store.files = []
  store.attachedFiles = []
  store.userInput = ''
  store.thinkingStatus = ''
  store.currentToolCalls = []
  store.taskTodos = []
  store.taskArtifacts = []
  store.taskPlan = { steps: [], revision: 0, finished: false, finishReason: '', summary: '', createdAt: 0, progress: 0 }
  store.referenceSkills = []
  store.referenceLinks = []
  store.usageStats = { by_model: {}, total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } }
  store.conversationRenderKey++
  resetRuntimeState()
  store.currentView = 'chat'
  if (store.inputArea) store.inputArea.style.height = 'auto'
  if (store.isMobile) store.leftDrawerOpen = false
  await refreshHistoryGroups()
}

export async function deleteConversation(id, event) {
  if (event) event.stopPropagation()

  // 先在本地缓存里删除，UI 即时响应
  writeLocalCache(readLocalCache().filter(c => c.id !== id))
  writeMetaCache(readMetaCache().filter(c => c.id !== id))

  if (store.activeHistoryId === id) {
    store.activeHistoryId = null
  }

  try {
    await apiDeleteConversation(id)
  } catch (e) {
    console.warn('[history] 服务端删除失败', e)
  }
  await refreshHistoryGroups()
}

export async function newChat() {
  if (store.messages.length > 0) {
    await saveCurrentConversation()
    await refreshHistoryGroups()
  }
  store.activeHistoryId = null
  store.currentView = 'chat'
  store.threadId = generateUUID()
  store.messages = []
  store.thinkingStatus = ''
  store.charts = []
  store.files = []
  store.attachedFiles = []
  store.userInput = ''
  store.currentToolCalls = []
  store.taskTodos = []
  store.taskArtifacts = []
  store.taskPlan = { steps: [], revision: 0, finished: false, finishReason: '', summary: '', createdAt: 0, progress: 0 }
  store.referenceSkills = []
  store.referenceLinks = []
  store.usageStats = { by_model: {}, total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } }
  store.conversationRenderKey++
  resetRuntimeState()
  if (store.inputArea) store.inputArea.style.height = 'auto'
  if (store.isMobile) store.leftDrawerOpen = false
}

export function resetRuntimeState() {
  store.runtimeState = {
    node: '', activeAgent: '', nextNode: '', targetAgent: '',
    selectedSkillName: '', selectedSkillCapability: '', skillAutoCreated: false,
    executionMode: '', fallbackSource: '', executionBackend: '',
  }
  store.runtimeTimeline = []
}

export function runtimeLifecycleLabel(eventName) {
  const mapping = {
    supervisor_requested_skill_creation: '请求创建新 Skill',
    supervisor_selected_skill: '确定路由目标 Skill',
    supervisor_routed_task: '完成节点路由',
    skill_auto_created: 'Skill Builder 动态生成',
    skill_reused: '检索复用现有 Skill',
    agent_executing_skill: 'Agent 执行当前 Skill',
    agent_entered_fallback: '降级为 Fallback 模式',
    execution_started: '安全沙盒执行代码',
    validation_passed: '执行结果校验通过',
    validation_failed: '校验失败，准备自修复',
  }
  return mapping[eventName] || eventName || '运行中'
}
