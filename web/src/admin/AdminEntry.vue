<template>
  <AdminApp
    v-if="view === 'workspace'"
    :login-configured="loginConfigured"
    :signing-out="busy"
    :session-error="error"
    @sign-out="leaveWorkspace"
  />
  <main v-else class="app-shell admin-entry" aria-labelledby="admin-login-title">
    <header class="admin-entry-header"><p>知识管理</p></header>
    <div class="admin-entry-body">
      <div class="admin-entry-brand">
        <p class="admin-entry-wordmark">陶陶</p>
        <p class="admin-entry-tagline">餐桌手记</p>
        <img class="admin-entry-illustration" :src="loginIllustration" width="720" height="460" alt="" aria-hidden="true" />
      </div>

      <section class="admin-entry-content">
        <h1 id="admin-login-title" ref="title" tabindex="-1">后台登录</h1>
        <template v-if="view === 'login'">
          <p>输入管理员密码，进入知识管理后台。</p>
          <form :aria-busy="busy" @submit.prevent="enterWorkspace">
            <div class="admin-field">
              <label class="sr-only" for="admin-password">管理员密码</label>
              <div class="admin-entry-password">
                <input
                  id="admin-password"
                  ref="passwordInput"
                  v-model="password"
                  :type="showPassword ? 'text' : 'password'"
                  name="password"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                  maxlength="256"
                  required
                  :readonly="busy"
                  :aria-invalid="invalidPassword || undefined"
                  :aria-describedby="error ? 'admin-login-error' : undefined"
                  @input="clearLoginError"
                />
                <button
                  class="admin-text-button admin-entry-visibility"
                  type="button"
                  aria-controls="admin-password"
                  @click="showPassword = !showPassword"
                >
                  {{ showPassword ? "隐藏密码" : "显示密码" }}
                </button>
              </div>
            </div>
            <p v-if="error" id="admin-login-error" class="admin-error" role="alert">{{ error }}</p>
            <button class="admin-primary admin-entry-submit" type="submit" :disabled="busy">
              {{ busy ? "正在登录…" : "登录" }}
            </button>
          </form>
        </template>
        <p v-else-if="view === 'checking'" role="status">正在检查登录状态…</p>
        <template v-else>
          <p class="admin-error" role="alert">{{ error }}</p>
          <button class="admin-secondary" type="button" @click="checkSession">重新连接</button>
        </template>
        <a class="admin-entry-back" href="/"><UiIcon name="back" />回到餐桌手记</a>
      </section>
    </div>
    <footer class="admin-entry-footer"><span>taotao</span><p>知识管理后台</p></footer>
  </main>
</template>

<script setup lang="ts">
import axios from "axios";
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import UiIcon from "../components/UiIcon.vue";
import loginIllustration from "../assets/admin-knowledge-illustration.svg";
import AdminApp from "./AdminApp.vue";
import { isCancelled, observeSessionExpiry, readAdminSession, signIn, signOut } from "./api";

const view = ref<"checking" | "login" | "workspace" | "unavailable">("checking");
const loginConfigured = ref(false);
const busy = ref(false);
const error = ref("");
const invalidPassword = ref(false);
const password = ref("");
const showPassword = ref(false);
const title = ref<HTMLElement | null>(null);
const passwordInput = ref<HTMLInputElement | null>(null);
const controller = new AbortController();

function clearLoginError(): void {
  error.value = "";
  invalidPassword.value = false;
}

async function showLogin(message = "", focusTitle = true): Promise<void> {
  password.value = "";
  showPassword.value = false;
  invalidPassword.value = false;
  error.value = message;
  view.value = "login";
  if (focusTitle) {
    await nextTick();
    title.value?.focus();
  }
}

async function checkSession(): Promise<void> {
  view.value = "checking";
  error.value = "";
  try {
    const session = await readAdminSession(controller.signal);
    loginConfigured.value = session.configured;
    if (session.configured && !session.authenticated) {
      await showLogin("", false);
    } else {
      view.value = "workspace";
    }
  } catch (cause) {
    if (isCancelled(cause)) return;
    error.value = "暂时无法连接后台，请稍后重试。";
    view.value = "unavailable";
    await nextTick();
    title.value?.focus();
  }
}

