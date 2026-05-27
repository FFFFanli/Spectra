<template>
  <div class="chat-message-wrapper" :class="{ 'user-msg': msg.role === 'user', 'assistant-msg': msg.role === 'assistant' }">
    <div v-if="msg.role === 'user'" class="user-message-row">
      <div class="message-bubble user-bubble" v-text="msg.content"></div>
    </div>
    <div v-else class="assistant-message-card">
      <div class="assistant-meta">
        <div class="assistant-avatar">🤖</div>
        <div class="assistant-meta-text">
          <div class="assistant-name-row">
            <div class="assistant-name">Spectra Agent</div>
            <span class="assistant-dot"></span>
            <div class="assistant-time">{{ thinking ? '处理中' : (msg.timestamp ? formatTime(msg.timestamp) : '刚刚') }}</div>
          </div>
          <div class="assistant-subtitle">{{ thinking || '已完成回复' }}</div>
        </div>
        <div v-if="!streaming && msg.content" class="message-actions">
          <button class="msg-action-btn" @click.stop="copyContent" :title="copyLabel">
            <i class="fa-solid" :class="copied ? 'fa-check' : 'fa-copy'"></i>
          </button>
          <button class="msg-action-btn" @click.stop="regenerate" title="重新生成">
            <i class="fa-solid fa-rotate-right"></i>
          </button>
        </div>
      </div>
      <div class="assistant-body">
        <div v-if="msg.reasoning" class="reasoning-block" :class="{ collapsed: reasoningCollapsed }">
          <div class="reasoning-header" @click="reasoningCollapsed = !reasoningCollapsed">
            <span class="reasoning-header-left">
              <i class="fa-solid fa-brain"></i>
              <span class="reasoning-title">模型思考</span>
              <span v-if="streaming" class="reasoning-streaming">
                <i class="fa-solid fa-spinner fa-spin"></i>
              </span>
            </span>
            <i class="fa-solid" :class="reasoningCollapsed ? 'fa-chevron-right' : 'fa-chevron-down'"></i>
          </div>
          <div v-if="!reasoningCollapsed" class="reasoning-body">{{ msg.reasoning }}</div>
        </div>
        <div v-if="msg.processBlock && msg.processBlock.todos && msg.processBlock.todos.length > 0" class="process-block" :class="{ collapsed: msg.processBlock.collapsed }">
          <div class="process-header" @click="toggleProcess(msg)">
            <span class="process-header-left">
              <i class="fa-solid fa-list-check"></i>
              <span class="process-title">思考过程</span>
              <span class="process-badge">{{ doneCount(msg) }}/{{ msg.processBlock.todos.length }}</span>
            </span>
            <i class="fa-solid" :class="msg.processBlock.collapsed ? 'fa-chevron-right' : 'fa-chevron-down'"></i>
          </div>
          <div v-if="!msg.processBlock.collapsed" class="process-body">
            <!-- Phase 2: 有 plan 时显示 plan steps，否则显示旧 tool-level todos -->
            <div class="process-section">
              <div class="process-section-title">
                <i class="fa-solid fa-clipboard-list"></i> 任务步骤
              </div>
              <template v-if="planSteps.length > 0">
                <div v-for="s in planSteps" :key="s.id" class="process-todo">
                  <i class="fa-solid" :class="planStepIcon(s.status)" :style="{ color: planStepColor(s.status) }"></i>
                  <span :class="{ 'todo-done': s.status === 'done' }">{{ s.description }}</span>
                </div>
              </template>
              <template v-else>
                <div v-for="todo in msg.processBlock.todos" :key="todo.id" class="process-todo">
                  <i class="fa-solid" :class="todoStatusIcon(todo.status)" :style="{ color: todoStatusColor(todo.status) }"></i>
                  <span :class="{ 'todo-done': todo.status === 'done' }">{{ todo.text }}</span>
                </div>
              </template>
            </div>
            <div v-if="msg.processBlock.skills && msg.processBlock.skills.length > 0" class="process-section">
              <div class="process-section-title">
                <i class="fa-solid fa-wrench"></i> 使用技能
              </div>
              <div class="process-tags">
                <span v-for="s in msg.processBlock.skills" :key="s.name" class="process-tag skill-tag">
                  {{ s.name }}<template v-if="s.count > 1"> ×{{ s.count }}</template>
                </span>
              </div>
            </div>
            <div v-if="msg.processBlock.links && msg.processBlock.links.length > 0" class="process-section">
              <div class="process-section-title">
                <i class="fa-solid fa-globe"></i> 联网搜索
              </div>
              <div class="process-links">
                <a v-for="l in msg.processBlock.links" :key="l.url" :href="l.url" target="_blank" class="process-link" :title="l.url">
                  <i class="fa-solid fa-arrow-up-right-from-square"></i>
                  {{ l.title.length > 50 ? l.title.slice(0, 50) + '...' : l.title }}
                </a>
              </div>
            </div>
          </div>
        </div>
        <div v-if="segments.length > 0 || thinking" class="message-bubble assistant-bubble">
          <div v-if="segments.length === 0 && thinking" class="assistant-status">
            <i class="fa-solid fa-spinner fa-spin"></i>
            <span>{{ thinking }}</span>
          </div>
          <template v-for="(segment, idx) in segments" :key="idx">
            <div v-if="segment.type === 'text'" v-html="segment.html"></div>
            <InlineEcharts
              v-else-if="segment.type === 'chart'"
              :chart-id="segment.chartId"
              :json-str="segment.jsonStr"
              :title="segment.title"
              :streaming="streaming"
            />
          </template>
        </div>
        <!-- 多文件下载列表（Team mode 多产物） -->
        <div v-if="msg.downloadFiles && msg.downloadFiles.length" class="download-attachment download-list">
          <div class="download-list-title">
            <i class="fa-solid fa-folder-open"></i> 产物文件 ({{ msg.downloadFiles.length }})
          </div>
          <a
            v-for="f in msg.downloadFiles"
            :key="f.url"
            :href="f.url"
            :download="f.name"
            class="download-btn"
          >
            <i class="fa-solid fa-download"></i>
            <span class="download-label">{{ (f.format || 'FILE').toUpperCase() }}</span>
            <span class="download-name">{{ f.name }}</span>
          </a>
        </div>
        <!-- 兼容历史：单文件 downloadFile 仅在没有 downloadFiles 时单独渲染 -->
        <div
          v-else-if="msg.downloadFile"
          class="download-attachment"
        >
          <a :href="msg.downloadFile.url" :download="msg.downloadFile.name" class="download-btn">
            <i class="fa-solid fa-download"></i>
            <span class="download-label">下载 {{ msg.downloadFile.format }}</span>
            <span class="download-name">{{ msg.downloadFile.name }}</span>
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { computed, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import katex from 'katex'
import InlineEcharts from './InlineEcharts.vue'
import { hashStr } from '../utils/charts.js'
import { regenerateMessage } from '../composables/useChat.js'
import { store } from '../store.js'

// ── marked 配置：代码高亮 + 复制按钮 ──
const renderer = new marked.Renderer()
const origCode = renderer.code.bind(renderer)
renderer.code = function({ text, lang, escaped }) {
  let highlighted
  if (lang && hljs.getLanguage(lang)) {
    highlighted = hljs.highlight(text, { language: lang }).value
  } else {
    highlighted = hljs.highlightAuto(text).value
  }
  const langLabel = lang || 'code'
  return `<div class="code-block-wrapper">`
    + `<div class="code-block-header"><span>${langLabel}</span>`
    + `<button class="code-copy-btn" onclick="(function(btn){var p=btn.parentElement.nextElementSibling;var t=p.textContent;navigator.clipboard.writeText(t).then(function(){btn.textContent='已复制';setTimeout(function(){btn.textContent='复制'},2000)})})(this)">复制</button></div>`
    + `<pre><code class="hljs language-${langLabel}">${highlighted}</code></pre>`
    + `</div>`
}
marked.setOptions({ renderer })

// ── KaTeX 数学公式渲染 ──
function renderMath(text) {
  if (!text) return text
  // 块级公式 $$...$$
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, formula) => {
    try { return katex.renderToString(formula.trim(), { displayMode: true, throwOnError: false }) }
    catch { return _ }
  })
  // 行内公式 $...$
  text = text.replace(/\$(.+?)\$/g, (_, formula) => {
    try { return katex.renderToString(formula.trim(), { displayMode: false, throwOnError: false }) }
    catch { return _ }
  })
  return text
}

