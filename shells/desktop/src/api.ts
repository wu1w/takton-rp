/* nianxia-core API 客户端（SSE 走 fetch ReadableStream） */

// Tauri 生产环境：页面跑在 tauri:// 协议下，core 在本机 7420。
// 开发/浏览器环境（core 托管 dist 或 vite dev）用相对路径同源访问。
export const API_BASE: string =
  location.protocol === "tauri:" || location.hostname === "tauri.localhost"
    ? "http://127.0.0.1:7420"
    : "";

export interface Health {
  status: string;
  version: string;
  schema_version: number;
}

export interface ProfileItem {
  id: string;
  name: string;
}

export interface Persona {
  id: string;
  name: string;
  locked: boolean;
  identity: {
    short: string;
    full: string;
    speech_style: string[];
    boundaries: string[];
    greeting_style: string;
  };
  active_card_id?: string | null;
  active_card?: Card;
}

export interface Fact {
  id: string;
  text: string;
  pinned: boolean;
  source: string;
  created_at: number;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(`${API_BASE}${url}`);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function put<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${url}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function del<T>(url: string): Promise<T> {
  const r = await fetch(`${API_BASE}${url}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

/** 导入角色卡（PNG/JSON，chara_card_v2 兼容） */
export async function importCard(file: File): Promise<Card> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  const r = await fetch(`${API_BASE}/v1/cards/import`, { method: "POST", body: fd });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      msg = ((await r.json()) as { detail?: string }).detail || msg;
    } catch { /* 保持状态码 */ }
    throw new Error(msg);
  }
  return r.json() as Promise<Card>;
}

export const api = {
  health: () => get<Health>("/v1/health"),
  clock: () => get<Record<string, unknown>>("/v1/clock"),
  profiles: () => get<{ items: ProfileItem[] }>("/v1/profiles"),
  persona: (pid: string) => get<Persona>(`/v1/profiles/${pid}/persona`),
  facts: (pid: string) => get<{ items: Fact[] }>(`/v1/profiles/${pid}/facts`),
  settings: () => get<Record<string, any>>("/v1/settings"),
  memoryStats: (pid: string) =>
    get<{
      facts_total: number;
      facts_pinned: number;
      facts_loose: number;
      sessions: number;
      growth_pending: number;
      last_active: number;
    }>(`/v1/profiles/${pid}/memory/stats`),

  engineStatus: () =>
    get<{
      l0: { installed: boolean; running: boolean; model_path: string | null; backend?: string | null; candidates?: string[] };
    }>("/v1/engine/status"),
  l0DownloadStart: () =>
    post<{ ok: boolean; error?: string }>("/v1/engine/l0/download"),
  l0DownloadStatus: () =>
    get<{ status: string; done_bytes: number; total_bytes: number; error?: string | null }>("/v1/engine/l0/download/status"),
  backendStatus: () =>
    get<{ packs: Record<string, { state: string; bytes_done?: number; bytes_total?: number; error?: string | null }>; installed: string[] }>(
      "/v1/engine/l0/backend/status"
    ),
  backendInstall: (backend: string) =>
    post<{ ok: boolean; error?: string }>(`/v1/engine/l0/backend/${backend}`),

  backupExport: async (): Promise<{ path: string; size: number }> => {
    const r = await fetch(`${API_BASE}/v1/backup/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ include_secrets: false }),
    });
    if (!r.ok) throw new Error(`backupExport → ${r.status}`);
    return r.json();
  },

  backupList: () =>
    get<{ items: { name: string; path: string; size: number }[] }>("/v1/backup/list"),

  backupImport: async (path: string): Promise<{ ok: boolean; error?: string }> => {
    const r = await fetch(`${API_BASE}/v1/backup/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) throw new Error(`backupImport → ${r.status}`);
    return r.json();
  },

  exportMemoir: (pid: string) =>
    fetch(`${API_BASE}/v1/profiles/${pid}/export/memoir`).then((r) => {
      if (!r.ok) throw new Error(`memoir → ${r.status}`);
      return r.json() as Promise<{ path: string; size: number }>;
    }),

  async addFact(pid: string, text: string, pinned = false): Promise<Fact> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/facts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, pinned }),
    });
    if (!r.ok) throw new Error(`addFact → ${r.status}`);
    return r.json();
  },

  async setPin(pid: string, factId: string, pinned: boolean): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/facts/${factId}/pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    });
    if (!r.ok) throw new Error(`setPin → ${r.status}`);
  },

  async deleteFact(pid: string, factId: string): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/facts/${factId}`, {
      method: "DELETE",
    });
    if (!r.ok) throw new Error(`deleteFact → ${r.status}`);
  },

  bond: (pid: string) =>
    get<{ met_at: number; stage: string; last_session_at: number | null }>(
      `/v1/profiles/${pid}/bond`
    ),

  latestSession: (pid: string) =>
    get<{
      session_id: string | null;
      items: { role: string; content: string; ts: number }[];
    }>(`/v1/profiles/${pid}/sessions/latest`),

  listSessions: (pid: string) =>
    get<{
      items: {
        session_id: string;
        updated_at: number;
        msg_count: number;
        preview: string;
      }[];
    }>(`/v1/profiles/${pid}/sessions`),

  // ---------- 角色卡 ----------
  listCards: () => get<{ items: Card[] }>("/v1/cards"),
  createCard: (card: Partial<Card>) =>
    post<Card>("/v1/cards", card),
  updateCard: (id: string, card: Partial<Card>) =>
    put<Card>(`/v1/cards/${id}`, card),
  deleteCard: (id: string) => del<{ ok: boolean }>(`/v1/cards/${id}`),
  exportCard: (id: string) => get<unknown>(`/v1/cards/${id}/export`),
  setActiveCard: (pid: string, cardId: string | null) =>
    post<{
      ok: boolean;
      active_card_id: string | null;
      session_id?: string;
      created?: boolean;
      greeting?: string;
    }>(`/v1/profiles/${pid}/active-card`, { card_id: cardId }),
  createSession: (pid: string) =>
    post<{ session_id: string; greeting: string }>(
      `/v1/profiles/${pid}/sessions`,
      {}
    ),

  getSession: (pid: string, sid: string) =>
    get<{
      session_id: string;
      items: { role: string; content: string; ts: number }[];
    }>(`/v1/profiles/${pid}/sessions/${sid}`),

  async deleteSession(pid: string, sid: string): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/sessions/${sid}`, {
      method: "DELETE",
    });
    if (!r.ok) throw new Error(`deleteSession → ${r.status}`);
  },

  async putSettings(s: Record<string, any>): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
    });
    if (!r.ok) throw new Error(`putSettings → ${r.status}`);
  },

  /** 部分更新：读当前配置 → 一层深合并 dict → 整体写回（不丢其它字段） */
  async updateSettings(patch: Record<string, any>): Promise<Record<string, any>> {
    const cur = await get<Record<string, any>>("/v1/settings");
    const next: Record<string, any> = { ...cur };
    for (const [k, v] of Object.entries(patch)) {
      const cv = cur[k];
      next[k] =
        v && typeof v === "object" && !Array.isArray(v) &&
        cv && typeof cv === "object" && !Array.isArray(cv)
          ? { ...(cv as Record<string, any>), ...(v as Record<string, any>) }
          : v;
    }
    const r = await fetch(`${API_BASE}/v1/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
    if (!r.ok) throw new Error(`updateSettings → ${r.status}`);
    return next;
  },

  async setLlmKey(apiKey: string): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/settings/llm-key`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!r.ok) throw new Error(`setLlmKey → ${r.status}`);
  },

  listGrowth: (pid: string, status = "pending") =>
    get<{ items: GrowthItem[] }>(
      `/v1/profiles/${pid}/growth?status=${status}`
    ),

  async growthAction(
    pid: string,
    gid: string,
    action: "confirm" | "reject" | "pin"
  ): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/growth/${gid}/${action}`, {
      method: "POST",
    });
    if (!r.ok) throw new Error(`growth ${action} → ${r.status}`);
  },

  async tts(text: string, voice = ""): Promise<{ ok: boolean; path?: string; error?: string }> {
    const r = await fetch(`${API_BASE}/v1/media/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice }),
    });
    if (!r.ok) throw new Error(`tts → ${r.status}`);
    return r.json();
  },

  /** AI 代笔：一句话 → L0 扩写卡草稿（不落库，用户过目） */
  async draftCard(hint: string, name = ""): Promise<{ ok: boolean; draft?: Partial<Card>; error?: string }> {
    const r = await fetch(`${API_BASE}/v1/cards/draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hint, name }),
    });
    if (!r.ok) throw new Error(`draft → ${r.status}`);
    return r.json();
  },

  /** 画图：真实调用配置的服务商，未配置会如实报错 */
  async generateImage(prompt: string): Promise<{ ok: boolean; path?: string; error?: string }> {
    const r = await fetch(`${API_BASE}/v1/media/image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!r.ok) throw new Error(`image → ${r.status}`);
    return r.json();
  },

  /** 视觉补人设：L0 读图写人设草稿 */
  async inferPersona(rel: string): Promise<{ ok: boolean; draft?: string; error?: string }> {
    const r = await fetch(`${API_BASE}/v1/media/infer-persona`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rel }),
    });
    if (!r.ok) throw new Error(`infer-persona → ${r.status}`);
    return r.json();
  },

  /** 上传角色形象照为卡头像 */
  async uploadCardAvatar(cardId: string, file: File): Promise<Card> {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`${API_BASE}/v1/cards/${cardId}/avatar`, { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `avatar → ${r.status}`);
    return data;
  },

  /** 把 media/ 下已有图（AI 生成产物）设为卡头像 */
  async cardAvatarFrom(cardId: string, rel: string): Promise<Card> {
    const r = await fetch(`${API_BASE}/v1/cards/${cardId}/avatar-from`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rel }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `avatar-from → ${r.status}`);
    return data;
  },

  /** 跨会话搜索聊天记录 */
  searchMessages: (pid: string, q: string) =>
    get<{ items: SearchHit[] }>(`/v1/profiles/${pid}/search?q=${encodeURIComponent(q)}`),

  /** 会话分支：复制前 upto 条到新会话 */
  async branchSession(pid: string, sid: string, upto: number): Promise<{ ok: boolean; session_id: string; msg_count: number }> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/sessions/${sid}/branch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upto }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `branch → ${r.status}`);
    return data;
  },

  mediaUrl: (rel: string) => `/v1/media/file?rel=${encodeURIComponent(rel)}`,

  async putPersona(
    pid: string,
    body: { name?: string; short?: string; boundaries?: string[] }
  ): Promise<void> {
    const r = await fetch(`${API_BASE}/v1/profiles/${pid}/persona`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`putPersona → ${r.status}`);
  },
};

export interface GrowthItem {
  id: string;
  text: string;
  kind: string;
  status: string;
  confidence: number;
  source_session_id: string;
  source_excerpt: string;
  created_at: number;
}

export interface ChatHandlers {
  onSession?: (sid: string) => void;
  onDelta?: (text: string) => void;
  onTrace?: (info: any) => void;
  onTool?: (phase: "call" | "result", human: string, payload?: any) => void;
  onGrowth?: (text: string) => void;
  onSwipe?: (p: { message_id: string; content: string; swipe_idx: number; swipes_count: number }) => void;
  onEnd?: (info: any) => void;
  onError?: (msg: string) => void;
}

/** POST /v1/chat/stream，逐事件回调 */
export interface Attachment {
  kind: "image" | "file";
  name: string;
  url: string;
  text?: string | null;
}

export interface LoreEntry {
  id?: string;
  keys: string[];
  content: string;
  constant?: boolean;
  order?: number;
  enabled?: boolean;
}

export interface Card {
  id: string;
  name: string;
  avatar?: string;
  avatar_url?: string;
  description: string;
  personality: string;
  scenario: string;
  first_mes: string;
  mes_example: string;
  system_prompt: string;
  post_history_instructions: string;
  creator_notes: string;
  tags: string[];
  alternate_greetings: string[];
  voice?: string;
  lorebook?: LoreEntry[];
  source: "builtin" | "imported" | "custom";
}

export interface SearchHit {
  session_id: string;
  session_preview: string;
  idx: number;
  role: string;
  snippet: string;
  ts: number;
}

export async function uploadMedia(file: File): Promise<Attachment> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API_BASE}/v1/media/upload`, { method: "POST", body: fd });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.detail || `上传失败（${r.status}）`);
  return { kind: data.kind, name: data.name, url: data.url, text: data.text ?? null };
}

