import { reactive, ref } from 'vue'

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
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
