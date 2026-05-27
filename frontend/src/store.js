import { reactive, ref } from 'vue'

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

/**
 * Solo / Team 模式各自独立的会话状态容器。
 *
 * 切换模式时，会把当前顶层 store 字段快照到旧模式容器，再从新模式容器恢复到顶层字段。
 * 这样每个模式都保留自己的消息列表、thread_id、产物、任务计划等。
 */
function createEmptySession() {
  return {
    messages: [],
    threadId: generateUUID(),
    thinkingStatus: '',
    currentToolCalls: [],
    taskTodos: [],
    taskArtifacts: [],
    taskPlan: {
      steps: [], revision: 0, finished: false, finishReason: '',
      summary: '', createdAt: 0, progress: 0,
    },
    runtimeState: {
      node: '', activeAgent: '', nextNode: '', targetAgent: '',
      selectedSkillName: '', selectedSkillCapability: '', skillAutoCreated: false,
      executionMode: '', fallbackSource: '', executionBackend: '',
    },
    runtimeTimeline: [],
    usageStats: { by_model: {}, total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } },
    referenceSkills: [],
    referenceLinks: [],
    suggestExport: false,
    activeHistoryId: null,
    conversationRenderKey: 0,
    charts: [],
    files: [],
    attachedFiles: [],
    userInput: '',
    loading: false,
    abortController: null,
    // Team 专有字段
    members: {},
    backgroundTasks: [],
    parsedFiles: [],
    workspaceArtifacts: [],
  }
}