function renderMarkdown(text) {
  const html = marked.parse(text)
  return DOMPurify.sanitize(renderMath(html), { ADD_ATTR: ['target'] })
}

function formatTime(ts) {
  if (!ts) return '刚刚'
  const diff = Date.now() - ts
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
  return Math.floor(diff / 86400000) + ' 天前'
}

export default {
  name: 'ChatMessage',
  components: { InlineEcharts },
  props: {
    msg: { type: Object, required: true },
    msgIndex: { type: Number, default: -1 },
    thinking: { type: String, default: '' },
    streaming: { type: Boolean, default: false }
  },
  setup(props) {
    const reasoningCollapsed = ref(true)
    const copied = ref(false)
    const copyLabel = computed(() => copied.value ? '已复制' : '复制')

    const segments = computed(() => {
      const content = props.msg.content || ''
      return parseContentWithCharts(content)
    })
    const planSteps = computed(() => {
      if (!store || !store.taskPlan || !Array.isArray(store.taskPlan.steps)) {
        return []
      }
      return store.taskPlan.steps
    })

    function toggleProcess(msg) {
      if (msg.processBlock) {
        msg.processBlock.collapsed = !msg.processBlock.collapsed
      }
    }

    function doneCount(msg) {
      if (!msg.processBlock || !msg.processBlock.todos) return 0
      return msg.processBlock.todos.filter(t => t.status === 'done').length
    }

    function todoStatusIcon(status) {
      if (status === 'done') return 'fa-circle-check'
      if (status === 'running') return 'fa-spinner fa-spin'
      return 'fa-circle'
    }

    function todoStatusColor(status) {
      if (status === 'done') return '#10b981'
      if (status === 'running') return '#3b82f6'
      return '#94a3b8'
    }

    function planStepIcon(status) {
      if (status === 'done') return 'fa-circle-check'
      if (status === 'running') return 'fa-spinner fa-spin'
      if (status === 'failed') return 'fa-circle-xmark'
      return 'fa-circle'
    }

    function planStepColor(status) {
      if (status === 'done') return '#10b981'
      if (status === 'running') return '#3b82f6'
      if (status === 'failed') return '#ef4444'
      return '#94a3b8'
    }

    async function copyContent() {
      try {
        await navigator.clipboard.writeText(props.msg.content || '')
        copied.value = true
        setTimeout(() => { copied.value = false }, 2000)
      } catch (e) {
        // fallback for older browsers
        const ta = document.createElement('textarea')
        ta.value = props.msg.content || ''
        ta.style.position = 'fixed'; ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
        copied.value = true
        setTimeout(() => { copied.value = false }, 2000)
      }
    }

    function regenerate() {
      if (props.msgIndex >= 0) {
        regenerateMessage(props.msgIndex)
      }
    }

    return {
      $store: store,
      planSteps,
      segments, toggleProcess, doneCount, todoStatusIcon, todoStatusColor,
      planStepIcon, planStepColor,
      reasoningCollapsed, copied, copyLabel, copyContent, regenerate, formatTime
    }
  }
}

