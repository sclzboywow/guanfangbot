<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type CredentialStatus } from '@/services/api'

const status = ref<CredentialStatus | null>(null)
onMounted(async () => {
  try { status.value = await api.credentialStatus() }
  catch { status.value = null }
})
</script>

<template>
  <section class="page settings-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">项目设置</h1>
        <p class="page-sub">机器人凭证与配置已改为前台管理，服务端仅保留全局 API 地址。</p>
      </div>
    </div>
    <div class="settings-grid">
      <section class="card settings-card">
        <h2 class="section-title">后端连接</h2>
        <div class="setting"><span>API 状态</span><b :class="status ? 'ok' : 'bad'">{{ status ? '已连接' : '连接失败' }}</b></div>
        <div class="setting"><span>已配置机器人</span><b :class="status?.configured ? 'ok' : 'warn'">{{ status?.configured_count ?? 0 }} / {{ status?.total_bots ?? 0 }}</b></div>
        <div class="setting"><span>配置模式</span><b>前台按机器人管理</b></div>
        <div class="setting"><span>OpenAPI Base</span><code>{{ status?.api_base || '—' }}</code></div>
      </section>
      <section class="card settings-card">
        <h2 class="section-title">配置入口</h2>
        <div class="setting"><span>创建机器人</span><RouterLink to="/bots">我的机器人</RouterLink></div>
        <div class="setting"><span>凭证维护</span><span>机器人详情页填写 AppID / AppSecret</span></div>
        <div class="setting"><span>事件订阅</span><RouterLink to="/events">事件与回调</RouterLink></div>
        <div class="setting"><span>OpenAPI</span><RouterLink to="/api-console">API 调试台</RouterLink></div>
      </section>
      <section class="card settings-card wide">
        <h2 class="section-title">对外开放前检查</h2>
        <div class="checklist">
          <label><input type="checkbox" checked disabled />AppSecret 仅服务端保存</label>
          <label><input type="checkbox" checked disabled />前台可管理全部机器人配置</label>
          <label><input type="checkbox" />接入管理台登录与权限</label>
          <label><input type="checkbox" />事件签名校验</label>
          <label><input type="checkbox" checked disabled />配置持久化</label>
          <label><input type="checkbox" />限制 API 调试台权限</label>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.settings-page { max-width: 1000px; }
.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.settings-card { padding: 22px; }
.settings-card.wide { grid-column: 1/-1; }
.setting { display: flex; justify-content: space-between; gap: 12px; padding: 13px 0; border-top: 1px solid var(--line); color: var(--ink-3); }
.setting:first-of-type { margin-top: 15px; }
.setting b, .setting code, .setting a { color: var(--ink); }
.setting a { font-weight: 650; }
.ok { color: #238541 !important; }.bad { color: var(--danger) !important; }.warn { color: var(--warn) !important; }
.checklist { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 18px; }
.checklist label { display: flex; gap: 9px; align-items: center; padding: 12px; border-radius: 12px; background: var(--bg-sunken); }
.checklist input { width: 16px; height: 16px; accent-color: var(--accent); }
@media (max-width: 720px) { .settings-grid, .checklist { grid-template-columns: 1fr; } .settings-card.wide { grid-column: auto; } }
</style>
