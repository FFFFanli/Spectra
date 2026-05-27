import { nextTick } from 'vue'
import { store, getActiveSession, getActiveMode, setSessionPrimitive } from '../store.js'
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

// 创建一个 streamChat 级别的请求上下文。每次 streamChat 启动一个，
// 包含 ownerSession（写入目标）+ ownerMode（启动时的 mode 快照）+ 一些请求级状态。
function createStreamCtx() {
  const ownerSession = getActiveSession()
  const ownerMode = getActiveMode()
  return {
    ownerSession,
    ownerMode,
    todoSeq: 0,
    pendingProcessBlock: null,
  }
}

// 原语字段写入帮助：写 ownerSession，且当 ownerMode === store.agentMode 时同步到顶层。
function setPrim(ctx, key, value) {
  setSessionPrimitive(ctx.ownerSession, ctx.ownerMode, key, value)
}

function ensureTaskPlan(ctx) {
  const s = ctx.ownerSession
  if (!s.taskPlan || !Array.isArray(s.taskPlan.steps)) {
    s.taskPlan = createEmptyTaskPlan()
    if (ctx.ownerMode === store.agentMode) store.taskPlan = s.taskPlan
  }
  return s.taskPlan
}

function extractLinks(text) {
  if (!text || typeof text !== 'string') return []
  const urlRegex = /https?:\/\/[^\s<>"{}|\\^`\[\]]+/g
  const matches = text.match(urlRegex) || []
  return [...new Set(matches)]
}

function addTodo(ctx, text, agent) {
  ctx.todoSeq++
  const s = ctx.ownerSession
  const existing = s.taskTodos.find(t => t.status === 'running')
  if (existing) {
    existing.status = 'done'
  }
  s.taskTodos.push({
    id: 'td-' + ctx.todoSeq,
    text: (agent && !text.startsWith(agent) ? `[${agent}] ` : '') + text,
    status: 'running',
    agent: agent || ''
  })
}

function markTodoDone(ctx, text) {
  const match = ctx.ownerSession.taskTodos.find(t => t.status === 'running' && t.text.includes(text))
  if (match) {
    match.status = 'done'
  }
}

function calcPlanProgress(steps) {
  if (!steps || steps.length === 0) return 0
  const done = steps.filter(s => s.status === 'done' || s.status === 'failed').length
  return Math.round((done / steps.length) * 100)
}

function addSkill(ctx, name, agent) {
  if (!name) return
  const s = ctx.ownerSession
  const exists = s.referenceSkills.find(x => x.name === name)
  if (exists) {
    exists.count = (exists.count || 1) + 1
  } else {
    s.referenceSkills.push({ name, count: 1, agent: agent || '' })
  }
}

function addLink(ctx, url, title, agent) {
  if (!url) return
  const s = ctx.ownerSession
  const exists = s.referenceLinks.find(l => l.url === url)
  if (!exists) {
    s.referenceLinks.push({ url, title: title || url, agent: agent || '' })
  }
}

function ensureAssistantMessage(ctx) {
  const msgs = ctx.ownerSession.messages
  const lastMsg = msgs[msgs.length - 1]
  if (lastMsg && lastMsg.role === 'assistant') {
    return lastMsg
  }
  const newMsg = { role: 'assistant', content: '', timestamp: Date.now() }
  if (ctx.pendingProcessBlock) {
    newMsg.processBlock = ctx.pendingProcessBlock
    ctx.pendingProcessBlock = null
  }
  msgs.push(newMsg)
  return newMsg
}

function syncProcessBlock(ctx) {
  const s = ctx.ownerSession
  const hasData = s.taskTodos.length > 0 || s.referenceSkills.length > 0 || s.referenceLinks.length > 0
  if (!hasData) return
  const targetMsg = ensureAssistantMessage(ctx)
  const snapshot = {
    todos: s.taskTodos.map(t => ({ ...t })),
    skills: s.referenceSkills.map(x => ({ ...x })),
    links: s.referenceLinks.map(l => ({ ...l })),
    collapsed: targetMsg.processBlock?.collapsed ?? false
  }
  targetMsg.processBlock = snapshot
}

function handleSSEEvent(eventType, data, ctx) {
  const s = ctx.ownerSession
  try {
    const dataType = typeof data
    const dataSummary = dataType === 'string' ? ('str:' + data.slice(0, 60)) : (dataType === 'object' ? (data && data.tool ? 'tool:' + data.tool : (data && data.content ? 'content:' + String(data.content).slice(0, 40) : 'obj')) : dataType)
    console.log('[Spectra] handleSSEEvent:', eventType, dataSummary, 'mode:', ctx.ownerMode, 'msgs:', s.messages.length)

  switch (eventType) {
    case 'error':
      console.error('[Spectra] SSE error event:', data)
      setPrim(ctx, 'thinkingStatus', '发生错误')
      {
        const targetMsg = ensureAssistantMessage(ctx)
        const errText = typeof data === 'string' ? data : (data && data.message ? data.message : JSON.stringify(data))
        targetMsg.content = `**❌ Agent 错误:**\n${errText}`
      }
      setPrim(ctx, 'loading', false)
      break

    case 'node':
      if (data && data.status) {
        setPrim(ctx, 'thinkingStatus', data.status)
        addTodo(ctx, data.status, data.node || data.agent || '')
      }
      syncProcessBlock(ctx)
      scrollToBottom()
      break

    case 'reply':
      if (data) {
        const text = typeof data === 'string' ? data : (data.text || '')
        const content = text.replace(/\\n/g, '\n')
        const targetMsg = ensureAssistantMessage(ctx)
        targetMsg.content = content
      }
      syncProcessBlock(ctx)
      scrollToBottom()
      break

    case 'llm_stream':
      if (data && data.content) {
        const targetMsg = ensureAssistantMessage(ctx)
        targetMsg.content += data.content
        if (targetMsg.content.length < 200 || targetMsg.content.length % 500 < data.content.length) {
          console.log('[Spectra] llm_stream: total len=' + targetMsg.content.length)
        }
      }
      syncProcessBlock(ctx)
      scrollToBottom()
      break

    case 'reasoning_stream':
      if (data && data.content) {
        const targetMsg = ensureAssistantMessage(ctx)
        if (typeof targetMsg.reasoning !== 'string') {
          targetMsg.reasoning = ''
        }
        targetMsg.reasoning += data.content
        setPrim(ctx, 'thinkingStatus', '模型思考中...')
      }
      syncProcessBlock(ctx)
      scrollToBottom()
      break

    case 'tool_start':
      if (data && data.tool) {
        s.currentToolCalls.push({
          name: data.tool,
          input: data.input,
          status: 'running',
        })
        const skillName = data.skill ? data.skill.name : null
        const displayName = skillName || data.tool
        setPrim(ctx, 'thinkingStatus', skillName
          ? `正在使用技能: ${skillName} (${data.tool})...`
          : `正在调用工具: ${data.tool}...`)
        if (skillName) {
          addSkill(ctx, skillName, data.agent || '')
        }
        addTodo(ctx, `调用 ${displayName}`, data.agent || '')
      }
      syncProcessBlock(ctx)
      break

    case 'tool_result':
      if (data && data.tool) {
        const tc = s.currentToolCalls.find(
          t => t.name === data.tool && t.status === 'running'
        )
        if (tc) {
          tc.status = 'done'
          tc.output = data.output
        }
        setPrim(ctx, 'thinkingStatus', `工具 ${data.tool} 执行完成`)
        markTodoDone(ctx, data.tool)
        if (data.output && (data.tool === 'web_search' || data.tool === 'web-search' || data.tool.includes('web'))) {
          const links = extractLinks(data.output)
          links.forEach(url => addLink(ctx, url, url, data.agent || ''))
        }
      }
      syncProcessBlock(ctx)
      break

    case 'runtime':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        Object.assign(s.runtimeState, payload)
        if (payload.lifecycle_event) {
          s.runtimeTimeline.unshift({
            key: payload.lifecycle_event + Date.now(),
            node: payload.node || '',
            activeAgent: payload.active_agent || '',
            selectedSkillName: payload.selected_skill_name || '',
            lifecycleEvent: payload.lifecycle_event,
          })
          if (payload.lifecycle_event === 'node_start' || payload.lifecycle_event === 'task_start') {
            const desc = payload.node || payload.active_agent || payload.lifecycle_event
            addTodo(ctx, desc, payload.active_agent || '')
          }
        }
      }
      syncProcessBlock(ctx)
      break

    case 'message':
      if (data && typeof data === 'string') {
        const targetMsg = ensureAssistantMessage(ctx)
        targetMsg.content = data.replace(/\\n/g, '\n')
      }
      syncProcessBlock(ctx)
      scrollToBottom()
      break

    case 'artifacts':
      if (data) {
        let items = typeof data === 'string' ? JSON.parse(data) : data
        if (Array.isArray(items)) {
          const targetMsg = ensureAssistantMessage(ctx)
          if (!Array.isArray(targetMsg.downloadFiles)) targetMsg.downloadFiles = []
          items.forEach(item => {
            const url = item.url || item.path
            const name = item.name || (url ? url.split('/').pop() : '')
            if (item.type === 'chart_html') {
              if (url && !s.charts.includes(url)) {
                s.charts.push(url)
                const chartExists = s.taskArtifacts.some(a => a.url === url)
                if (!chartExists) {
                  s.taskArtifacts.push({ id: 'ar-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6), type: 'chart', name: name || '图表', url })
                }
              }
            } else {
              if (url) {
                const exists = s.files.some(f => f.path === url)
                if (!exists) {
                  s.files.push({ name, path: url })
                }
                const artExists = s.taskArtifacts.some(a => a.url === url)
                if (!artExists) {
                  s.taskArtifacts.push({ id: 'ar-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6), type: item.type || 'file', name, url })
                }
                // 把可下载文件追加到当前 assistant 消息的下载列表
                const dup = targetMsg.downloadFiles.find(x => x.url === url)
                if (!dup) {
                  const fmt = (name.split('.').pop() || item.type || 'FILE').toUpperCase()
                  targetMsg.downloadFiles.push({ name, url, format: fmt, type: item.type || 'misc' })
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
        const targetMsg = ensureAssistantMessage(ctx)
        const fileEntry = {
          name: data.name || data.url.split('/').pop(),
          url: data.url,
          format: data.format || 'FILE',
          type: data.type || 'misc',
        }
        // 兼容历史：保留 downloadFile（取最后一个），同时维护完整列表 downloadFiles
        targetMsg.downloadFile = fileEntry
        if (!Array.isArray(targetMsg.downloadFiles)) targetMsg.downloadFiles = []
        const dup = targetMsg.downloadFiles.find(x => x.url === fileEntry.url)
        if (!dup) targetMsg.downloadFiles.push(fileEntry)

        if (!s.taskArtifacts) s.taskArtifacts = []
        const existsArt = s.taskArtifacts.find(x => x.url === fileEntry.url)
        if (!existsArt) {
          s.taskArtifacts.push({
            id: 'ar-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
            type: data.type || 'report',
            name: fileEntry.name,
            url: fileEntry.url,
          })
        }
      }
      scrollToBottom()
      break

    case 'plan_created':
      if (data && data.steps) {
        const newPlan = {
          steps: data.steps.map(step => ({
            id: step.id,
            description: step.description,
            agent: step.assignee_agent_id || '',
            status: step.status || 'pending',
            note: step.note || '',
            startedAt: step.started_at || 0,
            finishedAt: step.finished_at || 0,
          })),
          revision: data.revision || 0,
          finished: false,
          finishReason: '',
          summary: '',
          createdAt: Date.now(),
          progress: calcPlanProgress(data.steps),
        }
        s.taskPlan = newPlan
        if (ctx.ownerMode === store.agentMode) store.taskPlan = newPlan
        setPrim(ctx, 'thinkingStatus', `计划已创建: ${data.steps.length} 个步骤`)
      }
      break

    case 'plan_updated':
      if (data && data.changes) {
        const taskPlan = ensureTaskPlan(ctx)
        for (const ch of data.changes) {
          const step = taskPlan.steps.find(x => x.id === ch.step_id)
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

    case 'step_started':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        const taskPlan = ensureTaskPlan(ctx)
        const step = taskPlan.steps.find(x => x.id === payload.step_id)
        if (step) {
          step.status = 'running'
          step.startedAt = Date.now()
        }
        taskPlan.progress = calcPlanProgress(taskPlan.steps)
        const desc = payload.description || (step ? step.description : '') || ''
        const agent = payload.assignee_agent_id || (step ? step.agent : '')
        const label = agent ? `[${agent}]` : ''
        setPrim(ctx, 'thinkingStatus',
          `${label} 正在执行: ${desc.slice(0, 60)}${desc.length > 60 ? '…' : ''}`)
        addTodo(ctx, desc || `执行步骤 ${payload.step_id}`, agent)
        // 把执行进度写到 assistant 消息体里，让用户在主聊天区看到实时执行流
        const targetMsg = ensureAssistantMessage(ctx)
        targetMsg.content = (targetMsg.content || '') +
          `\n\n🔄 ${label} **正在执行**：${desc}\n`
        scrollToBottom()
      }
      break

    case 'step_completed':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        const taskPlan = ensureTaskPlan(ctx)
        const step = taskPlan.steps.find(x => x.id === payload.step_id)
        if (step) {
          step.status = 'done'
          step.finishedAt = Date.now()
          if (payload.reply) step.note = payload.reply
        }
        taskPlan.progress = calcPlanProgress(taskPlan.steps)
        const agent = step ? step.agent : ''
        const label = agent ? `[${agent}]` : ''
        markTodoDone(ctx, step ? step.description : payload.step_id)
        setPrim(ctx, 'thinkingStatus',
          `${label} 步骤完成 (${taskPlan.progress}%)`)

        // 把完成消息和产物写入 assistant 消息流
        const targetMsg = ensureAssistantMessage(ctx)
        const desc = step ? step.description : payload.step_id
        let chunk = `\n✅ ${label} **完成**：${desc}\n`
        const reply = (payload.reply || '').trim()
        if (reply) {
          // 截断过长的 step.reply（长篇分析报告等），避免把 chat 区刷爆
          const truncated = reply.length > 800 ? reply.slice(0, 800) + '…' : reply
          chunk += `\n${truncated}\n`
        }

        // 收集 artifacts：写到消息的 downloadFiles 列表 + 右侧 ProcessSidebar 任务产物
        const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : []
        if (artifacts.length) {
          if (!s.taskArtifacts) s.taskArtifacts = []
          if (!Array.isArray(targetMsg.downloadFiles)) targetMsg.downloadFiles = []
          for (const a of artifacts) {
            const url = a.url || (a.path ? `/files/${a.path}` : '')
            const name = a.name || (url ? url.split('/').pop() : '')
            if (!url || !name) continue

            // 写入右侧任务产物列表（ProcessSidebar 会读 store.taskArtifacts）
            const exists = s.taskArtifacts.find(x => x.url === url)
            if (!exists) {
              s.taskArtifacts.push({
                id: 'art-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
                type: a.type || 'misc',
                name,
                path: a.path || '',
                url,
              })
            }

            // 写入消息体的下载列表
            const dupInMsg = targetMsg.downloadFiles.find(x => x.url === url)
            if (!dupInMsg) {
              const fmt = (name.split('.').pop() || a.type || 'FILE').toUpperCase()
              targetMsg.downloadFiles.push({ name, url, format: fmt, type: a.type || 'misc' })
            }
          }
        }

        targetMsg.content = (targetMsg.content || '') + chunk
        scrollToBottom()
      }
      break

    case 'step_failed':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        const taskPlan = ensureTaskPlan(ctx)
        const step = taskPlan.steps.find(x => x.id === payload.step_id)
        if (step) {
          step.status = 'failed'
          step.finishedAt = Date.now()
          if (payload.error) step.note = payload.error
        }
        taskPlan.progress = calcPlanProgress(taskPlan.steps)
        const retryHint = payload.retry_count > 0 ? ` (第 ${payload.retry_count} 次重试)` : ''
        setPrim(ctx, 'thinkingStatus',
          `❌ 步骤失败${retryHint}: ${(payload.error || '').slice(0, 80)}`)

        // 写到 assistant 消息流
        const targetMsg = ensureAssistantMessage(ctx)
        const agent = step ? step.agent : ''
        const label = agent ? `[${agent}]` : ''
        const desc = step ? step.description : payload.step_id
        const errPreview = (payload.error || '').slice(0, 200)
        targetMsg.content = (targetMsg.content || '') +
          `\n❌ ${label} **失败**${retryHint}：${desc}\n\`\`\`\n${errPreview}\n\`\`\`\n`
        scrollToBottom()
      }
      break

    case 'plan_revised':
      if (data && data.steps) {
        const taskPlan = ensureTaskPlan(ctx)
        taskPlan.steps = data.steps.map(step => ({
          id: step.id,
          description: step.description,
          agent: step.assignee_agent_id || '',
          status: step.status || 'pending',
          note: step.note || '',
          startedAt: step.started_at || 0,
          finishedAt: step.finished_at || 0,
        }))
        taskPlan.revision = data.revision || 0
        taskPlan.progress = calcPlanProgress(data.steps)
        setPrim(ctx, 'thinkingStatus', `计划已重排 (v${data.revision})`)
      }
      break

    case 'plan_finished': {
      const tp = ensureTaskPlan(ctx)
      tp.finished = true
      tp.finishReason = data.finish_reason || 'completed'
      tp.summary = data.summary || ''
      break
    }

    case 'usage':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.total) {
          s.usageStats = payload
          if (ctx.ownerMode === store.agentMode) store.usageStats = payload
        }
      }
      break

    case 'supervisor_decision':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.type) {
          setPrim(ctx, 'thinkingStatus', `[Supervisor] ${payload.type}`)
          addTodo(ctx, `Supervisor: ${payload.type}`, 'Supervisor')
        }
      }
      syncProcessBlock(ctx)
      break

    case 'agent_message':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.reply) {
          const targetMsg = ensureAssistantMessage(ctx)
          const label = payload.agent_id ? `**${payload.agent_id}**` : '**Agent**'
          const codeHint = payload.has_code ? ' `[含代码]`' : ''
          targetMsg.content += `${label}${codeHint}:\n${payload.reply}\n\n`
          setPrim(ctx, 'thinkingStatus', `${payload.agent_id || 'Agent'} 已完成回复`)
          addTodo(ctx, `${label} 完成`, payload.agent_id || 'Agent')
        }
      }
      syncProcessBlock(ctx)
      scrollToBottom()
      break

    case 'member_status':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.agent_id) {
          if (!s.members) s.members = {}
          s.members[payload.agent_id] = {
            state: payload.state || 'idle',
            currentStepId: payload.current_step_id || '',
          }
        }
      }
      break

    case 'task_pending':
    case 'task_progress':
    case 'task_completed':
    case 'task_failed':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.task_id) {
          if (!s.backgroundTasks) s.backgroundTasks = []
          const existing = s.backgroundTasks.find(t => t.taskId === payload.task_id)
          if (existing) {
            Object.assign(existing, {
              status: payload.status || existing.status,
              title: payload.title || existing.title,
              elapsed: payload.elapsed || '',
            })
          } else {
            s.backgroundTasks.push({
              taskId: payload.task_id,
              agentId: payload.agent_id || '',
              title: payload.title || '',
              status: payload.status || 'pending',
              elapsed: '',
            })
          }
        }
      }
      break

    case 'file_parsed':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.file_id) {
          if (!s.parsedFiles) s.parsedFiles = []
          const exists = s.parsedFiles.find(f => f.fileId === payload.file_id)
          if (!exists) {
            s.parsedFiles.push({
              fileId: payload.file_id,
              mimeType: payload.mime_type || '',
              summary: payload.summary || '',
              previewPayload: payload.preview_payload || null,
            })
          }
        }
      }
      break

    case 'workspace_artifact_added':
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.url) {
          if (!s.workspaceArtifacts) s.workspaceArtifacts = []
          const dup = s.workspaceArtifacts.find(x => x.url === payload.url)
          if (!dup) {
            s.workspaceArtifacts.push({
              id: payload.id || ('ar-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6)),
              type: payload.type || 'misc',
              name: payload.name || '',
              url: payload.url,
            })
          }
          // 同时灌进当前 assistant 消息的下载列表
          const targetMsg = ensureAssistantMessage(ctx)
          if (!Array.isArray(targetMsg.downloadFiles)) targetMsg.downloadFiles = []
          const dupInMsg = targetMsg.downloadFiles.find(x => x.url === payload.url)
          if (!dupInMsg) {
            const name = payload.name || payload.url.split('/').pop()
            const fmt = (name.split('.').pop() || payload.type || 'FILE').toUpperCase()
            targetMsg.downloadFiles.push({ name, url: payload.url, format: fmt, type: payload.type || 'misc' })
          }
        }
      }
      break

    case 'done': {
      if (data) {
        const payload = typeof data === 'string' ? JSON.parse(data) : data
        if (payload && payload.thread_id) {
          setPrim(ctx, 'threadId', payload.thread_id)
        }
      }
      setPrim(ctx, 'thinkingStatus', '任务完成 ✓')
      setPrim(ctx, 'loading', false)
      const runningTodo = s.taskTodos.find(t => t.status === 'running')
      if (runningTodo) runningTodo.status = 'done'

      const lastAssistantMsg = ensureAssistantMessage(ctx)

      if (lastAssistantMsg) {
        console.log('[Spectra] done:', {
          contentLen: (lastAssistantMsg.content || '').length,
          reasoningLen: (lastAssistantMsg.reasoning || '').length,
          hasProcessBlock: !!(lastAssistantMsg.processBlock && lastAssistantMsg.processBlock.todos && lastAssistantMsg.processBlock.todos.length > 0),
          hasDownloadFile: !!lastAssistantMsg.downloadFile,
          totalMessages: s.messages.length,
        })
      }

      if (
        lastAssistantMsg &&
        !(lastAssistantMsg.content || '').trim() &&
        !(lastAssistantMsg.reasoning || '').trim() &&
        !lastAssistantMsg.downloadFile &&
        !(lastAssistantMsg.processBlock && lastAssistantMsg.processBlock.todos && lastAssistantMsg.processBlock.todos.length > 0)
      ) {
        const idx = s.messages.lastIndexOf(lastAssistantMsg)
        if (idx >= 0) s.messages.splice(idx, 1)
        s.messages.push({
          role: 'assistant',
          content: '**⚠️ 上次回复中断**：模型没有完成响应。请重新发送或尝试更简短的请求。',
          timestamp: Date.now(),
        })
      }

      syncProcessBlock(ctx)
      // 仅在原 mode 仍是当前活跃 mode 时持久化（避免覆盖另一个 mode 的对话）
      if (ctx.ownerMode === store.agentMode) {
        saveCurrentConversation()
        refreshHistoryGroups()
      }
      const lastA = [...s.messages].reverse().find(m => m.role === 'assistant')
      const mature = !!(lastA && lastA.content && lastA.content.length >= 800)
      setPrim(ctx, 'suggestExport', mature)
      if (mature) {
        const alreadySuggested = s.messages.some(m =>
          m.role === 'assistant' && m.content && m.content.includes('导出为 PDF 或 DOCX')
        )
        if (!alreadySuggested) {
          s.messages.push({
            role: 'assistant',
            content: '本次分析内容比较丰富，是否需要我帮您整理导出为 PDF 或 DOCX 格式的文档？（回复「导出 pdf」或「导出 docx」即可）',
            timestamp: Date.now(),
          })
        }
      }
      scrollToBottom()
      break
    }
  }
  } catch (e) {
    console.error('[Spectra] handleSSEEvent 异常:', e)
    try {
      const errMsg = ensureAssistantMessage(ctx)
      errMsg.content = (errMsg.content || '') + `\n\n**❌ 处理事件异常:**\n${e.message}`
    } catch (_) {}
    setPrim(ctx, 'loading', false)
  }
}

