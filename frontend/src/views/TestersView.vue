<script setup lang="ts">
import { ref } from 'vue'
const query = ref('')
const testers = ref<{ id: string; name: string; type: string; color: string }[]>([])
function remove(id: string) { testers.value = testers.value.filter(item => item.id !== id) }
const filtered = () => testers.value.filter(t => !query.value || `${t.name}${t.id}`.includes(query.value))
</script>

<template>
  <section class="page testers-page">
    <div class="page-head"><div><h1 class="page-title">开发者测试</h1><p class="page-sub">管理本地测试成员和场景。真实测试资格仍需在 QQ 开放平台配置。</p></div><button class="btn primary" disabled>添加测试成员</button></div>
    <section class="card tester-card">
      <div class="tester-head"><div><h2 class="section-title">测试成员</h2><p class="section-sub">暂无测试成员，可在接入后添加。</p></div><input v-model="query" class="input search" placeholder="搜索名称或 ID" /></div>
      <div v-if="filtered().length === 0" class="empty">暂无测试成员</div>
      <div v-else class="tester-list">
        <div v-for="tester in filtered()" :key="tester.id" class="tester-row">
          <div class="avatar" :style="{ background: tester.color }">{{ tester.name.slice(-1) }}</div>
          <div class="tester-main"><strong>{{ tester.name }}</strong><span class="mono">QQ {{ tester.id }}</span></div>
          <span class="type-tag">{{ tester.type }}</span>
          <button class="remove" @click="remove(tester.id)">移除</button>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.testers-page { max-width: 980px; }
.tester-card { padding: 22px; }
.tester-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.search { width: 240px; }
.empty { margin-top: 18px; padding: 28px 12px; border: 1px dashed var(--line); border-radius: 12px; text-align: center; color: var(--ink-4); font-size: 13px; }
.tester-list { margin-top: 18px; }
.tester-row { display: flex; align-items: center; gap: 12px; padding: 13px 4px; border-top: 1px solid var(--line); }
.avatar { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 50%; color: white; font-weight: 800; }
.tester-main { flex: 1; min-width: 0; }
.tester-main strong, .tester-main span { display: block; }
.tester-main span { margin-top: 3px; color: var(--ink-4); font-size: 11px; }
.type-tag { padding: 5px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-size: 11px; font-weight: 700; }
.remove { padding: 6px 10px; border: 0; border-radius: 8px; background: rgba(255,59,48,.08); color: var(--danger); font-weight: 650; }
@media (max-width: 650px) { .tester-head { flex-direction: column; } .search { width: 100%; } .type-tag { display: none; } }
</style>