function parseContentWithCharts(content) {
  const results = []
  const re = /<agentArtifact\s+type="echarts"\s+title="([^"]*)"\s*>([\s\S]*?)<\/agentArtifact>/g
  let lastIndex = 0
  let match

  while ((match = re.exec(content)) !== null) {
    const before = content.slice(lastIndex, match.index)
    if (before.trim()) {
      pushTextOrFallbackCharts(results, before)
    }
    const title = match[1]
    const jsonStr = match[2].trim()
    const chartId = 'chart-' + hashStr(jsonStr)
    results.push({ type: 'chart', chartId, jsonStr, title })
    lastIndex = re.lastIndex
  }

  const remaining = content.slice(lastIndex)
  if (remaining.trim()) {
    pushTextOrFallbackCharts(results, remaining)
  }

  if (results.length === 0 && content.trim()) {
    pushTextOrFallbackCharts(results, content)
  }

  return results
}

// 兜底：在没有 <agentArtifact> 包裹的纯文本片段里识别"裸 ECharts JSON"。
// 触发条件：一段以 { 开头并且大括号配对的 JSON 文本，包含 ECharts 关键字段
//（"series" 加上 "xAxis"/"yAxis"/"radar"/"polar" 之一）。
function pushTextOrFallbackCharts(results, text) {
  const blocks = extractBareEchartsBlocks(text)
  if (blocks.length === 0) {
    results.push({ type: 'text', html: renderMarkdown(text) })
    return
  }
  let cursor = 0
  blocks.forEach((blk, i) => {
    const before = text.slice(cursor, blk.start)
    if (before.trim()) {
      results.push({ type: 'text', html: renderMarkdown(before) })
    }
    const chartId = 'chart-' + hashStr(blk.jsonStr)
    results.push({
      type: 'chart',
      chartId,
      jsonStr: blk.jsonStr,
      title: blk.title || `图表 ${i + 1}`,
    })
    cursor = blk.end
  })
  const tail = text.slice(cursor)
  if (tail.trim()) {
    results.push({ type: 'text', html: renderMarkdown(tail) })
  }
}

