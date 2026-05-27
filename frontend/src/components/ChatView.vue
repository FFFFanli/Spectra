<template>
  <!--
    ChatView 现在是路由容器。根据 store.agentMode 渲染对应子组件。
    Solo / Team 共享底层 store 顶层会话字段（messages/threadId/...），
    切换模式时 store.switchAgentMode 把当前会话快照存入 soloSession/teamSession，
    再恢复目标模式的会话。这样两个模式各自保留独立的消息列表与产物。
  -->
  <SoloChatView v-if="$store.agentMode === 'solo'" />
  <TeamChatView v-else-if="$store.agentMode === 'team'" />
</template>

<script>
import { store } from '../store.js'
import SoloChatView from './SoloChatView.vue'
import TeamChatView from './TeamChatView.vue'

export default {
  name: 'ChatView',
  components: { SoloChatView, TeamChatView },
  setup() {
    return { $store: store }
  },
}
</script>