/** 通用 SSE POST 读取器（chat/swipe/regen 共用） */
async function ssePost(url: string, body: Record<string, unknown>, h: ChatHandlers): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok || !resp.body) {
    h.onError?.(`连接失败（${resp.status}），Core 是否已启动？`);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");
    buf = events.pop() ?? "";
    for (const raw of events) {
      let ev = "";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!ev || !data) continue;
      let payload: any = {};
      try {
        payload = JSON.parse(data);
      } catch {
        continue;
      }
      if (ev === "session") h.onSession?.(payload.session_id);
      else if (ev === "delta") h.onDelta?.(payload.text ?? "");
      else if (ev === "trace") h.onTrace?.(payload);
      else if (ev === "tool_call") h.onTool?.("call", payload.human ?? payload.tool, payload);
      else if (ev === "tool_result") h.onTool?.("result", payload.human ?? "", payload);
      else if (ev === "growth") h.onGrowth?.(payload.text ?? "");
      else if (ev === "swipe") h.onSwipe?.(payload);
      else if (ev === "message_end") h.onEnd?.(payload);
      else if (ev === "error") h.onError?.(payload.message ?? "未知错误");
    }
  }
}

export async function chatStream(
  profileId: string,
  sessionId: string | null,
  message: string,
  tier: string,
  h: ChatHandlers,
  attachments?: Attachment[]
): Promise<void> {
  await ssePost(`${API_BASE}/v1/chat/stream`, {
    profile_id: profileId,
    session_id: sessionId,
    message,
    tier,
    ...(attachments?.length ? { attachments } : {}),
  }, h);
}

