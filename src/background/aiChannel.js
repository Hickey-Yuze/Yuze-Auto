/**
 * AI 工作流通道：background 轮询本机桥（automa-bridge）的指令队列，
 * 支持 AI 侧远程「导入工作流 / 执行工作流」，结果回传供 AI 读取。
 *
 * 通道协议（与 automa-bridge/server.py /yuze/* 端点对应）：
 * - 扩展每 POLL_INTERVAL_MS 调 POST /yuze/commands {since, workflows}
 *   （上报工作流摘要 + 取走 id > since 的指令）
 * - 逐条执行指令，POST /yuze/results {commandId, type, ok, result, error}
 * - AI 侧经桥的 /yuze/workflows、/yuze/execute、/yuze/results 收发
 *
 * 复用 Python 桥的连接配置（chrome.storage.local.pythonBridgeConfig），
 * 另加独立开关 aiChannelEnabled（默认关闭，设置页可开）。
 */
import browser from 'webextension-polyfill';
import { nanoid } from 'nanoid';
import dbLogs from '@/db/logs';
import BackgroundWorkflowUtils from './BackgroundWorkflowUtils';

const PY_BRIDGE_KEY = 'pythonBridgeConfig';
const AI_CHANNEL_STATE_KEY = 'aiChannelState';
const AI_CHANNEL_ALARM = 'yuze-ai-channel';
const POLL_INTERVAL_MS = 2000;
const POLL_INTERVAL_IDLE_MS = 10000;
const EXECUTE_RESULT_TIMEOUT_MS = 120000;
const DEFAULT_WORKFLOW_SETTINGS = {
  publicId: '',
  aipowerToken: '',
  blockDelay: 0,
  saveLog: true,
  debugMode: false,
  restartTimes: 3,
  notification: true,
  execContext: 'popup',
  reuseLastState: false,
  inputAutocomplete: true,
  onError: 'stop-workflow',
  executedBlockOnWeb: false,
  insertDefaultColumn: false,
  defaultColumnName: 'column',
};

const state = {
  timer: null,
  since: 0,
  failures: 0,
};

function getBridgeConfig() {
  return browser.storage.local
    .get([PY_BRIDGE_KEY, 'aiChannelEnabled'])
    .then(({ [PY_BRIDGE_KEY]: config, aiChannelEnabled }) => {
      if (!aiChannelEnabled) return null;

      return { host: '127.0.0.1', port: 27182, token: '', ...config };
    });
}

