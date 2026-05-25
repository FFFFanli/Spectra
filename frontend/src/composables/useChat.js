import { nextTick } from 'vue'
import { store } from '../store.js'
import { parseSSEStream, streamFetch, apiFetch, getAccessCode } from '../utils/sse.js'
import { saveCurrentConversation, refreshHistoryGroups } from './useHistory.js'
import { loadUserPreferences, injectPreferences, rememberUserPreference } from './usePreferences.js'

export function scrollToBottom() {
  nextTick(() => {
    const container = document.getElementById('chat-container')
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
    }
  })
}

let todoSeq = 0
let pendingProcessBlock = null

function createEmptyTaskPlan() {
  return {
    steps: [],
    revision: 0,
    finished: false,
    finishReason: '',
    summary: '',
    createdAt: 0,
    progress: 0
  }
}

function ensureTaskPlan() {
  if (!store.taskPlan || !Array.isArray(store.taskPlan.steps)) {
    store.taskPlan = createEmptyTaskPlan()
  }
  return store.taskPlan
}

function extractLinks(text) {
  if (!text || typeof text !== 'string') return []
  const urlRegex = /https?:\/\/[^\s<>"{}|\\^`\[\]]+/g
  const matches = text.match(urlRegex) || []
  return [...new Set(matches)]
}

function addTodo(text, agent) {
  todoSeq++
  const existing = store.taskTodos.find(t => t.status === 'running')
  if (existing) {
    existing.status = 'done'
  }
  store.taskTodos.push({
    id: 'td-' + todoSeq,
    text: (agent && !text.startsWith(agent) ? `[${agent}] ` : '') + text,
    status: 'running',
    agent: agent || ''
  })
}

function markTodoDone(text) {
  const match = store.taskTodos.find(t => t.status === 'running' && t.text.includes(text))
  if (match) {
    match.status = 'done'
  }
}

function calcPlanProgress(steps) {
  if (!steps || steps.length === 0) return 0
  const done = steps.filter(s => s.status === 'done' || s.status === 'failed').length
  return Math.round((done / steps.length) * 100)
}

function addSkill(name, agent) {
  if (!name) return
  const exists = store.referenceSkills.find(s => s.name === name)
  if (exists) {
    exists.count = (exists.count || 1) + 1
  } else {
    store.referenceSkills.push({ name, count: 1, agent: agent || '' })
  }
}

function addLink(url, title, agent) {
  if (!url) return
  const exists = store.referenceLinks.find(l => l.url === url)
  if (!exists) {
    store.referenceLinks.push({ url, title: title || url, agent: agent || '' })
  }
}

function ensureAssistantMessage() {
  const msgs = store.messages
  const lastMsg = msgs[msgs.length - 1]
  if (lastMsg && lastMsg.role === 'assistant') {
    return lastMsg
  }
  const newMsg = { role: 'assistant', content: '', timestamp: Date.now() }
  if (pendingProcessBlock) {
    newMsg.processBlock = pendingProcessBlock
    pendingProcessBlock = null
  }
  msgs.push(newMsg)
  return newMsg
}

function syncProcessBlock() {
  const hasData = store.taskTodos.length > 0 || store.referenceSkills.length > 0 || store.referenceLinks.length > 0
  if (!hasData) return
  const targetMsg = ensureAssistantMessage()
  const snapshot = {
    todos: store.taskTodos.map(t => ({ ...t })),
    skills: store.referenceSkills.map(s => ({ ...s })),
    links: store.referenceLinks.map(l => ({ ...l })),
    collapsed: targetMsg.processBlock?.collapsed ?? false
  }
  targetMsg.processBlock = snapshot
}

function handleSSEEvent(eventType, data) {
  try {
  // [Spectra debug] 记录每个事件的类型和关键数据
  const dataType = typeof data
  const dataSummary = dataType === 'string' ? ('str:' + data.slice(0, 60)) : (dataType === 'object' ? (data && data.tool ? 'tool:' + data.tool : (data && data.content ? 'content:' + String(data.content).slice(0, 40) : 'obj')) : dataType)
  console.log('[Spectra] handleSSEEvent:', eventType, dataSummary, 'msgs:', store.messages.length)

  switch (eventType) {
    case 'error':
      console.error('[Spectra] SSE error event:', data)
      store.thinkingStatus = '发生错误'
      {
        const targetMsg = ensureAssistantMessage()
        const errText = typeof data === 'string' ? data : (data && data.message ? data.message : JSON.stringify(data))
        targetMsg.content = `**❌ Agent 错误:**\n${errText}`
      }
      store.loading = false
      break

    case 'node':
      if (data && data.status) {
        store.thinkingStatus = data.status
        addTodo(data.status, data.node || data.agent || '')
      }
      syncProcessBlock()
      scrollToBottom()
      break

    case 'reply':
      if (data) {
        const text = typeof data === 'string' ? data : (data.text || '')
        const content = text.replace(/\\n/g, '\n')
        const targetMsg = ensureAssistantMessage()
        targetMsg.content = content
      }
      syncProcessBlock()
      scrollToBottom()
      break

    case 'llm_stream':
      if (data && data.content) {
        const targetMsg = ensureAssistantMessage()
        targetMsg.content += data.content
        // [Spectra debug] 追踪内容积累
        if (targetMsg.content.length < 200 || targetMsg.content.length % 500 < data.content.length) {
          console.log('[Spectra] llm_stream: total len=' + targetMsg.content.length)
        }
      }
      syncProcessBlock()
      scrollToBottom()
      break

    case 'reasoning_stream':
      if (data && data.content) {
        const targetMsg = ensureAssistantMessage()
        if (typeof targetMsg.reasoning !== 'string') {
          targetMsg.reasoning = ''
        }
        targetMsg.reasoning += data.content
        store.thinkingStatus = '模型思考中...'
      }
      syncProcessBlock()
      scrollToBottom()
      break

    case 'tool_start':
      if (data && data.tool) {
        store.currentToolCalls.push({
          name: data.tool,
          input: data.input,
          status: 'running',
        })
        const skillName = data.skill ? data.skill.name : null
        const displayName = skillName || data.tool
        store.thinkingStatus = skillName
          ? `正在使用技能: ${skillName} (${data.tool})...`
          : `正在调用工具: ${data.tool}...`
        // 只记录真实 skill 名称，不再把 tool 名当 skill
        if (skillName) {
          addSkill(skillName, data.agent || '')
        }
        addTodo(`调用 ${displayName}`, data.agent || '')
      }
      syncProcessBlock()
      break

    case 'tool_result':
      if (data && data.tool) {
        const tc = store.currentToolCalls.find(
          t => t.name === data.tool && t.status === 'running'
        )
        if (tc) {
          tc.status = 'done'
          tc.output = data.output
        }
        store.thinkingStatus = `工具 ${data.tool} 执行完成`
        markTodoDone(data.tool)
        if (data.output && (data.tool === 'web_search' || data.tool === 'web-search' || data.tool.includes('web'))) {
          const links = extractLinks(data.output)
          links.forEach(url => addLink(url, url, data.agent || ''))
        }
      }
      syncProcessBlock()
      break

    case 'runtime':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        Object.assign(store.runtimeState, payload)
        if (payload.lifecycle_event) {
          store.runtimeTimeline.unshift({
            key: payload.lifecycle_event + Date.now(),
            node: payload.node || '',
            activeAgent: payload.active_agent || '',
            selectedSkillName: payload.selected_skill_name || '',
            lifecycleEvent: payload.lifecycle_event,
          })
          if (payload.lifecycle_event === 'node_start' || payload.lifecycle_event === 'task_start') {
            const desc = payload.node || payload.active_agent || payload.lifecycle_event
            addTodo(desc, payload.active_agent || '')
          }
        }
      }
      syncProcessBlock()
      break

    case 'message':
      if (data && typeof data === 'string') {
        const targetMsg = ensureAssistantMessage()
        targetMsg.content = data.replace(/\\n/g, '\n')
      }
      syncProcessBlock()
      scrollToBottom()
      break

    case 'artifacts':
      if (data) {
        let items = typeof data === 'string' ? JSON.parse(data) : data
        if (Array.isArray(items)) {          items.forEach(item => {
            if (item.type === 'chart_html') {
              if (!store.charts.includes(item.path)) {
                store.charts.push(item.path)
                const chartExists = store.taskArtifacts.some(a => a.url === item.path)
                if (!chartExists) {
                  store.taskArtifacts.push({ id: 'ar-' + Date.now(), type: 'chart', name: item.name || '图表', url: item.path })
                }
              }
            } else {
              const exists = store.files.some(f => f.path === item.path)
              if (!exists) {
                store.files.push({ name: item.name || item.path.split('/').pop(), path: item.path })
                const artExists = store.taskArtifacts.some(a => a.url === item.path)
                if (!artExists) {
                  store.taskArtifacts.push({ id: 'ar-' + Date.now(), type: item.type || 'file', name: item.name || item.path.split('/').pop(), url: item.path })
                }
              }
            }
          })
        }
      }
      scrollToBottom()
      break

    case 'file':
      if (data && data.url) {
        const targetMsg = ensureAssistantMessage()
        targetMsg.downloadFile = {
          name: data.name || data.url.split('/').pop(),
          url: data.url,
          format: data.format || 'FILE'
        }
        store.taskArtifacts.push({
          id: 'ar-' + Date.now(),
          type: 'report',
          name: data.name || data.url.split('/').pop(),
          url: data.url
        })
      }
      scrollToBottom()
      break

    // Phase 2: plan 事件处理
    case 'plan_created':
      if (data && data.steps) {
        store.taskPlan = {
          steps: data.steps.map(s => ({
            id: s.id,
            description: s.description,
            status: s.status || 'pending',
            note: s.note || '',
            startedAt: s.started_at || 0,
            finishedAt: s.finished_at || 0,
          })),
          revision: data.revision || 0,
          finished: false,
          finishReason: '',
          summary: '',
          createdAt: Date.now(),
          progress: calcPlanProgress(data.steps),
        }
        store.thinkingStatus = `计划已创建: ${data.steps.length} 个步骤`
      }
      break

    case 'plan_updated':
      if (data && data.changes) {
        const taskPlan = ensureTaskPlan()
        for (const ch of data.changes) {
          const step = taskPlan.steps.find(s => s.id === ch.step_id)
          if (step) {
            step.status = ch.status
            if (ch.note) step.note = ch.note
            if (ch.status === 'running' && !step.startedAt) step.startedAt = Date.now()
            if (ch.status === 'done' || ch.status === 'failed') step.finishedAt = Date.now()
          }
        }
        taskPlan.progress = calcPlanProgress(taskPlan.steps)
      }
      break

    case 'plan_revised':
      if (data && data.steps) {
        const taskPlan = ensureTaskPlan()
        taskPlan.steps = data.steps.map(s => ({
          id: s.id,
          description: s.description,
          status: s.status || 'pending',
          note: s.note || '',
          startedAt: s.started_at || 0,
          finishedAt: s.finished_at || 0,
        }))
        taskPlan.revision = data.revision || 0
        taskPlan.progress = calcPlanProgress(data.steps)
        store.thinkingStatus = `计划已重排 (v${data.revision})`
      }
      break

    case 'plan_finished':
      ensureTaskPlan()
      store.taskPlan.finished = true
      store.taskPlan.finishReason = data.finish_reason || 'completed'
      store.taskPlan.summary = data.summary || ''
      break

    case 'usage':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.total) {
          store.usageStats = payload
        }
      }
      break

    case 'supervisor_decision':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.type) {
          store.thinkingStatus = `[Supervisor] ${payload.type}`
          addTodo(`Supervisor: ${payload.type}`, 'Supervisor')
        }
      }
      syncProcessBlock()
      break

    case 'agent_message':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.reply) {
          const targetMsg = ensureAssistantMessage()
          const label = payload.agent_id ? `**${payload.agent_id}**` : '**Agent**'
          const codeHint = payload.has_code ? ' `[含代码]`' : ''
          targetMsg.content += `${label}${codeHint}:\n${payload.reply}\n\n`
          store.thinkingStatus = `${payload.agent_id || 'Agent'} 已完成回复`
          addTodo(`${label} 完成`, payload.agent_id || 'Agent')
        }
      }
      syncProcessBlock()
      scrollToBottom()
      break

    case 'done':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.thread_id) {
          store.threadId = payload.thread_id
        }
      }
      store.thinkingStatus = '任务完成 ✓'
      store.loading = false
      const runningTodo = store.taskTodos.find(t => t.status === 'running')
      if (runningTodo) runningTodo.status = 'done'

      // 确保始终有一条 assistant 消息存在（即使前面没有任何事件触发创建）
      const lastAssistantMsg = ensureAssistantMessage()

      // [Spectra debug] 诊断日志：确认 done 时的消息状态
      if (lastAssistantMsg) {
        console.log('[Spectra] done:', {
          contentLen: (lastAssistantMsg.content || '').length,
          reasoningLen: (lastAssistantMsg.reasoning || '').length,
          hasProcessBlock: !!(lastAssistantMsg.processBlock && lastAssistantMsg.processBlock.todos && lastAssistantMsg.processBlock.todos.length > 0),
          hasDownloadFile: !!lastAssistantMsg.downloadFile,
          totalMessages: store.messages.length,
        })
      }

      // 健康检查：如果 assistant 消息是空的（LLM 没产出 content
      // 就 done 了，通常是 tool_call 被中断），清理掉这条空消息并提示用户。
      // 这避免下一次请求把空 AIMessage 再传回 LLM 导致 400。
      if (
        lastAssistantMsg &&
        !(lastAssistantMsg.content || '').trim() &&
        !(lastAssistantMsg.reasoning || '').trim() &&
        !lastAssistantMsg.downloadFile &&
        !(lastAssistantMsg.processBlock && lastAssistantMsg.processBlock.todos && lastAssistantMsg.processBlock.todos.length > 0)
      ) {
        // 完全空的 assistant 消息 → 移除并替换为警告
        const idx = store.messages.lastIndexOf(lastAssistantMsg)
        if (idx >= 0) store.messages.splice(idx, 1)
        store.messages.push({
          role: 'assistant',
          content: '**⚠️ 上次回复中断**：模型没有完成响应。请重新发送或尝试更简短的请求。',
          timestamp: Date.now(),
        })
      }

      syncProcessBlock()
      saveCurrentConversation()
      refreshHistoryGroups()
      const mature = checkConversationMaturity()
      store.suggestExport = mature
      if (mature) {
        const alreadySuggested = store.messages.some(m =>
          m.role === 'assistant' && m.content && m.content.includes('导出为 PDF 或 DOCX')
        )
        if (!alreadySuggested) {
          store.messages.push({
            role: 'assistant',
            content: '本次分析内容比较丰富，是否需要我帮您整理导出为 PDF 或 DOCX 格式的文档？（回复「导出 pdf」或「导出 docx」即可）',
            timestamp: Date.now(),
          })
        }
      }
      scrollToBottom()
      break

    case 'error':
      ensureAssistantMessage().content = `**❌ 执行出错:**\n${data}`
      store.loading = false
      syncProcessBlock()
      scrollToBottom()
      break
  }
  } catch (e) {
    console.error('[Spectra] handleSSEEvent 异常:', e)
    try {
      const errMsg = ensureAssistantMessage()
      errMsg.content = (errMsg.content || '') + `\n\n**❌ 处理事件异常:**\n${e.message}`
    } catch (_) {}
    store.loading = false
  }
}