export const store = reactive({
  authRequired: false,

  currentView: 'chat',
  isMobile: window.innerWidth < 1024,
  leftDrawerOpen: false,
  leftSidebarCollapsed: false,
  rightSidebarCollapsed: false,

  messages: [],
  userInput: '',
  loading: false,
  thinkingStatus: '',
  abortController: null,
  threadId: generateUUID(),
  inputArea: null,

  models: [
    { id: 'qwen3.5-plus', name: '通义千问 Qwen3.5-Plus' },
    { id: 'qwen3.6-plus', name: '通义千问 Qwen3.6-Plus' },
    { id: 'qwen-max', name: '通义千问 Qwen-Max' },
    { id: 'gpt-4o', name: 'OpenAI GPT-4o' },
    { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash' },
  ],  // 默认列表，fetchModels() 会用后端返回的动态列表覆盖
  apiKeys: {
    dashscope: '',
    openai: '',
    deepseek: '',
    selectedModel: 'qwen3.5-plus'
  },

  attachedFiles: [],
  charts: [],
  files: [],

  currentToolCalls: [],

  // 本次请求 token 用量统计（由后端 usage 事件下发）
  // {by_model: {model: {input_tokens, output_tokens, total_tokens}}, total: {...}}
  usageStats: { by_model: {}, total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } },

  runtimeState: {
    node: '', activeAgent: '', nextNode: '', targetAgent: '',
    selectedSkillName: '', selectedSkillCapability: '', skillAutoCreated: false,
    executionMode: '', fallbackSource: '', executionBackend: '',
  },
  runtimeTimeline: [],

  activeHistoryId: null,
  historyGroups: [],
  conversationRenderKey: 0,

  currentAutomationTab: 'templates',
  currentWorkflow: null,
  automationTemplates: [
    { icon: '<span class="text-blue-500">📑</span>', title: '每日 AI 新闻抓取', desc: '每天早上搜索AI行业最新动态并总结分析', workflow: 'ai_news_daily' },
    { icon: '<span class="text-green-500">🛒</span>', title: '竞品数据监控日报', desc: '每天抓取竞品价格和销量变化并推送，生成趋势报告', workflow: 'competitor_monitor' },
    { icon: '<span class="text-purple-500">⚙️</span>', title: '每周竞品动态巡检', desc: '定期抓取竞品的产品更新、社区反馈和用户舆情', workflow: 'weekly_competitor_scan' },
    { icon: '<span class="text-red-500">📈</span>', title: '股价/大盘异常告警', desc: '每小时监控指定股票涨跌幅，异常时及时发送告警', workflow: 'stock_alert' },
    { icon: '<span class="text-teal-500">🔍</span>', title: '安全漏洞日报', desc: '定期抓取漏洞库信息，发现相关组件高危漏洞立即告警', workflow: 'security_vuln_daily' },
    { icon: '<span class="text-orange-500">🛠️</span>', title: '扫描仓库 Bug', desc: '分析代码仓库动态，发现潜在代码质量或逻辑 Bug' },
    { icon: '<span class="text-indigo-500">⟳</span>', title: '补充测试用例', desc: '监控代码变动并自动生成缺失的单元测试代码' },
    { icon: '<span class="text-pink-500">📋</span>', title: '每日需求整理', desc: '每天分析收到的业务需求情况，生成团队跟进日报' }
  ],

  scheduleConfig: { prompt: '', cron: '*/1 * * * *' },
  alerts: [],

  dbConfig: { type: 'mysql', connectionString: '', alias: '' },
  uploadStatus: '',
  uploadError: false,

  settingsSaving: false,
  settingsSaved: false,
  settingsError: '',

  userPreferences: {
    preferredChartType: null,
    language: 'zh-CN',
    preferences: {}
  },

  taskTodos: [],
  taskArtifacts: [],
  taskPlan: {
    steps: [],
    revision: 0,
    finished: false,
    finishReason: '',
    summary: '',
    createdAt: 0,
    progress: 0,
  },
  referenceSkills: [],
  referenceLinks: [],

  suggestExport: false,

  personas: [],          // 用户自定义角色模板 [{id, name, systemPrompt, createdAt}]
  selectedPersonaId: null,  // 当前选中的角色 ID
  agentMode: localStorage.getItem('spectra_agent_mode') || 'solo',  // 'solo' | 'team'

  // 双模式独立会话容器：当前模式的状态在顶层字段，非当前模式的状态备份在这里
  soloSession: createEmptySession(),
  teamSession: createEmptySession(),

  availableSkills: [
    { id: 'web-search', name: '联网搜索', category: '搜索', icon: 'fa-solid fa-globe', desc: '实时搜索互联网获取最新信息', color: '#3b82f6' },
    { id: 'web-fetch', name: '网页抓取', category: '搜索', icon: 'fa-solid fa-file-arrow-down', desc: '抓取并解析指定网页内容', color: '#2563eb' },
    { id: 'chart', name: '图表绘制', category: '可视化', icon: 'fa-solid fa-chart-pie', desc: '根据数据生成 ECharts 交互图表', color: '#8b5cf6' },
    { id: 'file-read', name: '文件读取', category: '文件', icon: 'fa-solid fa-file-lines', desc: '读取上传的文件内容并分析', color: '#f59e0b' },
    { id: 'code-exec', name: '代码执行', category: '开发', icon: 'fa-solid fa-code', desc: '在沙箱中执行 Python 代码片段', color: '#10b981' },
    { id: 'db-query', name: '数据库查询', category: '数据', icon: 'fa-solid fa-database', desc: '连接数据库执行 SQL 查询', color: '#ef4444' },
    { id: 'report-gen', name: '报告生成', category: '输出', icon: 'fa-solid fa-file-pdf', desc: '将分析结果整理为结构化报告', color: '#ec4899' },
    { id: 'news-digest', name: '新闻摘要', category: '内容', icon: 'fa-solid fa-newspaper', desc: '抓取并总结新闻动态与要点', color: '#06b6d4' },
    { id: 'alert-monitor', name: '告警监控', category: '自动化', icon: 'fa-solid fa-bell', desc: '定时监控异常指标并发送告警', color: '#f97316' },
    { id: 'translate', name: '翻译', category: '内容', icon: 'fa-solid fa-language', desc: '多语言翻译与本地化处理', color: '#6366f1' },
    { id: 'summarize', name: '摘要生成', category: '内容', icon: 'fa-solid fa-align-left', desc: '对长文本自动生成精炼摘要', color: '#14b8a6' },
    { id: 'image-gen', name: '图像生成', category: '生成', icon: 'fa-solid fa-image', desc: '根据描述生成 AI 图像', color: '#d946ef' }
  ]
})

