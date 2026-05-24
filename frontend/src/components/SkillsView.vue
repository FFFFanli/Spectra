<template>
  <div class="skills-view">
    <div class="skills-header">
      <div class="header-left">
        <button v-if="$store.isMobile" @click="$store.leftDrawerOpen = true" class="mobile-menu-btn">
          <i class="fa-solid fa-bars"></i>
        </button>
        <h2 class="skills-title">技能中心</h2>
        <span class="skills-count">{{ filteredSkills.length }} 个技能</span>
      </div>
    </div>

    <div class="skills-toolbar">
      <div class="search-box">
        <i class="fa-solid fa-search search-icon"></i>
        <input v-model="searchQuery" placeholder="搜索技能..." class="search-input" />
        <button v-if="searchQuery" @click="searchQuery = ''" class="search-clear">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>
      <div class="category-filters">
        <button
          v-for="cat in categories"
          :key="cat"
          @click="activeCategory = activeCategory === cat ? '' : cat"
          :class="['category-chip', { active: activeCategory === cat }]"
        >{{ cat }}</button>
      </div>
    </div>

    <div class="skills-grid">
      <div v-for="skill in filteredSkills" :key="skill.id" class="skill-card">
        <div class="skill-icon-box" :style="{ background: skill.color + '18', color: skill.color }">
          <i :class="skill.icon"></i>
        </div>
        <div class="skill-info">
          <h4 class="skill-name">{{ skill.name }}</h4>
          <p class="skill-desc">{{ skill.desc }}</p>
          <span class="skill-category">{{ skill.category }}</span>
        </div>
      </div>
      <div v-if="filteredSkills.length === 0" class="empty-skills">
        <i class="fa-solid fa-circle-exclamation"></i>
        <span>没有找到匹配的技能</span>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { store } from '../store.js'

export default {
  name: 'SkillsView',
  setup() {
    const searchQuery = ref('')
    const activeCategory = ref('')

    const categories = computed(() => {
      const set = new Set()
      store.availableSkills.forEach(s => set.add(s.category))
      return Array.from(set).sort()
    })

    const filteredSkills = computed(() => {
      let list = store.availableSkills
      if (searchQuery.value) {
        const q = searchQuery.value.toLowerCase()
        list = list.filter(s =>
          s.name.toLowerCase().includes(q) ||
          s.desc.toLowerCase().includes(q) ||
          s.category.toLowerCase().includes(q)
        )
      }
      if (activeCategory.value) {
        list = list.filter(s => s.category === activeCategory.value)
      }
      return list
    })

    return { $store: store, searchQuery, activeCategory, categories, filteredSkills }
  }
}
</script>

<style scoped>
.skills-view {
  flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden;
  background: #f8fafc;
}
.skills-header {
  padding: 14px 20px; border-bottom: 1px solid #e2e8f0;
  display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 12px }
.mobile-menu-btn {
  display: none; background: none; border: none; color: #475569;
  cursor: pointer; font-size: 18px;
}
.skills-title { font-size: 18px; font-weight: 700; color: #1e293b }
.skills-count { font-size: 12px; color: #94a3b8; background: #e2e8f0; padding: 2px 8px; border-radius: 10px }
.skills-toolbar { padding: 16px 20px 12px; flex-shrink: 0 }
.search-box {
  display: flex; align-items: center; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 10px; padding: 8px 12px; gap: 8px; margin-bottom: 12px;
}
.search-icon { color: #94a3b8; font-size: 14px }
.search-input {
  flex: 1; border: none; outline: none; font-size: 13px; color: #1e293b; background: transparent;
}
.search-input::placeholder { color: #94a3b8 }
.search-clear { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 12px }
.category-filters { display: flex; gap: 6px; flex-wrap: wrap }
.category-chip {
  padding: 4px 12px; border-radius: 14px; border: 1px solid #e2e8f0;
  background: #fff; color: #64748b; font-size: 12px; cursor: pointer;
  transition: all 0.15s;
}
.category-chip.active { background: #3b82f6; color: #fff; border-color: #3b82f6 }
.category-chip:hover:not(.active) { background: #f1f5f9 }
.skills-grid {
  flex: 1; overflow-y: auto; padding: 0 20px 20px;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px; align-content: start;
}
.skill-card {
  display: flex; gap: 14px; padding: 16px; background: #fff;
  border: 1px solid #e2e8f0; border-radius: 12px;
  transition: all 0.15s; cursor: default;
}
.skill-card:hover { border-color: #3b82f6; box-shadow: 0 2px 12px rgba(59,130,246,0.08) }
.skill-icon-box {
  width: 44px; height: 44px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
}
.skill-info { min-width: 0 }
.skill-name { font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 4px }
.skill-desc { font-size: 12px; color: #64748b; line-height: 1.5; margin-bottom: 6px }
.skill-category { font-size: 11px; color: #3b82f6; background: #eff6ff; padding: 2px 8px; border-radius: 8px; display: inline-block }
.empty-skills {
  grid-column: 1 / -1; display: flex; flex-direction: column;
  align-items: center; gap: 8px; padding: 48px 0; color: #94a3b8;
}
@media (max-width: 1023px) {
  .mobile-menu-btn { display: block }
  .skills-grid { grid-template-columns: 1fr }
}
@media (prefers-color-scheme: dark) {
  .skills-view { background: #0f172a }
  .skills-header { border-color: #1e293b }
  .skills-title { color: #e2e8f0 }
  .skills-count { background: #1e293b; color: #64748b }
  .search-box { background: #1e293b; border-color: #334155 }
  .search-input { color: #e2e8f0 }
  .category-chip { background: #1e293b; border-color: #334155; color: #94a3b8 }
  .category-chip.active { background: #3b82f6; color: #fff }
  .category-chip:hover:not(.active) { background: #0f172a }
  .skill-card { background: #1e293b; border-color: #334155 }
  .skill-card:hover { border-color: #3b82f6 }
  .skill-name { color: #e2e8f0 }
  .skill-desc { color: #94a3b8 }
  .skill-category { background: #1e3a5f; color: #60a5fa }
}
</style>