export async function streamChat(body) {
  store.loading = true
  store.thinkingStatus = '正在连接 Agent 服务...'
  store.abortController = new AbortController()

  const msgCountBefore = store.messages.length
  let eventCount = 0

  try {
    const endpoint = store.agentMode === 'team' ? '/api/v2/chat' : '/api/chat'
    console.log(`[Spectra] 🎯 Agent 模式: ${store.agentMode.toUpperCase()} → 请求端点: ${endpoint}`)
    const response = await streamFetch(endpoint, body, store.abortController.signal)
    for await (const { event, data } of parseSSEStream(response)) {
      eventCount++
      handleSSEEvent(event, data)
    }

    // 兜底：如果流结束了但没有创建任何 assistant 消息，手动创建一条
    const lastMsg = store.messages[store.messages.length - 1]
    if (!lastMsg || lastMsg.role !== 'assistant' || !(lastMsg.content || '').trim()) {
      console.warn('[Spectra] SSE 流结束但无 assistant 消息，创建兜底消息。eventCount:', eventCount)
      if (!lastMsg || lastMsg.role !== 'assistant') {
        store.messages.push({ role: 'assistant', content: '', timestamp: Date.now() })
      }
      const assistantMsg = store.messages[store.messages.length - 1]
      if (!(assistantMsg.content || '').trim()) {
        assistantMsg.content = '**⚠️ 无法解析模型回复**：Agent 完成了处理，但未能提取到有效文本。请重试或检查模型 API 配置。'
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      store.messages.push({ role: 'assistant', content: `**❌ 连接异常:**\n${e.message}`, timestamp: Date.now() })
    }
  } finally {
    store.loading = false
    store.abortController = null
    scrollToBottom()
  }
}

export function handleStop() {
  if (store.abortController) {
    store.abortController.abort()
    store.abortController = null
  }
  store.loading = false
  store.thinkingStatus = '已停止'
}

export async function regenerateMessage(assistantMsgIndex) {
  if (store.loading) return

  let userMsg = null
  for (let i = assistantMsgIndex - 1; i >= 0; i--) {
    if (store.messages[i].role === 'user') {
      userMsg = store.messages[i]
      break
    }
  }
  if (!userMsg || !userMsg.content) return

  store.messages.splice(assistantMsgIndex)

  store.abortController = null
  store.currentToolCalls = []
  store.taskTodos = []
  store.taskArtifacts = []
  store.taskPlan = createEmptyTaskPlan()
  store.referenceSkills = []
  store.referenceLinks = []
  store.usageStats = { by_model: {}, total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } }
  todoSeq = 0
  pendingProcessBlock = null

  await streamChat({
    message: buildAgentMessage(userMsg.content),
    thread_id: store.threadId,
    model: store.apiKeys.selectedModel,
    persona_system_prompt: getActivePersonaPrompt(),
    attached_files: store.attachedFiles.map(f => ({
      name: f.name,
      table_name: f.table_name,
      type: f.type || 'csv',
    })),
    db_alias: store.dbConfig.alias || '',
  })
}

