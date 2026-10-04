<template>
  <div class="mb-12">
    <p class="mb-1 font-semibold">{{ t('settings.theme') }}</p>
    <div class="flex items-center space-x-4">
      <div
        v-for="item in theme.themes"
        :key="item.id"
        class="cursor-pointer"
        role="button"
        @click="theme.set(item.id)"
      >
        <div
          :class="{ 'ring ring-accent': item.id === theme.activeTheme.value }"
          class="rounded-lg p-0.5"
        >
          <img
            :src="require(`@/assets/images/theme-${item.id}.png`)"
            width="140"
            class="rounded-lg"
          />
        </div>
        <span class="ml-1 text-sm text-gray-600 dark:text-gray-200">
          {{ item.name }}
        </span>
      </div>
    </div>
  </div>
  <div class="flex items-center">
    <div id="languages">
      <p class="mb-1 font-semibold">{{ t('settings.language.label') }}</p>
      <ui-select
        :model-value="settings.locale"
        class="w-80"
        @change="updateLanguage"
      >
        <option
          v-for="locale in supportLocales"
          :key="locale.id"
          :value="locale.id"
        >
          {{ locale.name }}
        </option>
      </ui-select>
      <a
        class="ml-1 block text-gray-600 dark:text-gray-200"
        href="https://github.com/AutomaApp/automa/wiki/Help-Translate"
        target="_blank"
        rel="noopener"
      >
        {{ t('settings.language.helpTranslate') }}
      </a>
    </div>
    <p v-if="isLangChange" class="ml-4 inline-block">
      {{ t('settings.language.reloadPage') }}
    </p>
  </div>
  <div id="delete-logs" class="mt-12">
    <p class="mb-1 font-semibold">工作流日志</p>
    <div class="flex items-center">
      <ui-select
        :model-value="settings.deleteLogAfter"
        :label="t('settings.deleteLog.title')"
        placeholder="Delete after"
        class="w-80"
        @change="
          updateSetting(
            'deleteLogAfter',
            $event === 'never' ? 'never' : +$event
          )
        "
      >
        <option v-for="day in deleteLogDays" :key="day" :value="day">
          <template v-if="typeof day === 'string'">
            {{ t('settings.deleteLog.deleteAfter.never') }}
          </template>
          <template v-else>
            {{ t('settings.deleteLog.deleteAfter.days', { day }) }}
          </template>
        </option>
      </ui-select>
      <ui-input
        :model-value="settings.logsLimit"
        class="ml-4"
        type="number"
        label="日志上限"
        min="10"
        @change="updateSetting('logsLimit', +$event <= 0 ? 1000 : +$event)"
      />
    </div>
  </div>
  <div id="theme-color" class="mt-12">
    <p class="mb-1 font-semibold">主题颜色（按钮/侧边栏等强调色）</p>
    <p class="mb-2 text-sm text-gray-600 dark:text-gray-200">
      选择预设色或自定义拾色，保存后立即生效
    </p>
    <div class="flex items-center gap-3">
      <button
        v-for="color in accentPresets"
        :key="color"
        :style="{ backgroundColor: color }"
        :class="{
          'ring-2 ring-gray-900 ring-offset-2 dark:ring-gray-100':
            accentColor === color,
        }"
        class="h-8 w-8 rounded-full border border-gray-200 dark:border-gray-600"
        :title="color"
        @click="applyAccentColor(color)"
      />
      <input
        type="color"
        :value="accentColor"
        class="h-8 w-12 cursor-pointer rounded border border-gray-200 bg-transparent dark:border-gray-600"
        title="自定义颜色"
        @change="applyAccentColor($event.target.value)"
      />
    </div>
  </div>
  <popup-wallpaper />
  <div id="python-bridge" class="mt-12">
    <p class="mb-1 font-semibold">Python 桥接（本机执行 Python 代码块）</p>
    <p class="mb-2 text-sm text-gray-600 dark:text-gray-200">
      先在本机启动桥接服务：<code>python3 automa-bridge/server.py</code>， token
      自动生成于 <code>~/.automa-bridge/token</code>，把文件内容粘贴到下面。
    </p>
    <div class="flex items-start">
      <div class="w-80 space-y-2">
        <ui-input
          :model-value="bridgeConfig.token"
          type="password"
          label="Token"
          placeholder="粘贴 ~/.automa-bridge/token 的内容"
          @change="updateBridgeConfig({ token: $event.trim() })"
        />
        <ui-input
          :model-value="bridgeConfig.port"
          type="number"
          label="端口（默认 27182）"
          @change="updateBridgeConfig({ port: +$event || 27182 })"
        />
      </div>
      <div class="ml-4">
        <ui-button
          variant="accent"
          :disabled="state.pinging"
          @click="pingBridgeAction"
        >
          {{ state.pinging ? '测试中...' : '测试连接' }}
        </ui-button>
        <p v-if="state.pingResult" class="mt-2 text-sm">
          {{ state.pingResult }}
        </p>
      </div>
    </div>
  </div>
  <div id="ai-channel" class="mt-12">
    <p class="mb-1 font-semibold">AI 工作流通道（Yuze Harness 远程管理）</p>
    <p class="mb-2 text-sm text-gray-600 dark:text-gray-200">
      开启后扩展会轮询本机桥的指令队列，AI
      可远程导入工作流、触发执行并读取结果。复用上方桥接配置，需先启动桥接服务。
    </p>
    <label class="flex cursor-pointer items-center space-x-2">
      <ui-switch :model-value="aiChannelEnabled" @change="toggleAiChannel" />
      <span class="text-sm">{{ aiChannelEnabled ? '已开启' : '已关闭' }}</span>
    </label>
  </div>
  <div id="ai-chat" class="mt-12">
    <p class="mb-1 font-semibold">
      AI 服务（OpenAI 兼容，供「AI 问答」块使用）
    </p>
    <p class="mb-2 text-sm text-gray-600 dark:text-gray-200">
      选择厂商自动填 API 地址与推荐模型，也可选「自定义」手填任意 OpenAI
      兼容服务
    </p>
    <div class="w-80 space-y-2">
      <ui-select
        :model-value="state.aiProvider"
        label="模型厂商"
        class="w-full"
        @change="selectAiProvider($event)"
      >
        <option v-for="p in aiProviders" :key="p.label" :value="p.label">
          {{ p.label }}
        </option>
      </ui-select>
      <ui-input
        :model-value="aiChatConfig.baseUrl"
        label="API 地址（不含 /chat/completions）"
        :placeholder="state.aiProviderPlaceholder"
        @change="
          updateAiChatConfig({ baseUrl: $event.trim().replace(/\/+$/, '') })
        "
      />
      <ui-input
        :model-value="aiChatConfig.apiKey"
        type="password"
        label="API Key"
        placeholder="sk-..."
        @change="updateAiChatConfig({ apiKey: $event.trim() })"
      />
      <ui-input
        :model-value="aiChatConfig.model"
        label="默认模型"
        :placeholder="state.aiModelPlaceholder"
        @change="updateAiChatConfig({ model: $event.trim() })"
      />
    </div>
  </div>