export async function streamChat(body) {
  const ctx = createStreamCtx()
  const s = ctx.ownerSession

  setPrim(ctx, 'loading', true)
  setPrim(ctx, 'thinkingStatus', '正在连接 Agent 服务...')
  const ac = new AbortController()
  // abortController 是原语级别的对象引用，仍用 setPrim 同步顶层
  setPrim(ctx, 'abortController', ac)

  let eventCount = 0

  try {
    const endpoint = ctx.ownerMode === 'team' ? '/api/v2/chat' : '/api/chat'
    console.log(`[Spectra] 🎯 Agent 模式: ${ctx.ownerMode.toUpperCase()} → 请求端点: ${endpoint}`)
    const response = await streamFetch(endpoint, body, ac.signal)
    for await (const { event, data } of parseSSEStream(response)) {
      eventCount++
      handleSSEEvent(event, data, ctx)
    }

    // 兜底：流结束但无 assistant 消息
    const lastMsg = s.messages[s.messages.length - 1]
    if (!lastMsg || lastMsg.role !== 'assistant' || !(lastMsg.content || '').trim()) {
      console.warn('[Spectra] SSE 流结束但无 assistant 消息，创建兜底消息。eventCount:', eventCount)
      if (!lastMsg || lastMsg.role !== 'assistant') {
        s.messages.push({ role: 'assistant', content: '', timestamp: Date.now() })
      }
      const assistantMsg = s.messages[s.messages.length - 1]
      if (!(assistantMsg.content || '').trim()) {
        assistantMsg.content = '**⚠️ 无法解析模型回复**：Agent 完成了处理，但未能提取到有效文本。请重试或检查模型 API 配置。'
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      s.messages.push({ role: 'assistant', content: `**❌ 连接异常:**\n${e.message}`, timestamp: Date.now() })
    }
  } finally {
    setPrim(ctx, 'loading', false)
    setPrim(ctx, 'abortController', null)
    if (ctx.ownerMode === store.agentMode) {
      scrollToBottom()
    }
  }
}

export function handleStop() {
  // 只停当前 mode 的请求
  const s = getActiveSession()
  if (s.abortController) {
    s.abortController.abort()
    s.abortController = null
  }
  s.loading = false
  s.thinkingStatus = '已停止'
  // 同步顶层
  store.abortController = null
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

  // 注意：这里只能修改顶层 store 字段（用 splice/length=0 等就地清空）
  // 不能用 store.X = [] 替换引用，否则会和当前 mode 的 session 容器脱钩。
  const s = getActiveSession()
  s.messages.splice(assistantMsgIndex)
  s.currentToolCalls.length = 0
  s.taskTodos.length = 0
  s.taskArtifacts.length = 0
  s.referenceSkills.length = 0
  s.referenceLinks.length = 0
  // taskPlan / usageStats 是对象，就地清空
  Object.assign(s.taskPlan, createEmptyTaskPlan())
  s.usageStats.by_model = {}
  s.usageStats.total = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }
  s.abortController = null
  // 同步顶层（因为是当前 mode）
  store.abortController = null

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

  // 与 regenerateMessage 同样原则：就地清空，不替换引用
  const s = getActiveSession()
  s.messages.push({ role: 'user', content: msg, timestamp: Date.now() })
  store.userInput = ''
  s.userInput = ''
  s.attachedFiles.length = 0
  store.attachedFiles.length = 0
  s.currentToolCalls.length = 0
  s.taskTodos.length = 0
  s.taskArtifacts.length = 0
  s.referenceSkills.length = 0
  s.referenceLinks.length = 0
  Object.assign(s.taskPlan, createEmptyTaskPlan())
  s.usageStats.by_model = {}
  s.usageStats.total = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }
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

  const skillWorkflowId = store._skillWorkflowId || null
  store._skillWorkflowId = null  // 消费一次后清除

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
    skill_workflow_id: skillWorkflowId,
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