function buildAgentMessage(msg) {
  const prefs = store.userPreferences
  if (!prefs || !prefs.preferences || Object.keys(prefs.preferences).length === 0) return msg

  const lines = []
  for (const [key, value] of Object.entries(prefs.preferences)) {
    lines.push(`${key}: ${value}`)
  }
  return msg + `\n\n[系统记忆·用户偏好]\n${lines.join('\n')}`
}

function getActivePersonaPrompt() {
  if (!store.selectedPersonaId) return ''
  const persona = store.personas.find(p => p.id === store.selectedPersonaId)
  return persona ? persona.systemPrompt : ''
}

function checkConversationMaturity() {
  const lastAssistant = [...store.messages].reverse().find(m => m.role === 'assistant')
  if (!lastAssistant || !lastAssistant.content || lastAssistant.content.length < 800) return false

  return true
}

function generateExportTitle() {
  const firstUserMsg = store.messages.find(m => m.role === 'user')
  if (firstUserMsg && firstUserMsg.content) {
    const snippet = firstUserMsg.content.replace(/\n/g, ' ').slice(0, 40).trim()
    return snippet || 'Spectra 分析报告'
  }
  return 'Spectra 分析报告'
}

// 收集报告导出所需的素材：从最后一条 assistant 消息提取 markdown 正文 +
// 按出现顺序收集图表 chartId/title，再用图表注册表 echarts.getDataURL 拿 PNG
async function _collectExportPayloadImpl() {
  const charts_utils = await import('../utils/charts.js')
  const { getChartInstance, hashStr } = charts_utils

  // 找最近一条非空 assistant 消息
  let target = null
  for (let i = store.messages.length - 1; i >= 0; i--) {
    const m = store.messages[i]
    if (m && m.role === 'assistant' && m.content && m.content.trim()) {
      target = m
      break
    }
  }
  const reportMarkdown = target ? target.content : ''

  // 按出现顺序找出所有图表（标签 + 兜底裸 JSON），生成 chartId
  const charts = []
  if (reportMarkdown) {
    const tagRe = /<agentArtifact\s+type="echarts"\s+title="([^"]*)"\s*>([\s\S]*?)<\/agentArtifact>/g
    const visited = []
    let m
    while ((m = tagRe.exec(reportMarkdown)) !== null) {
      visited.push({ index: m.index, title: m[1] || '', jsonStr: (m[2] || '').trim() })
    }
    // 兜底：扫裸 JSON
    const bareBlocks = extractBareEchartsBlocks(reportMarkdown)
    bareBlocks.forEach(b => visited.push({ index: b.start, title: b.title || '', jsonStr: b.jsonStr }))
    visited.sort((a, b) => a.index - b.index)

    visited.forEach((v, i) => {
      const chartId = 'chart-' + hashStr(v.jsonStr)
      const inst = getChartInstance(chartId)
      let dataUrl = ''
      if (inst && inst.chart && !inst.chart.isDisposed()) {
        try {
          dataUrl = inst.chart.getDataURL({
            type: 'png',
            pixelRatio: 2,
            backgroundColor: '#ffffff',
          })
        } catch (e) {
          console.warn('图表导出 PNG 失败', e)
        }
      }
      charts.push({
        chartId,
        title: v.title || `图表 ${i + 1}`,
        dataUrl,
      })
    })
  }

  // sources：用已收集的 referenceLinks
  const sources = (store.referenceLinks || []).map((l, i) => ({
    index: i + 1,
    title: l.title || l.url,
    url: l.url,
  }))

  return { reportMarkdown, charts, sources }
}