/** Swipes 重抽：prev/next 切变体；new 重新生成一个变体（流式） */
export async function swipeStream(
  profileId: string,
  sessionId: string,
  messageId: string,
  direction: "prev" | "next" | "new",
  tier: string,
  h: ChatHandlers
): Promise<void> {
  await ssePost(`${API_BASE}/v1/chat/swipe`, {
    profile_id: profileId,
    session_id: sessionId,
    message_id: messageId,
    direction,
    tier,
  }, h);
}

/** 重生成：以最后一条 user 消息为提示续写（编辑消息后使用） */
export async function regenStream(
  profileId: string,
  sessionId: string,
  tier: string,
  h: ChatHandlers
): Promise<void> {
  await ssePost(`${API_BASE}/v1/chat/regen`, {
    profile_id: profileId,
    session_id: sessionId,
    tier,
  }, h);
}

/** 编辑自己的消息：更新内容并截断其后消息 */
export async function editMessage(
  profileId: string,
  sessionId: string,
  messageId: string,
  content: string
): Promise<{ ok: boolean; removed: number }> {
  const resp = await fetch(`${API_BASE}/v1/chat/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_id: profileId, session_id: sessionId, message_id: messageId, content }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail ?? `编辑失败（${resp.status}）`);
  return data;
}