async function enterWorkspace(): Promise<void> {
  if (busy.value) return;
  clearLoginError();
  busy.value = true;
  try {
    await signIn(password.value, controller.signal);
    password.value = "";
    showPassword.value = false;
    view.value = "workspace";
    await nextTick();
    document.getElementById("admin-title")?.focus();
  } catch (cause) {
    if (isCancelled(cause)) return;
    invalidPassword.value = axios.isAxiosError(cause) && cause.response?.status === 401;
    error.value = invalidPassword.value
      ? "密码不正确，请重新输入。"
      : "暂时无法登录，请稍后重试。";
    if (invalidPassword.value) {
      passwordInput.value?.focus();
      passwordInput.value?.select();
    }
  } finally {
    busy.value = false;
  }
}

async function leaveWorkspace(): Promise<void> {
  if (busy.value) return;
  error.value = "";
  busy.value = true;
  try {
    await signOut(controller.signal);
    await showLogin();
  } catch (cause) {
    if (!isCancelled(cause)) error.value = "退出失败，请稍后重试。";
  } finally {
    busy.value = false;
  }
}

const stopObserving = observeSessionExpiry(() => {
  if (view.value === "workspace" && loginConfigured.value) {
    void showLogin("登录已过期，请重新登录。");
  }
});

onMounted(checkSession);
onBeforeUnmount(() => {
  controller.abort();
  stopObserving();
});
</script>

<style scoped lang="scss">
@font-face {
  font-family: "Admin Serif";
  src: url("../assets/fonts/admin-serif.ttf") format("truetype");
  font-weight: 400;
  font-display: swap;
}

@font-face {
  font-family: "Admin Serif";
  src: url("../assets/fonts/admin-serif-semibold.ttf") format("truetype");
  font-weight: 600;
  font-display: swap;
}

@font-face {
  font-family: "Admin Latin";
  src: url("../assets/fonts/admin-latin.ttf") format("truetype");
  font-weight: 400;
  font-display: swap;
}

.admin-entry {
  --paper: #f7f5f0;
  --ink: #25253c;
  --muted: #686675;
  --clay: #25253c;
  --clay-hover: #3d3b55;
  --line: #ceccd0;
  --control-line: #907580;
  --serif: "Admin Serif", "Table Serif", "Songti SC", serif;
  display: grid;
  grid-template-rows: 80px minmax(0, 1fr) 80px;
  width: 100%;
  min-height: 100dvh;
  max-width: 1440px;
  margin-inline: auto;
  padding-inline: clamp(24px, 6.12vw, 88px);
  color: var(--ink);
  background: var(--paper);
  font-family: var(--sans);
}

.admin-entry-header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--ink);
}

.admin-entry-header p {
  margin: 0;
  font: 400 17px/1.5 var(--serif);
  letter-spacing: 0.22em;
}

.admin-entry-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
  align-items: center;
  gap: clamp(48px, 7vw, 100px);
  padding: 36px 24px 48px 0;
}

.admin-entry-brand {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: end;
  gap: 16px 24px;
  min-width: 0;
}

.admin-entry-wordmark {
  margin: 0;
  font: 400 clamp(64px, 6.1vw, 88px)/1.15 var(--serif);
  letter-spacing: -0.055em;
}

.admin-entry-tagline {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 0 0 12px;
  font: 400 16px/1.5 var(--serif);
  letter-spacing: 0.16em;
}

.admin-entry-tagline::before {
  width: 26px;
  height: 1px;
  content: "";
  background: var(--control-line);
}

.admin-entry-illustration {
  grid-column: 1 / -1;
  display: block;
  width: 100%;
  max-height: 360px;
  height: auto;
  object-fit: contain;
}

.admin-entry-content {
  width: 100%;
  max-width: 380px;
  min-width: 0;
}

.admin-entry-content h1 {
  margin: 0 0 16px;
  font: 600 30px/1.4 var(--serif);
  letter-spacing: 0.04em;
}

.admin-entry-content > p:not(.admin-error) {
  margin: 0 0 24px;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.8;
}