</template>
<script setup>
import { computed, reactive, ref, onMounted } from 'vue';
import { useI18n } from 'vue-i18n';
import { useToast } from 'vue-toastification';
import { useStore } from '@/stores/main';
import { useTheme } from '@/composable/theme';
import { supportLocales } from '@/utils/shared';
import {
  getBridgeConfig,
  setBridgeConfig,
  pingBridge,
  getAiChannelEnabled,
  setAiChannelEnabled,
} from '@/automation/python/bridgeClient';
import { getAiChatConfig, setAiChatConfig } from '@/automation/ai/aiChatClient';
import PopupWallpaper from '@/components/newtab/settings/PopupWallpaper.vue';

const deleteLogDays = ['never', 7, 14, 30, 60, 120];

const { t } = useI18n();
const toast = useToast();
const store = useStore();
const theme = useTheme();

const isLangChange = ref(false);
const settings = computed(() => store.settings);

const bridgeConfig = ref({ token: '', port: 27182 });
const aiChannelEnabled = ref(false);
const accentPresets = ['#16a34a', '#2563eb', '#9333ea', '#ea580c', '#dc2626'];
const accentColor = ref('#16a34a');
const aiChatConfig = ref({ baseUrl: '', apiKey: '', model: '' });
const state = reactive({
  pinging: false,
  pingResult: '',
  aiProvider: '自定义',
  aiProviderPlaceholder: 'https://api.example.com',
  aiModelPlaceholder: '',
});