// 与 ChatMessage.vue 中的 extractBareEchartsBlocks 保持同一识别逻辑（精简版）
function extractBareEchartsBlocks(text) {
  const blocks = []
  let i = 0
  while (i < text.length) {
    const openIdx = text.indexOf('{', i)
    if (openIdx === -1) break
    const matched = matchBalancedJson(text, openIdx)
    if (matched === -1) { i = openIdx + 1; continue }
    const candidate = text.slice(openIdx, matched + 1)
    if (looksLikeEchartsJson(candidate)) {
      let parsed = null
      try { parsed = JSON.parse(candidate) } catch (_) {}
      if (parsed && hasEchartsShape(parsed)) {
        blocks.push({ start: openIdx, end: matched + 1, jsonStr: candidate, title: '' })
        i = matched + 1
        continue
      }
    }
    i = openIdx + 1
  }
  return blocks
}
function matchBalancedJson(text, openIdx) {
  let depth = 0, inStr = false, escape = false
  for (let i = openIdx; i < text.length; i++) {
    const ch = text[i]
    if (inStr) {
      if (escape) { escape = false; continue }
      if (ch === '\\') { escape = true; continue }
      if (ch === '"') inStr = false
      continue
    }
    if (ch === '"') { inStr = true; continue }
    if (ch === '{') depth++
    else if (ch === '}') { depth--; if (depth === 0) return i; if (depth < 0) return -1 }
  }
  return -1
}
function looksLikeEchartsJson(s) {
  if (!s || s.length < 30) return false
  if (!s.includes('"series"')) return false
  return s.includes('"xAxis"') || s.includes('"yAxis"') || s.includes('"radar"')
    || s.includes('"polar"') || /"type"\s*:\s*"pie"/.test(s)
}
function hasEchartsShape(obj) {
  if (!obj || typeof obj !== 'object') return false
  if (!('series' in obj)) return false
  return 'xAxis' in obj || 'yAxis' in obj || 'radar' in obj || 'polar' in obj
    || (Array.isArray(obj.series) && obj.series.some(s => s && s.type === 'pie'))
    || (obj.series && obj.series.type === 'pie')
}