function extractBareEchartsBlocks(text) {
  const blocks = []
  const len = text.length
  let i = 0
  while (i < len) {
    const openIdx = text.indexOf('{', i)
    if (openIdx === -1) break
    const matched = matchBalancedJson(text, openIdx)
    if (!matched) {
      i = openIdx + 1
      continue
    }
    const candidate = text.slice(openIdx, matched + 1)
    if (looksLikeEchartsJson(candidate)) {
      let parsed = null
      try { parsed = JSON.parse(candidate) } catch (_) { parsed = null }
      if (parsed && hasEchartsShape(parsed)) {
        const title = guessTitleFromContext(text, openIdx)
        blocks.push({
          start: openIdx,
          end: matched + 1,
          jsonStr: candidate,
          title,
        })
        i = matched + 1
        continue
      }
    }
    i = openIdx + 1
  }
  return blocks
}

// 在字符串引号外做大括号配对，返回闭括号位置。失败返回 -1。
function matchBalancedJson(text, openIdx) {
  let depth = 0
  let inStr = false
  let escape = false
  for (let i = openIdx; i < text.length; i++) {
    const ch = text[i]
    if (inStr) {
      if (escape) { escape = false; continue }
      if (ch === '\\') { escape = true; continue }
      if (ch === '"') { inStr = false }
      continue
    }
    if (ch === '"') { inStr = true; continue }
    if (ch === '{') depth++
    else if (ch === '}') {
      depth--
      if (depth === 0) return i
      if (depth < 0) return -1
    }
  }
  return -1
}

function looksLikeEchartsJson(s) {
  if (!s || s.length < 30) return false
  if (!s.includes('"series"')) return false
  return (
    s.includes('"xAxis"') ||
    s.includes('"yAxis"') ||
    s.includes('"radar"') ||
    s.includes('"polar"') ||
    /"type"\s*:\s*"pie"/.test(s)
  )
}

function hasEchartsShape(obj) {
  if (!obj || typeof obj !== 'object') return false
  if (!('series' in obj)) return false
  return 'xAxis' in obj || 'yAxis' in obj || 'radar' in obj || 'polar' in obj || (
    Array.isArray(obj.series) && obj.series.some(s => s && s.type === 'pie')
  ) || (obj.series && obj.series.type === 'pie')
}