export function generateThreadId() {
  return generateUUID()
}

/**
 * 字段列表：哪些顶层 store 字段是会话级状态。
 * 切换模式时所有这些字段的引用（数组/对象）和值（原语）都在 soloSession/teamSession 中独立保存。
 */
const SESSION_FIELDS = [
  'messages', 'threadId', 'thinkingStatus', 'currentToolCalls',
  'taskTodos', 'taskArtifacts', 'taskPlan',
  'runtimeState', 'runtimeTimeline', 'usageStats',
  'referenceSkills', 'referenceLinks', 'suggestExport',
  'activeHistoryId', 'conversationRenderKey',
  'charts', 'files', 'attachedFiles', 'userInput',
  'loading', 'abortController',
]

// 关键不变量：当前 mode 的所有顶层 SESSION_FIELDS 字段 ===
// store.{soloSession|teamSession} 对应字段（数组/对象引用相等，原语值同步）。
// 这样：
//   - SSE 处理器在 streamChat 启动时捕获 ownerSession 引用，对数组/对象 mutation
//     直接通过 ownerSession 写入；对原语用 setSessionPrimitive 双写。
//   - 切换模式后，原 stream 仍然写入原 ownerSession，不污染对方 session。
//   - 切回原 mode 时引用恢复一致，原 stream 的累积写入再次反映到 UI。

// 把当前顶层字段引用回写到当前 mode 的 session 容器（保证一致性）
// 在替换顶层引用（如 store.messages = []）之后调用，保证 session 容器同步。
export function syncTopToSession() {
  const key = store.agentMode === 'solo' ? 'soloSession' : 'teamSession'
  for (const k of SESSION_FIELDS) {
    store[key][k] = store[k]
  }
}

// 启动一次：把初始顶层数组/对象引用注入对应 session
syncTopToSession()

/**
 * 切换 Agent 模式（solo <-> team）。
 *
 * 切换流程：
 *   1. 把当前顶层会话字段同步到当前 mode session（保证后续不变量）
 *   2. 修改 agentMode 标记
 *   3. 把目标 mode session 的字段恢复到顶层
 *
 * 流式中调用是安全的：原 streamChat 持有的 ownerSession 引用不会改变，
 * 仍然能继续写入它自己的会话。
 */
export function switchAgentMode(newMode) {
  if (newMode !== 'solo' && newMode !== 'team') return
  if (store.agentMode === newMode) return

  // 1. 把顶层引用回写到当前 mode session
  syncTopToSession()

  // 2. 切换 mode 标记
  store.agentMode = newMode
  localStorage.setItem('spectra_agent_mode', newMode)

  // 3. 把目标 mode session 字段恢复到顶层
  const newKey = newMode === 'solo' ? 'soloSession' : 'teamSession'
  for (const k of SESSION_FIELDS) {
    if (k in store[newKey]) {
      store[k] = store[newKey][k]
    }
  }

  // 触发消息列表重新渲染
  store.conversationRenderKey++
}

/**
 * 取当前 mode 的 session 容器引用。
 * streamChat 启动时调用，并在第一时间同步顶层引用到容器，
 * 保证后续 ownerSession 与顶层 store 字段引用一致。
 */
export function getActiveSession() {
  syncTopToSession()
  return store.agentMode === 'solo' ? store.soloSession : store.teamSession
}

/**
 * 取当前 mode 标记（不可变快照）。streamChat 启动时捕获，
 * 用来在 SSE 回调时判断"我是不是仍在被显示的 mode"。
 */
export function getActiveMode() {
  return store.agentMode
}

/**
 * 设置 session 原语字段：写入 ownerSession，且仅在当前 mode === ownerMode 时同步到顶层。
 * 数组/对象 mutation 不需要这个，直接 ownerSession.X.push(...) 即可（引用共享）。
 */
export function setSessionPrimitive(ownerSession, ownerMode, key, value) {
  ownerSession[key] = value
  if (store.agentMode === ownerMode) {
    store[key] = value
  }
}