async function exportConversation(format) {
  store.loading = true
  store.thinkingStatus = `正在生成 ${format.toUpperCase()} 文档...`

  try {
    const title = generateExportTitle()
    const { reportMarkdown, charts, sources } = await _collectExportPayloadImpl()

    if (!reportMarkdown) {
      throw new Error('找不到可导出的分析正文，请先让 Agent 完成一次回复')
    }

    const res = await apiFetch('/api/export_conversation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: store.threadId,
        format: format,
        title: title,
        report_markdown: reportMarkdown,
        charts,
        sources,
      })
    })

    if (!res.ok) {
      const errData = await res.json()
      throw new Error(errData.error || '导出失败')
    }

    const data = await res.json()

    store.taskArtifacts.push({
      id: 'ar-' + Date.now(),
      type: 'report',
      name: data.filename,
      url: data.file_path
    })

    const chartCount = charts.filter(c => c.dataUrl).length
    const totalCharts = charts.length
    const chartNote = totalCharts > 0
      ? `（包含 ${chartCount}/${totalCharts} 张图表${chartCount < totalCharts ? '，部分图表实例已被释放未能导出' : ''}）`
      : ''

    store.messages.push({
      role: 'assistant',
      content: `已为您导出 ${format.toUpperCase()} 文档${chartNote}`,
      timestamp: Date.now(),
      downloadFile: {
        name: data.filename,
        url: data.file_path,
        format: format.toUpperCase()
      }
    })

    store.thinkingStatus = '导出完成 ✓'
  } catch (e) {
    store.messages.push({
      role: 'assistant',
      content: `**❌ 导出失败:** ${e.message}`,
      timestamp: Date.now(),
    })
    store.thinkingStatus = ''
  } finally {
    store.loading = false
    scrollToBottom()
  }
}