// 从前文里抓一个看起来像章节标题的短句作为图表名（例如"3.1 投资规模变化"）。
function guessTitleFromContext(text, openIdx) {
  const before = text.slice(0, openIdx)
  const lines = before.split(/\r?\n/).map(s => s.trim()).filter(Boolean)
  for (let k = lines.length - 1; k >= 0 && k >= lines.length - 4; k--) {
    const line = lines[k]
    if (line.length > 0 && line.length <= 40 && !line.endsWith('。') && !line.endsWith('.')) {
      return line.replace(/^#+\s*/, '')
    }
  }
  return ''
}

</script>

<style scoped>
.chat-message-wrapper { margin-bottom: 16px }
.user-message-row {
  display: flex;
  justify-content: flex-end;
}
.assistant-message-card {
  width: min(760px, 100%);
  margin: 0 auto;
}
.assistant-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.message-actions {
  margin-left: auto;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}
.assistant-message-card:hover .message-actions { opacity: 1 }
.msg-action-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.1s, color 0.1s;
}
.msg-action-btn:hover {
  background: #f1f5f9;
  color: #475569;
}
@media (prefers-color-scheme: dark) {
  .msg-action-btn { color: #64748b }
  .msg-action-btn:hover { background: #334155; color: #94a3b8 }
}
.assistant-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; font-size: 15px;
  background: #dbeafe;
  box-shadow: inset 0 0 0 1px rgba(30, 64, 175, 0.1);
}
.assistant-meta-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.assistant-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.assistant-name {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
}
.assistant-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #94a3b8;
}
.assistant-time {
  font-size: 11px;
  color: #64748b;
}
.assistant-subtitle {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.assistant-body { width: 100%; min-width: 0 }

.process-block {
  margin-bottom: 6px;
  border: none;
  border-radius: 14px;
  background: #fafafa;
  overflow: hidden;
}

.reasoning-block {
  margin-bottom: 6px;
  border-radius: 14px;
  background: #f5f3ff;
  border: 1px solid #ede9fe;
  overflow: hidden;
}
.reasoning-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; cursor: pointer; user-select: none;
  font-size: 13px; color: #6d28d9;
}
.reasoning-header:hover { background: #ede9fe }
.reasoning-header-left { display: flex; align-items: center; gap: 6px }
.reasoning-title { font-weight: 600 }
.reasoning-streaming { font-size: 11px; color: #8b5cf6 }
.reasoning-body {
  padding: 8px 12px 12px;
  font-size: 12px;
  line-height: 1.6;
  color: #4c1d95;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.process-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; cursor: pointer; user-select: none;
  font-size: 13px; color: #475569;
}
.process-header:hover { background: #f5f5f5 }
.process-header-left { display: flex; align-items: center; gap: 6px }
.process-title { font-weight: 600 }
.process-badge {
  font-size: 11px; background: #f1f5f9; color: #64748b;
  padding: 1px 7px; border-radius: 10px;
}
.process-body { padding: 0 12px 10px }
.process-section { margin-top: 6px }
.process-section:first-child { margin-top: 0 }
.process-section-title {
  font-size: 11px; font-weight: 600; color: #64748b;
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 4px; display: flex; align-items: center; gap: 4px;
}
.process-todo {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #1e293b; padding: 3px 0; line-height: 1.5;
}
.process-todo .fa-circle { font-size: 7px }
.process-todo .fa-circle-check { font-size: 13px }
.process-todo .fa-spinner { font-size: 12px }
.todo-done { color: #94a3b8; text-decoration: line-through }

.process-tags { display: flex; flex-wrap: wrap; gap: 4px }
.process-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 6px;
  background: #ede9fe; color: #7c3aed; font-weight: 500;
}

.process-links { display: flex; flex-direction: column; gap: 2px }
.process-link {
  font-size: 12px; color: #3b82f6; text-decoration: none;
  display: flex; align-items: center; gap: 4px; padding: 2px 0;
}
.process-link:hover { text-decoration: underline }
.process-link i { font-size: 9px }

.message-bubble {
  padding: 12px 16px; border-radius: 14px;
  font-size: 14px; line-height: 1.65; overflow-x: auto;
  word-wrap: break-word; overflow-wrap: break-word;
}
.user-bubble {
  max-width: min(420px, 72%);
  background: #f1f5f9;
  color: #334155;
  border: none;
  border-bottom-right-radius: 8px;
  padding: 10px 14px;
  box-shadow: none;
}
.assistant-bubble {
  background: transparent;
  color: #0f172a;
  border: none;
  border-radius: 16px;
  box-shadow: none;
  padding: 12px 4px;
}
.assistant-status {
  display: flex; align-items: center; gap: 8px;
  color: #64748b; font-size: 13px;
}

@media (prefers-color-scheme: dark) {
  .assistant-avatar { background: #1e3a5f }
  .assistant-name { color: #e2e8f0 }
  .assistant-dot { background: #475569 }
  .assistant-time { color: #64748b }
  .assistant-subtitle { color: #64748b }
  .assistant-bubble { background: transparent; color: #e2e8f0; border: none; box-shadow: none }
  .assistant-status { color: #64748b }
  .process-block { border: none; background: #1a202c }
  .process-header { color: #94a3b8 }
  .process-header:hover { background: #1e293b }
  .reasoning-block { background: #1e1b3a; border-color: #312e81 }
  .reasoning-header { color: #c4b5fd }
  .reasoning-header:hover { background: #2e1065 }
  .reasoning-body { color: #c4b5fd }
  .process-badge { background: #334155; color: #94a3b8 }
  .process-todo { color: #e2e8f0 }
  .todo-done { color: #64748b }
  .process-tag { background: #312e81; color: #a5b4fc }
  .process-link { color: #60a5fa }
  .user-bubble { background: #1e293b; color: #cbd5e1; border: none }
}

.download-attachment {
  margin-top: 8px;
}

/* 多文件下载列表 */
.download-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.download-list-title {
  font-size: 12px;
  color: #475569;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.download-list-title i {
  color: #3b82f6;
}

@media (prefers-color-scheme: dark) {
  .download-list-title {
    color: #cbd5e1;
  }
  .download-list-title i {
    color: #60a5fa;
  }
}

.download-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 10px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: background 0.15s, border-color 0.15s;
}

.download-btn:hover {
  background: #dbeafe;
  border-color: #93c5fd;
}

.download-btn i {
  font-size: 14px;
}

.download-label {
  font-weight: 600;
}

.download-name {
  color: #64748b;
  font-size: 12px;
}

@media (prefers-color-scheme: dark) {
  .download-btn {
    background: #1e3a5f;
    border-color: #2563eb;
    color: #93c5fd;
  }

  .download-btn:hover {
    background: #1e40af;
    border-color: #3b82f6;
  }

  .download-name {
    color: #94a3b8;
  }
}

/* ── 代码块 ── */
.code-block-wrapper {
  margin: 10px 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}
.code-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #f1f5f9;
  font-size: 11px;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.code-copy-btn {
  padding: 2px 8px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #64748b;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.1s;
}
.code-copy-btn:hover { background: #e2e8f0; color: #334155 }
.code-block-wrapper pre {
  margin: 0;
  padding: 12px 16px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.55;
  background: #0d1117;
  color: #c9d1d9;
}
.code-block-wrapper code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: none; padding: 0 }

/* ── KaTeX ── */
.katex-display { overflow-x: auto; overflow-y: hidden; padding: 4px 0 }

@media (prefers-color-scheme: dark) {
  .code-block-wrapper { border-color: #30363d }
  .code-block-header { background: #161b22; color: #8b949e }
  .code-copy-btn { color: #8b949e }
  .code-copy-btn:hover { background: #21262d; color: #c9d1d9 }
}
</style>