// 常见 OpenAI 兼容厂商预设（选择后自动填 API 地址与推荐模型，均可手改）
const aiProviders = [
  {
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    model: 'deepseek-chat',
  },
  {
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
  },
  {
    label: '硅基流动 SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    model: 'deepseek-ai/DeepSeek-V3',
  },
  {
    label: '月之暗面 Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-8k',
  },
  {
    label: '阿里通义千问',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
  },
  {
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4',
  },
  {
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    model: 'openai/gpt-4o-mini',
  },
  {
    label: 'Ollama（本机）',
    baseUrl: 'http://127.0.0.1:11434/v1',
    model: 'llama3',
  },
  { label: '自定义', baseUrl: '', model: '' },
];

async function updateAiChatConfig(patch) {
  aiChatConfig.value = await setAiChatConfig(patch);
}

function selectAiProvider(label) {
  const provider = aiProviders.find((p) => p.label === label);
  state.aiProvider = label;
  state.aiProviderPlaceholder = provider?.baseUrl || 'https://api.example.com';
  state.aiModelPlaceholder = provider?.model || '';

  if (provider?.baseUrl) {
    updateAiChatConfig({ baseUrl: provider.baseUrl, model: provider.model });
  }
}

onMounted(async () => {
  bridgeConfig.value = await getBridgeConfig();
  aiChannelEnabled.value = await getAiChannelEnabled();
  aiChatConfig.value = await getAiChatConfig();
  accentColor.value = await theme.getAccentColor();

  const matched = aiProviders.find(
    (p) => p.baseUrl && p.baseUrl === aiChatConfig.value.baseUrl
  );
  if (matched) {
    state.aiProvider = matched.label;
    state.aiModelPlaceholder = matched.model;
  }
  state.aiProviderPlaceholder =
    matched?.baseUrl || aiChatConfig.value.baseUrl || 'https://api.example.com';
});

function applyAccentColor(color) {
  accentColor.value = color;
  theme.setAccentColor(color);
}

async function updateBridgeConfig(patch) {
  bridgeConfig.value = await setBridgeConfig(patch);
}

async function toggleAiChannel(enabled) {
  aiChannelEnabled.value = await setAiChannelEnabled(enabled);
  toast.success(enabled ? '✅ AI 工作流通道已开启' : 'AI 工作流通道已关闭');
}

async function pingBridgeAction() {
  state.pinging = true;
  state.pingResult = '';

  try {
    const result = await pingBridge();
    state.pingResult = `✅ 连接成功，本机 Python ${result.python}`;
    toast.success(state.pingResult);
  } catch (err) {
    const messages = {
      'bridge-no-token': '❌ 未填写 token',
      'bridge-auth':
        '❌ token 校验失败，请检查与 ~/.automa-bridge/token 是否一致',
    };
    const msg =
      messages[err?.message] || '❌ 连接失败：桥接服务未启动或端口不对';
    state.pingResult = msg;
    toast.error(msg);
  } finally {
    state.pinging = false;
  }
}

function updateSetting(path, value) {
  store.updateSettings({ [path]: value });
}
function updateLanguage(value) {
  isLangChange.value = true;

  updateSetting('locale', value);
}
</script>
