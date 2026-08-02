<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import RobotMark from '@/components/RobotMark.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  error.value = ''
  if (password.value !== confirm.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  submitting.value = true
  try {
    await auth.register(email.value.trim(), password.value)
    await router.replace('/bots')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '注册失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <div class="brand">
        <RobotMark />
        <div>
          <h1>注册账号</h1>
          <p>创建独立工作区，管理你自己的机器人</p>
        </div>
      </div>
      <label class="field">
        <span>邮箱</span>
        <input v-model="email" class="input" type="email" autocomplete="username" required />
      </label>
      <label class="field">
        <span>密码（至少 8 位）</span>
        <input v-model="password" class="input" type="password" autocomplete="new-password" required minlength="8" />
      </label>
      <label class="field">
        <span>确认密码</span>
        <input v-model="confirm" class="input" type="password" autocomplete="new-password" required minlength="8" />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <button class="btn primary" type="submit" :disabled="submitting">{{ submitting ? '注册中…' : '注册并进入' }}</button>
      <p class="switch">已有账号？<RouterLink to="/login">登录</RouterLink></p>
    </form>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(0, 153, 255, 0.16), transparent 55%),
    radial-gradient(900px 420px at 90% 0%, rgba(48, 209, 88, 0.10), transparent 50%),
    linear-gradient(180deg, #eef3f8 0%, #f5f5f7 45%, #f7f7f8 100%);
}
.auth-card {
  width: min(420px, 100%);
  display: grid;
  gap: 14px;
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--shadow-lg);
}
.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 6px; }
.brand h1 { margin: 0; font-size: 22px; letter-spacing: -.02em; }
.brand p { margin: 4px 0 0; color: var(--ink-4); font-size: 13px; }
.field { display: grid; gap: 7px; }
.field span { font-size: 12.5px; font-weight: 700; color: var(--ink-2); }
.error { margin: 0; color: var(--danger); font-size: 13px; }
.switch { margin: 0; text-align: center; color: var(--ink-4); font-size: 13px; }
.switch a { color: var(--accent); font-weight: 700; }
</style>