export async function handlePrimarySend() {
  if (!store.userInput.trim() || store.loading) return

  let msg = store.userInput.trim()

  rememberUserPreference(msg)

  if (store.attachedFiles.length > 0) {
    const fileNames = store.attachedFiles.map(f => f.name).join(', ')
    msg = `[附带文件: ${fileNames}]\n${msg}`
  }

  store.messages.push({ role: 'user', content: msg, timestamp: Date.now() })
  store.userInput = ''
  store.attachedFiles = []
  store.currentToolCalls = []
  store.taskTodos = []
  store.taskArtifacts = []
  store.taskPlan = createEmptyTaskPlan()
  store.referenceSkills = []
  store.referenceLinks = []
  store.usageStats = { by_model: {}, total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } }
  todoSeq = 0
  pendingProcessBlock = null
  if (store.inputArea) store.inputArea.style.height = 'auto'
  scrollToBottom()

  // 导出请求：收集图表 PNG 和最近 assistant 回复正文，传给后端
  let attachedCharts = []
  let exportContent = {}
  if (looksLikeExportRequest(msg)) {
    try {
      const payload = await _collectExportPayloadImpl()
      attachedCharts = (payload.charts || [])
        .filter(c => c.dataUrl)
        .map((c, i) => ({
          name: `chart_${i + 1}.png`,
          title: c.title || '',
          dataUrl: c.dataUrl,
        }))
      if (payload.reportMarkdown) {
        const firstH1 = (payload.reportMarkdown.match(/^#\s+(.+)/m) || [])[1] || ''
        exportContent = {
          content: payload.reportMarkdown,
          title: firstH1 || generateExportTitle(),
        }
      }
    } catch (e) {
      console.warn('收集导出素材失败，继续无图导出:', e)
    }
  }

  await streamChat({
    message: msg,
    thread_id: store.threadId,
    model: store.apiKeys.selectedModel,
    persona_system_prompt: getActivePersonaPrompt(),
    attached_charts: attachedCharts,
    attached_files: store.attachedFiles.map(f => ({
      name: f.name,
      table_name: f.table_name,
      type: f.type || 'csv',
    })),
    db_alias: store.dbConfig.alias || '',
    export_content: exportContent,
  })
}

function looksLikeExportRequest(msg) {
  if (!msg || typeof msg !== 'string') return false
  const verbRe = /(导出|保存|存为|存成|另存|转成|转为|整理成|打成|生成|下载成|做成)/
  const formatRe = /(pdf|docx|word文档|word|文档)/i
  return verbRe.test(msg) && formatRe.test(msg)
}

export async function handleFileUpload(event) {
  const file = event.target.files[0]
  if (!file) return

  const formData = new FormData()
  formData.append('file', file)

  store.uploadStatus = '正在处理文件...'
  store.uploadError = false

  try {
    const res = await apiFetch('/api/upload', { method: 'POST', body: formData })
    const data = await res.json()
    if (res.ok && !data.error) {
      store.attachedFiles.push({
        name: file.name,
        table_name: data.table_name || '',
        path: data.path || '',
        type: data.file_type
      })
      store.uploadStatus = `附件 ${file.name} 已添加`
      setTimeout(() => { store.uploadStatus = '' }, 3000)
    } else {
      throw new Error(data.error || data.detail || '服务器错误')
    }
  } catch (e) {
    store.uploadError = true
    store.uploadStatus = `上传失败: ${e.message}`
  } finally {
    event.target.value = ''
  }
}

export function removeFile(index) {
  store.attachedFiles.splice(index, 1)
}

export function useWorkflow(tpl) {
  store.currentWorkflow = tpl.workflow
  store.currentView = 'chat'
  store.userInput = tpl.title
  setTimeout(() => {
    if (store.inputArea) {
      store.inputArea.focus()
      resizeTextarea()
    }
  }, 100)
}

export function clearWorkflow() {
  store.currentWorkflow = null
}

export function resizeTextarea() {
  const el = store.inputArea
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

export async function connectDatabase() {
  if (!store.dbConfig.connectionString || !store.dbConfig.alias) {
    store.uploadError = true
    store.uploadStatus = '请填写完整的连接字符串和表别名'
    return
  }
  store.loading = true
  store.uploadStatus = '正在连接数据库...'
  store.uploadError = false

  try {
    const res = await apiFetch('/api/connect_db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        db_type: store.dbConfig.type,
        connection_string: store.dbConfig.connectionString,
        alias: store.dbConfig.alias
      })
    })
    const data = await res.json()
    if (res.ok && !data.error) {
      store.uploadStatus = `直连成功！数据库别名: ${store.dbConfig.alias}`
      store.currentView = 'chat'
      store.messages.push({
        role: 'assistant',
        content: `*(系统后台)* 已成功直连外部数据库 \`${store.dbConfig.alias}\`，您可以直接提问让我分析其中的表了！`,
        timestamp: Date.now(),
      })
    } else {
      throw new Error(data.error || '连接失败')
    }
  } catch (e) {
    store.uploadError = true
    store.uploadStatus = `连接失败: ${e.message}`
  } finally {
    store.loading = false
    scrollToBottom()
  }
}

export async function createSchedule() {
  if (!store.scheduleConfig.prompt) return
  store.loading = true
  try {
    const res = await apiFetch('/api/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(store.scheduleConfig)
    })
    const data = await res.json()
    if (res.ok && !data.error) {
      store.currentAutomationTab = 'history'
      store.scheduleConfig.prompt = ''
      fetchAlerts()
    } else {
      throw new Error(data.error || '创建失败')
    }
  } catch (e) {
    alert(`❌ 创建巡检任务失败: ${e.message}`)
  } finally {
    store.loading = false
  }
}

export async function fetchAlerts() {
  try {
    const res = await apiFetch('/api/alerts')
    const data = await res.json()
    if (res.ok) {
      store.alerts = data.alerts || []
    }
  } catch (e) {
    console.error('获取预警报告失败', e)
  }
}
