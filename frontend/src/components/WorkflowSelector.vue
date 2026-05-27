<template>
  <div v-if="$store.agentMode === 'team'" class="workflow-selector">
    <button
      v-for="wf in workflows"
      :key="wf.id"
      :class="['wf-btn', { active: selectedId === wf.id }]"
      @click="selectWorkflow(wf)"
      :title="wf.description"
    >
      {{ wf.title }}
    </button>
    <button
      v-if="workflows.length === 0"
      class="wf-btn loading"
      disabled
    >
      加载模板中...
    </button>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { store } from '../store.js'
import { apiFetch } from '../utils/sse.js'

export default {
  name: 'WorkflowSelector',
  setup() {
    const workflows = ref([])
    const selectedId = ref(null)

    onMounted(async () => {
      try {
        const res = await apiFetch('/api/v2/workflows')
        const data = await res.json()
        if (data.workflows) {
          workflows.value = data.workflows
        }
      } catch (e) {
        console.warn('加载工作流模板失败:', e)
      }
    })

    function selectWorkflow(wf) {
      selectedId.value = wf.id
      store.userInput = wf.title
      // 将 skill_workflow_id 暂时存到 store，发送时附带
      store._skillWorkflowId = wf.id
    }

    return { workflows, selectedId, selectWorkflow }
  },
}
</script>

<style scoped>
.workflow-selector {
  display: flex; gap: 4px; flex-wrap: wrap;
  padding: 6px 12px;
  border-top: 1px solid #f1f5f9;
}
.wf-btn {
  padding: 3px 10px; border-radius: 12px; border: 1px solid #e2e8f0;
  background: #ffffff; color: #64748b; font-size: 11px; cursor: pointer;
  transition: all 0.15s;
}
.wf-btn:hover { border-color: #8b5cf6; color: #8b5cf6; }
.wf-btn.active { background: #ede9fe; border-color: #8b5cf6; color: #6d28d9; }
.wf-btn.loading { opacity: 0.5; cursor: not-allowed; }

@media (prefers-color-scheme: dark) {
  .workflow-selector { border-color: #1e293b; }
  .wf-btn { border-color: #334155; background: #0f172a; color: #94a3b8; }
  .wf-btn:hover { border-color: #a78bfa; color: #a78bfa; }
  .wf-btn.active { background: #4c1d95; border-color: #a78bfa; color: #c4b5fd; }
}
</style>