async function bridgeRequest(config, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);

  try {
    const response = await fetch(
      `http://${config.host}:${config.port}${path}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Yuze-Token': config.token,
        },
        body: JSON.stringify({ token: config.token, ...body }),
        signal: controller.signal,
      }
    );

    if (response.status === 401) throw new Error('bridge-auth');

    return await response.json();
  } catch (err) {
    if (err.name === 'AbortError') throw new Error('bridge-timeout');
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** 工作流摘要上报（给 AI 侧 /yuze/workflows 提供快照） */
async function collectWorkflowSummaries() {
  const { workflows } = await browser.storage.local.get('workflows');
  const list = Array.isArray(workflows)
    ? workflows
    : Object.values(workflows || {});

  return list
    .filter((item) => item && !item.isDisabled)
    .map(({ id, name, description, createdAt, updatedAt }) => ({
      id,
      name,
      description: description || '',
      createdAt,
      updatedAt,
    }));
}

/**
 * 导入工作流（background 直写 storage.local 的 workflows 键）。
 * 同名工作流已存在则复用其 id 更新（便于 AI 迭代重推）。
 */
async function importWorkflow({ name, description, drawflow }) {
  const nodes = Array.isArray(drawflow?.nodes) ? drawflow.nodes : [];
  if (!nodes.length) throw new Error('drawflow.nodes 不能为空');

  const triggerNode = nodes.find((node) => node.label === 'trigger');
  if (!triggerNode) throw new Error('缺少 trigger 起始块');

  const { workflows } = await browser.storage.local.get('workflows');
  const store = Array.isArray(workflows)
    ? Object.fromEntries(workflows.map((item) => [item.id, item]))
    : { ...(workflows || {}) };

  const existing = Object.values(store).find((item) => item.name === name);
  const workflowId = existing?.id || nanoid();

  const workflow = {
    ...(existing || {}),
    id: workflowId,
    name,
    icon: existing?.icon || 'riGlobalLine',
    folderId: existing?.folderId ?? null,
    content: existing?.content ?? null,
    connectedTable: existing?.connectedTable ?? null,
    drawflow: {
      edges: Array.isArray(drawflow.edges) ? drawflow.edges : [],
      zoom: 1.3,
      nodes,
    },
    table: existing?.table || [],
    dataColumns: existing?.dataColumns || [],
    description: description || '',
    trigger: triggerNode.data || null,
    createdAt: existing?.createdAt || Date.now(),
    updatedAt: Date.now(),
    isDisabled: false,
    settings: { ...DEFAULT_WORKFLOW_SETTINGS, ...(existing?.settings || {}) },
    version: browser.runtime.getManifest().version,
    globalData: existing?.globalData || '{\n\t"key": "value"\n}',
  };

  store[workflowId] = workflow;
  await browser.storage.local.set({ workflows: store });

  if (triggerNode.data && triggerNode.data.type !== 'manual') {
    const { registerWorkflowTrigger } = await import('@/utils/workflowTrigger');
    registerWorkflowTrigger(workflowId, { data: triggerNode.data });
  }

  return { workflowId, name, imported: !existing, updated: !!existing };
}

/** 等待执行结果（轮询 logs 库 items 表，工作流完成写日志） */
async function waitForExecutionResult(workflowId, startedAt) {
  const deadline = Date.now() + EXECUTE_RESULT_TIMEOUT_MS;

  const sleep = () =>
    // 轮询间隙调一次扩展 API，重置 MV3 SW 的 30s 空闲计时，防止长执行等待期间被杀
    new Promise((resolve) => {
      browser.storage.local.get('aiChannelEnabled').then(() => {
        setTimeout(resolve, 2000);
      });
    });

  while (Date.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop
    await sleep();

    let fresh = [];

    try {
      // eslint-disable-next-line no-await-in-loop
      const items = await dbLogs.items
        .where('workflowId')
        .equals(workflowId)
        .toArray();
      fresh = items.filter((item) => (item.startedAt || 0) >= startedAt - 2000);
    } catch (err) {
      // logs 库尚未建表/查询失败时继续等
    }

    const latest = fresh.sort(
      (a, b) => (b.startedAt || 0) - (a.startedAt || 0)
    )[0];

    // 有已结束的日志即视为本次执行完成（endedAt 为 0 表示还在跑）
    if (latest && latest.endedAt) {
      return {
        status: latest.status,
        message: latest.message || '',
        logId: latest.logId || latest.id,
        endedAt: latest.endedAt,
      };
    }
  }

  throw new Error('execute-timeout: 120s 内未等到工作流完成');
}

/** 指令分发：import_workflow / execute_workflow */
async function dispatchCommand(command) {
  const { type, payload } = command;

  try {
    let result = null;

    if (type === 'import_workflow') {
      result = await importWorkflow(payload || {});
    } else if (type === 'execute_workflow') {
      const { workflowId } = payload || {};
      const workflowData = await BackgroundWorkflowUtils.getWorkflow(
        workflowId
      );
      if (!workflowData) throw new Error(`workflow-not-found:${workflowId}`);
      if (workflowData.isDisabled)
        throw new Error(`workflow-disabled:${workflowId}`);

      const startedAt = Date.now();
      // checkParams:false —— 自动执行禁止弹参数输入窗（会中断流程）
      await BackgroundWorkflowUtils.instance.executeWorkflow(workflowData, {
        checkParams: false,
      });
      result = await waitForExecutionResult(workflowId, startedAt);
    } else {
      throw new Error(`unknown-command:${type}`);
    }

    return { ok: true, result };
  } catch (err) {
    return { ok: false, error: err?.message || String(err) };
  }
}

/** 持久化轮询位点（防 service worker 重启重复消费） */
export async function saveAiChannelState() {
  await browser.storage.local.set({
    [AI_CHANNEL_STATE_KEY]: { since: state.since },
  });
}

async function pollOnce() {
  const config = await getBridgeConfig();
  if (!config || !config.token) return false;

  const workflows = await collectWorkflowSummaries();

  try {
    const payload = await bridgeRequest(config, '/yuze/commands', {
      since: state.since,
      workflows,
    });

    state.failures = 0;

    // 桥返回的 commands 已是数组；parseJSON 对数组会 JSON.parse 失败恒返兜底，故直接判 Array
    const commands = Array.isArray(payload.commands) ? payload.commands : [];
    for (const command of commands) {
      state.since = Math.max(state.since, command.id);

      try {
        const outcome = await dispatchCommand(command);
        await bridgeRequest(config, '/yuze/results', {
          commandId: command.id,
          type: command.type,
          ...outcome,
        });
      } catch (err) {
        await bridgeRequest(config, '/yuze/results', {
          commandId: command.id,
          type: command.type,
          ok: false,
          error: err?.message || String(err),
        });
      }
    }

    if (commands.length) await saveAiChannelState();

    return true;
  } catch (err) {
    state.failures += 1;
    return false;
  }
}

async function pollLoop() {
  let hasBridge = false;

  try {
    hasBridge = await pollOnce();
  } catch (err) {
    hasBridge = false;
  }

  // 桥在线且无失败：2s 快轮询；否则 10s 降频空转
  const delay =
    hasBridge && state.failures === 0
      ? POLL_INTERVAL_MS
      : POLL_INTERVAL_IDLE_MS;

  state.timer = setTimeout(pollLoop, delay);
}

/** 启动轮询（幂等），并注册 30s 周期 alarm 防 service worker 休眠失联 */
export async function startAiChannel() {
  // MV3 SW 空闲约 30s 会被杀，纯 setTimeout 轮询随之中断；
  // 用 chrome.alarms 周期唤醒（BackgroundEventsListeners.onAlarms 回调本函数重启轮询）
  browser.alarms.create(AI_CHANNEL_ALARM, { periodInMinutes: 0.5 });

  if (state.timer) return;

  const { [AI_CHANNEL_STATE_KEY]: saved } = await browser.storage.local.get(
    AI_CHANNEL_STATE_KEY
  );
  state.since = saved?.since || 0;

  pollLoop();
}

export function stopAiChannel() {
  if (state.timer) {
    clearTimeout(state.timer);
    state.timer = null;
  }
}
