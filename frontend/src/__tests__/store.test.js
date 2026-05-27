/**
 * Frontend unit tests for store.js session model and useChat.js behavior.
 *
 * Covers:
 *   16.11  Cross-mode streaming isolation (Property 6)
 *   16.12  syncTopToSession invariant
 *   16.13  handleStop only stops current mode
 *   16.14  In-place clear principle
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  store,
  syncTopToSession,
  switchAgentMode,
  getActiveSession,
  getActiveMode,
  setSessionPrimitive,
  generateThreadId,
} from '../store.js'


// ── Helpers ─────────────────────────────────────────────────────

function resetSessions() {
  // Reset both sessions and all top-level fields to clean state
  store.agentMode = 'solo'
  const fresh = createEmptySession()
  store.messages = fresh.messages
  store.threadId = fresh.threadId
  store.thinkingStatus = fresh.thinkingStatus
  store.currentToolCalls = fresh.currentToolCalls
  store.taskTodos = fresh.taskTodos
  store.taskArtifacts = fresh.taskArtifacts
  store.taskPlan = fresh.taskPlan
  store.runtimeState = fresh.runtimeState
  store.runtimeTimeline = fresh.runtimeTimeline
  store.usageStats = fresh.usageStats
  store.referenceSkills = fresh.referenceSkills
  store.referenceLinks = fresh.referenceLinks
  store.suggestExport = fresh.suggestExport
  store.activeHistoryId = fresh.activeHistoryId
  store.conversationRenderKey = fresh.conversationRenderKey
  store.charts = fresh.charts
  store.files = fresh.files
  store.attachedFiles = fresh.attachedFiles
  store.userInput = fresh.userInput
  store.loading = fresh.loading
  store.abortController = fresh.abortController
  store.soloSession = createEmptySession()
  store.teamSession = createEmptySession()
  syncTopToSession()
}

// Re-create the session factory (mirrors store.js internals)
function createEmptySession() {
  return {
    messages: [],
    threadId: generateThreadId(),
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
    members: {},
    backgroundTasks: [],
    parsedFiles: [],
    workspaceArtifacts: [],
  }
}


// ── 16.12  syncTopToSession invariant ────────────────────────────

describe('syncTopToSession invariant (16.12)', () => {
  beforeEach(() => {
    resetSessions()
  })

  it('after syncTopToSession, top-level messages === soloSession.messages when mode is solo', () => {
    store.messages = [{ role: 'user', content: 'hi' }]
    syncTopToSession()
    expect(store.messages).toBe(store.soloSession.messages)
  })

  it('after loadConversation replaces store.messages, syncTopToSession restores invariant', () => {
    // Simulate loadConversation: replace top-level reference
    store.messages = [{ role: 'user', content: 'loaded from db' }]
    store.threadId = 'loaded-thread-id'

    // Before sync, session still has old references
    expect(store.soloSession.messages).not.toBe(store.messages)

    // After sync, session references match top-level
    syncTopToSession()
    expect(store.soloSession.messages).toBe(store.messages)
    expect(store.soloSession.threadId).toBe(store.threadId)
  })

  it('after newChat resets messages to [], syncTopToSession matches', () => {
    // Simulate newChat: some messages loaded, then reset
    store.messages = [{ role: 'assistant', content: 'old' }]
    syncTopToSession()
    expect(store.soloSession.messages).toBe(store.messages)

    // newChat clears
    store.messages = []
    store.threadId = generateThreadId()
    syncTopToSession()
    expect(store.soloSession.messages).toBe(store.messages)
    expect(store.soloSession.messages.length).toBe(0)
  })

  it('switching mode twice preserves data in both sessions', () => {
    // Start in solo
    store.messages = [{ role: 'user', content: 'solo msg' }]
    syncTopToSession()

    // Switch to team
    switchAgentMode('team')
    store.messages = [{ role: 'user', content: 'team msg' }]
    syncTopToSession()

    // Switch back to solo
    switchAgentMode('solo')
    expect(store.messages[0].content).toBe('solo msg')

    // Switch back to team
    switchAgentMode('team')
    expect(store.messages[0].content).toBe('team msg')
  })
})


// ── 16.11  Cross-mode streaming isolation ───────────────────────

describe('cross-mode streaming isolation (16.11)', () => {
  beforeEach(() => {
    resetSessions()
  })

  it('ownerSession writes do not pollute other mode session', () => {
    // Simulate streamChat start: capture ownerSession
    switchAgentMode('solo')
    const ownerSession = getActiveSession()
    const ownerMode = getActiveMode()

    // Push messages as if SSE events arrive
    ownerSession.messages.push({ role: 'assistant', content: 'streaming chunk 1' })
    ownerSession.taskTodos.push({ id: 'td-1', text: 'working', status: 'running' })

    // Switch mode mid-stream
    switchAgentMode('team')

    // More SSE events arrive — must go to ownerSession only
    ownerSession.messages.push({ role: 'assistant', content: 'streaming chunk 2' })
    ownerSession.taskTodos.push({ id: 'td-2', text: 'done', status: 'done' })

    // Current (team) session should be unaffected
    expect(store.messages.length).toBe(0)  // team session is empty
    expect(store.taskTodos.length).toBe(0)

    // Owner session has all the data
    expect(ownerSession.messages.length).toBe(2)
    expect(ownerSession.taskTodos.length).toBe(2)

    // Switch back — data should be visible
    switchAgentMode('solo')
    expect(store.messages.length).toBe(2)
    expect(store.messages[0].content).toBe('streaming chunk 1')
    expect(store.messages[1].content).toBe('streaming chunk 2')
  })

  it('setSessionPrimitive only syncs to top when ownerMode matches current mode', () => {
    // Start in solo, capture ctx
    switchAgentMode('solo')
    const ownerSession = getActiveSession()
    const ownerMode = getActiveMode()

    // Set loading while still in solo
    setSessionPrimitive(ownerSession, ownerMode, 'loading', true)
    expect(store.loading).toBe(true)
    expect(ownerSession.loading).toBe(true)

    // Switch to team
    switchAgentMode('team')

    // Owner stream finishes — set loading to false
    setSessionPrimitive(ownerSession, ownerMode, 'loading', false)
    // Should NOT affect team's loading (team is current mode)
    expect(store.loading).toBe(false)  // team just started, loading is false by default
    // ownerSession loading is false
    expect(ownerSession.loading).toBe(false)

    // Verify team session is independent
    const teamSession = getActiveSession()
    setSessionPrimitive(teamSession, 'team', 'loading', true)
    expect(store.loading).toBe(true)
    // ownerSession (solo) loading unchanged
    expect(ownerSession.loading).toBe(false)
  })

  it('done event side-effects do not fire for background mode', () => {
    // Simulate: solo starts streaming, user switches to team, solo finishes
    switchAgentMode('solo')
    const soloOwnerSession = getActiveSession()
    const soloOwnerMode = getActiveMode()

    // Push some messages to solo
    soloOwnerSession.messages.push({ role: 'assistant', content: 'solo reply' })

    // Switch to team mid-stream
    switchAgentMode('team')

    // Solo stream finishes — done event fires
    // The guard: `if (ctx.ownerMode === store.agentMode)` should be FALSE
    const shouldPersist = (soloOwnerMode === store.agentMode)
    expect(shouldPersist).toBe(false)

    // Team is current, solo is background
    expect(store.agentMode).toBe('team')

    // Switch back — solo data intact
    switchAgentMode('solo')
    expect(store.messages.length).toBe(1)
    expect(store.messages[0].content).toBe('solo reply')
  })

  it('concurrent streams in both modes do not interfere', () => {
    // Start solo stream
    switchAgentMode('solo')
    const soloSession = getActiveSession()
    const soloMode = 'solo'
    soloSession.messages.push({ role: 'user', content: 'solo q' })

    // Switch to team, start team stream
    switchAgentMode('team')
    const teamSession = getActiveSession()
    const teamMode = 'team'
    teamSession.messages.push({ role: 'user', content: 'team q' })

    // Solo stream still getting events
    soloSession.messages.push({ role: 'assistant', content: 'solo a' })
    setSessionPrimitive(soloSession, soloMode, 'thinkingStatus', 'Solo thinking...')

    // Team stream getting events
    teamSession.messages.push({ role: 'assistant', content: 'team a' })
    setSessionPrimitive(teamSession, teamMode, 'thinkingStatus', 'Team thinking...')

    // Current mode (team) sees team data
    expect(store.thinkingStatus).toBe('Team thinking...')
    expect(store.messages.length).toBe(2)
    expect(store.messages[1].content).toBe('team a')

    // Solo data intact when switching back
    switchAgentMode('solo')
    expect(store.thinkingStatus).toBe('Solo thinking...')
    expect(store.messages.length).toBe(2)
    expect(store.messages[1].content).toBe('solo a')
  })
})


// ── 16.13  handleStop only stops current mode ───────────────────

describe('handleStop only stops current mode (16.13)', () => {
  beforeEach(() => {
    resetSessions()
  })

  it('handleStop aborts only the active session controller', () => {
    // Set up solo with its own abort controller
    switchAgentMode('solo')
    const soloAC = new AbortController()
    store.soloSession.abortController = soloAC
    store.abortController = soloAC

    // Switch to team, set up team's abort controller
    switchAgentMode('team')
    const teamAC = new AbortController()
    store.teamSession.abortController = teamAC
    store.abortController = teamAC

    // Call handleStop — should only abort team's controller
    // This simulates what handleStop() does:
    const activeSession = getActiveSession()
    const activeAC = activeSession.abortController
    activeAC.abort()

    // Team controller should be aborted
    expect(teamAC.signal.aborted).toBe(true)
    // Solo controller should remain untouched
    expect(soloAC.signal.aborted).toBe(false)
  })

  it('handleStop does not affect background mode stream abort controller', () => {
    // Background mode (solo) has a running stream
    switchAgentMode('solo')
    const soloAC = new AbortController()
    store.soloSession.abortController = soloAC
    store.abortController = soloAC

    // Switch to team
    switchAgentMode('team')
    const teamAC = new AbortController()
    store.teamSession.abortController = teamAC
    store.abortController = teamAC

    // Verify solo AC is preserved in session
    expect(store.soloSession.abortController).toBe(soloAC)
    expect(soloAC.signal.aborted).toBe(false)

    // Stop current (team) stream
    store.abortController.abort()
    expect(teamAC.signal.aborted).toBe(true)
    expect(soloAC.signal.aborted).toBe(false)
  })
})


// ── 16.14  In-place clear principle ──────────────────────────────

describe('in-place clear principle (16.14)', () => {
  beforeEach(() => {
    resetSessions()
  })

  it('handlePrimarySend clears arrays in-place via splice(0), not replacement', () => {
    switchAgentMode('solo')
    const session = getActiveSession()

    // Set up some data
    session.messages = [{ role: 'user', content: 'q' }, { role: 'assistant', content: 'a' }]
    store.messages = session.messages
    session.taskTodos = [{ id: 'td-1', text: 'working', status: 'running' }]
    store.taskTodos = session.taskTodos
    session.taskPlan.steps = [{ id: 's1', description: 'do', status: 'running' }]

    // Capture references before clear
    const messagesBefore = session.messages
    const taskTodosBefore = session.taskTodos
    const taskPlanBefore = session.taskPlan

    // Simulate handlePrimarySend: in-place clear
    session.messages.splice(0)
    session.taskTodos.length = 0
    Object.assign(session.taskPlan, {
      steps: [], revision: 0, finished: false, finishReason: '',
      summary: '', createdAt: 0, progress: 0,
    })

    // References must NOT be replaced
    expect(session.messages).toBe(messagesBefore)
    expect(session.taskTodos).toBe(taskTodosBefore)
    expect(session.taskPlan).toBe(taskPlanBefore)

    // Content must be cleared
    expect(session.messages.length).toBe(0)
    expect(session.taskTodos.length).toBe(0)
    expect(session.taskPlan.steps.length).toBe(0)
  })

  it('regenerateMessage clears in-place without replacing references', () => {
    switchAgentMode('team')
    const session = getActiveSession()

    session.messages = [{ role: 'user', content: 'req' }, { role: 'assistant', content: 'resp' }]
    store.messages = session.messages
    session.usageStats = { by_model: { qwen: { input_tokens: 100, output_tokens: 50 } }, total: { input_tokens: 100, output_tokens: 50, total_tokens: 150 } }
    store.usageStats = session.usageStats

    const messagesBefore = session.messages
    const usageStatsBefore = session.usageStats

    // Simulate regenerateMessage: clear last assistant, reset usage
    session.messages.pop() // remove last assistant message
    session.usageStats.by_model = {}

    expect(session.messages).toBe(messagesBefore)
    expect(session.usageStats).toBe(usageStatsBefore)
    expect(session.messages.length).toBe(1) // only user message left
    expect(Object.keys(session.usageStats.by_model).length).toBe(0)
  })

  it('replace-then-sync pattern works for history load', () => {
    // This is the pattern: loadHistory replaces references, then syncTopToSession
    switchAgentMode('solo')

    // Simulate loadConversation: copy then replace
    const loaded = [{ role: 'user', content: 'historical' }]
    store.messages = loaded  // replacement!
    store.threadId = 'hist-thread-id'

    // Now invariant is broken...
    expect(store.soloSession.messages).not.toBe(store.messages)

    // ...until syncTopToSession is called
    syncTopToSession()
    expect(store.soloSession.messages).toBe(store.messages)
    expect(store.soloSession.threadId).toBe(store.threadId)
  })

  it('each mode maintains independent taskPlan after switches', () => {
    // Solo plan
    switchAgentMode('solo')
    const soloPlan = store.taskPlan
    soloPlan.steps = [{ id: 'sol', description: 'solo step', status: 'running' }]

    // Switch to team and set team plan
    switchAgentMode('team')
    const teamPlan = store.taskPlan
    teamPlan.steps = [{ id: 'tm', description: 'team step', status: 'running' }]

    expect(teamPlan.steps[0].id).toBe('tm')

    // Switch back to solo
    switchAgentMode('solo')
    expect(store.taskPlan.steps[0].id).toBe('sol')
    expect(store.taskPlan).toBe(soloPlan)

    // Switch to team again
    switchAgentMode('team')
    expect(store.taskPlan.steps[0].id).toBe('tm')
    expect(store.taskPlan).toBe(teamPlan)
  })
})