.admin-entry-password {
  display: flex;
  align-items: center;
  height: 52px;
  border-bottom: 1px solid var(--ink);
  transition: box-shadow var(--duration) var(--ease);
}

.admin-entry-password:focus-within {
  box-shadow: 0 1px 0 var(--ink);
}

.admin-entry-content .admin-field {
  gap: 13px;
  margin-bottom: 22px;
  color: var(--ink);
  font-size: 15px;
  font-weight: 400;
  line-height: 1.5;
}

.admin-entry-content .admin-field input {
  width: 100%;
  min-height: 0;
  height: 100%;
  padding: 0 15px 0 0;
  border: 0;
  border-radius: 0;
  outline: 0;
  color: var(--ink);
  background: transparent;
  font-size: 16px;
  letter-spacing: 0.05em;
}

.admin-entry-content input::placeholder {
  color: var(--muted);
  font-size: 16px;
  letter-spacing: 0;
}

.admin-entry-visibility {
  flex: 0 0 auto;
  min-height: 44px;
  padding: 0;
  color: var(--muted);
  font-size: 16px;
}

.admin-entry-submit {
  width: 100%;
  min-height: 52px;
  padding-inline: 16px;
  border: 1px solid var(--ink);
  border-radius: 0;
  font: 600 16px/1.5 var(--serif);
  letter-spacing: 0.35em;
  text-indent: 0.35em;
}

.admin-entry-submit:disabled {
  opacity: 0.75;
}

.admin-entry-back {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 44px;
  margin-top: 20px;
  color: var(--muted);
  font-size: 14px;
  text-decoration: none;
}

.admin-entry-back .ui-icon {
  width: 20px;
  height: 20px;
  color: var(--control-line);
}

.admin-entry-content .admin-error {
  color: var(--ink);
  border-color: var(--control-line);
  background: #edebf1;
}

.admin-entry-footer {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  min-height: 80px;
  padding-top: 24px;
  border-top: 1px solid var(--line);
}

.admin-entry-footer > span {
  font: 400 22px/1 "Admin Latin", serif;
  letter-spacing: 0.15em;
}

.admin-entry-footer p {
  margin: 0;
  color: var(--muted);
  font: 400 14px/1.5 var(--serif);
  letter-spacing: 0.12em;
}

@media (min-width: 801px) and (max-height: 800px) {
  .admin-entry { grid-template-rows: 64px minmax(0, 1fr) 64px; }
  .admin-entry-body { padding-block: 24px; }
  .admin-entry-illustration { max-height: 290px; }
  .admin-entry-footer { min-height: 64px; padding-top: 18px; }
}

@media (max-width: 800px) {
  .admin-entry {
    grid-template-rows: 64px minmax(0, 1fr) 64px;
    padding-inline: 24px;
  }

  .admin-entry-header p { font-size: 15px; }

  .admin-entry-body {
    width: 100%;
    max-width: 440px;
    grid-template-columns: minmax(0, 1fr);
    align-content: center;
    gap: 28px;
    margin-inline: auto;
    padding: 28px 0 32px;
  }

  .admin-entry-brand { gap: 8px 20px; }
  .admin-entry-wordmark { font-size: 56px; }
  .admin-entry-tagline { margin-bottom: 7px; font-size: 15px; }
  .admin-entry-illustration { height: 180px; }
  .admin-entry-content { justify-self: center; }

  .admin-entry-content h1 {
    margin-bottom: 12px;
    font-size: 26px;
  }

  .admin-entry-content > p:not(.admin-error) { margin-bottom: 22px; }
  .admin-entry-footer { min-height: 64px; padding-top: 18px; }
  .admin-entry-footer p { font-size: 13px; }
}

@media (max-width: 480px) {
  .admin-entry-body { align-content: start; gap: 24px; padding-top: 22px; }
  .admin-entry-wordmark { font-size: 44px; }
  .admin-entry-brand { gap: 6px 18px; }
  .admin-entry-tagline { gap: 12px; margin-bottom: 5px; font-size: 14px; }
  .admin-entry-tagline::before { width: 22px; }
  .admin-entry-illustration { height: 150px; }
  .admin-entry-content h1 { font-size: 25px; }
}
</style>
