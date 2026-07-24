import React, { useEffect, useState } from "react";
import { api, API_BASE } from "../api";
import { IconCloud, IconCpu, IconDownload, IconFolder, IconSliders, IconSpeaker } from "../icons";

/** 画图配置：预设卡片快填 + 自定义字段 + 厂商外链（白名单）；真实落库 */
const IMAGE_PRESETS = [
  {
    id: "lan-comfy",
    label: "局域网 ComfyUI（自建）",
    base_url: "",
    model: "z-image-dual",
    backend: "comfy",
    link: "",
  },
  { id: "wanx", label: "通义万相", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "wanx2.1-t2i-turbo", backend: "openai", link: "https://bailian.console.aliyun.com/" },
  { id: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-image-1", backend: "openai", link: "https://platform.openai.com/" },
  { id: "sf", label: "硅基流动", base_url: "https://api.siliconflow.cn/v1", model: "Kwai-Kolors/Kolors", backend: "openai", link: "https://cloud.siliconflow.cn/" },
];

function MediaSection({
  settings,
  onSaved,
  onToast,
}: {
  settings: Record<string, any> | null;
  onSaved: (s: Record<string, any>) => void;
  onToast: (m: string) => void;
}) {
  const img = (settings?.media?.image ?? {}) as Record<string, any>;
  const [base, setBase] = useState("");
  const [model, setModel] = useState("");
  const [presetId, setPresetId] = useState("");
  const [backend, setBackend] = useState("openai");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setBase(String(img.base_url ?? ""));
    setModel(String(img.model ?? ""));
    setPresetId(String(img.preset_id ?? ""));
    setBackend(String(img.backend ?? (String(img.base_url ?? "").includes("8188") ? "comfy" : "openai")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  async function save(next?: Partial<{ base_url: string; model: string; preset_id: string; backend: string; enabled: boolean }>) {
    const patch = {
      preset_id: next?.preset_id ?? presetId,
      base_url: next?.base_url ?? base,
      model: next?.model ?? model,
      backend: next?.backend ?? backend,
      enabled: next?.enabled ?? true,
      key_ref: "secrets/image.key",
    };
    setBusy(true);
    try {
      const s = await api.updateSettings({ media: { image: patch } });
      onSaved(s);
    } catch {
      onToast("保存失败");
    }
    setBusy(false);
  }

  return (
    <>
      <div className="cell static">
        <span className="tile purple"><IconSpeaker /></span>
        <span className="body">
          <div className="t">图片生成</div>
          <div className="d">
            {base
              ? `${backend === "comfy" ? "Comfy · " : ""}${model || "未填模型"} · 随角色锁脸`
              : "未配置"}
          </div>
        </span>
        <span className="count" style={{ background: base ? "var(--green)" : "var(--faint)" }}>
          {base ? "已配置" : "未配置"}
        </span>
      </div>
      <div className="cell static" style={{ flexWrap: "wrap", gap: 4 }}>
        {IMAGE_PRESETS.map((p) => (
          <button
            key={p.id}
            className="act"
            type="button"
            disabled={busy}
            style={presetId === p.id ? { borderColor: "var(--tint)", color: "var(--tint)" } : {}}
            onClick={() => {
              setPresetId(p.id);
              setBase(p.base_url);
              setModel(p.model);
              setBackend(p.backend || "openai");
              save({
                preset_id: p.id,
                base_url: p.base_url,
                model: p.model,
                backend: p.backend || "openai",
                enabled: true,
              });
            }}
          >
            {p.label}
          </button>
        ))}
        {IMAGE_PRESETS.find((p) => p.id === presetId)?.link && (
          <button
            className="act"
            type="button"
            onClick={() => window.open(IMAGE_PRESETS.find((p) => p.id === presetId)!.link, "_blank")}
          >
            去配 Key
          </button>
        )}
      </div>
      <div className="cell static">
        <span className="body">
          <input
            className="input"
            placeholder={backend === "comfy" ? "ComfyUI 地址（如 http://192.168.1.10:8188）" : "base_url（OpenAI 兼容）"}
            value={base}
            onChange={(e) => setBase(e.target.value)}
          />
        </span>
      </div>
      <div className="cell static">
        <span className="body">
          <input
            className="input"
            placeholder={backend === "comfy" ? "模型标记（可填 z-image-dual）" : "模型名"}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </span>
        <button className="act" type="button" disabled={busy} onClick={() => save()}>保存</button>
      </div>
      <div className="cell static">
        <span className="body">
          <div className="d">
            生图会自动注入当前角色的外貌锁；有设定图/上次成图会记入角色卡，切换角色即换锁。
          </div>
        </span>
      </div>
    </>
  );
}

/** 语音配置：Edge 朗读开关真实落库；其余如实标未接 */
function TtsSection({
  settings,
  onSaved,
  onToast,
}: {
  settings: Record<string, any> | null;
  onSaved: (s: Record<string, any>) => void;
  onToast: (m: string) => void;
}) {
  const tts = (settings?.media?.tts ?? {}) as Record<string, any>;
  const enabled = Boolean(tts.enabled);

  async function toggle(v: boolean) {
    try {
      const s = await api.updateSettings({ media: { tts: { enabled: v, provider: "edge" } } });
      onSaved(s);
    } catch {
      onToast("保存失败");
    }
  }

  return (
    <>
      <div className="cell static">
        <span className="tile purple"><IconSpeaker /></span>
        <span className="body">
          <div className="t">Edge 朗读</div>
          <div className="d">免 Key · 点气泡下的「朗读」就能听</div>
        </span>
        <label className={"switch" + (enabled ? " on" : "")}>
          <input type="checkbox" checked={enabled} onChange={(e) => toggle(e.target.checked)} />
          <span className="sl" />
        </label>
      </div>
    </>
  );
}

/** 消息通道：总开关 + TG / QQ官方 / 微信机器人；支持图文文件收发 */
function ChannelSection({ onToast }: { onToast: (m: string) => void }) {
  const [status, setStatus] = useState<any>(null);
  const [token, setToken] = useState("");
  const [qqAppId, setQqAppId] = useState("");
  const [qqSecret, setQqSecret] = useState("");
  const [wxQrUrl, setWxQrUrl] = useState("");
  const [wxQrcode, setWxQrcode] = useState("");
  const [wxRedirect, setWxRedirect] = useState("");
  const [wxPolling, setWxPolling] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cards, setCards] = useState<{ id: string; name: string }[]>([]);
  const [bindings, setBindings] = useState<Record<string, { bound: boolean; profile_id: string; card_name: string | null }>>({});

  async function reload() {
    try {
      const r = await fetch(`${API_BASE}/v1/channels/status`);
      setStatus(await r.json());
      const b = await fetch(`${API_BASE}/v1/channels/bindings`);
      setBindings(await b.json());
    } catch {
      /* 离线 */
    }
  }
  useEffect(() => {
    reload();
    fetch(`${API_BASE}/v1/cards`)
      .then((r) => r.json())
      .then((d) => setCards((d.items ?? d ?? []).map((c: any) => ({ id: c.id, name: c.name }))))
      .catch(() => {});
  }, []);

  /** 通道专属角色绑定行：选卡=该通道用独立角色（记忆与 App 隔离）；默认=跟随 App */
  async function bind(channel: string, cardId: string) {
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/v1/channels/${channel}/bind`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ card_id: cardId || null }),
      });
      const d = await r.json();
      if (d.ok) onToast(cardId ? `已绑定「${d.card_name}」` : "已回到跟随 App");
      else onToast(d.detail || "绑定失败");
      reload();
    } catch {
      onToast("Core 未连接");
    }
    setBusy(false);
  }

  function bindRow(channel: string) {
    const b = bindings[channel];
    const current = b?.bound ? b.card_name ?? "已绑定" : "";
    return (
      <div className="cell static">
        <span className="body">
          <div className="d">专属角色{current ? `：${current}` : "（记忆与 App 隔离）"}</div>
        </span>
        <select
          className="input bind-select"
          disabled={busy}
          value={b?.bound ? cards.find((c) => c.name === b?.card_name)?.id ?? "" : ""}
          onChange={(e) => bind(channel, e.target.value)}
        >
          <option value="">跟随 App（当前角色）</option>
          {cards.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>
    );
  }

  const tg = status?.telegram ?? {};
  const qq = status?.qqbot ?? status?.onebot ?? {};
  const wx = status?.weixin ?? status?.wecom ?? {};

  async function post(path: string, body: any, okMsg: string) {
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/v1/channels/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.ok === false) onToast(d.error || "操作失败");
      else onToast(okMsg);
      reload();
    } catch {
      onToast("Core 未连接");
    }
    setBusy(false);
  }

  async function setupTg() {
    if (!token.trim()) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/v1/channels/telegram/setup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.trim() }),
      });
      const d = await r.json();
      if (d.ok) {
        onToast(`已连接 @${d.bot}，配对码 ${d.pairing_code}`);
        setToken("");
      } else onToast(d.error || "token 无效");
      reload();
    } catch {
      onToast("Core 未连接");
    }
    setBusy(false);
  }

  async function setupQq() {
    if (!qqAppId.trim() || !qqSecret.trim()) {
      onToast("请填 AppID 和 AppSecret");
      return;
    }
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/v1/channels/qqbot/setup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_id: qqAppId.trim(), app_secret: qqSecret.trim() }),
      });
      const d = await r.json();
      if (d.ok) {
        onToast(`QQ 已配置，配对码 ${d.pairing_code}`);
        setQqSecret("");
      } else onToast(d.error || "配置失败");
      reload();
    } catch {
      onToast("Core 未连接");
    }
    setBusy(false);
  }

  async function startWxQr() {
    setBusy(true);
    setWxQrUrl("");
    setWxQrcode("");
    setWxRedirect("");
    try {
      const r = await fetch(`${API_BASE}/v1/channels/weixin/qr/start`, { method: "POST" });
      const d = await r.json();
      if (!d.ok) {
        onToast(d.error || "获取二维码失败");
        setBusy(false);
        return;
      }
      setWxQrcode(d.qrcode || "");
      setWxQrUrl(d.qrcode_url || d.qrcode || "");
      onToast("请用微信扫码并确认");
      setWxPolling(true);
      // 前端轮询
      const code = d.qrcode as string;
      let redirect = "";
      for (let i = 0; i < 120; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        const pr = await fetch(`${API_BASE}/v1/channels/weixin/qr/poll`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ qrcode: code, redirect_base: redirect }),
        });
        const pd = await pr.json();
        if (pd.redirect_base) {
          redirect = pd.redirect_base;
          setWxRedirect(redirect);
        }
        if (pd.status === "confirmed" && pd.ok !== false) {
          onToast(`微信已连接，配对码 ${pd.pairing_code || ""}`);
          setWxPolling(false);
          setWxQrUrl("");
          setWxQrcode("");
          reload();
          setBusy(false);
          return;
        }
        if (pd.status === "expired") {
          onToast("二维码过期，请重新扫码");
          break;
        }
        if (pd.status === "error") {
          onToast(pd.error || "扫码失败");
          break;
        }
      }
      setWxPolling(false);
    } catch {
      onToast("Core 未连接");
      setWxPolling(false);
    }
    setBusy(false);
  }

  return (
    <>
      <div className="cell static">
        <span className="tile blue"><IconCloud /></span>
        <span className="body">
          <div className="t">通道总开关</div>
          <div className="d">关掉即所有外线全断 · 三通道均可收发图片/文件</div>
        </span>
        <label className={"switch" + (status?.master_enabled ? " on" : "")}>
          <input
            type="checkbox"
            checked={Boolean(status?.master_enabled)}
            onChange={(e) =>
              post("master", { enabled: e.target.checked }, e.target.checked ? "外线已开" : "外线全断")
            }
          />
          <span className="sl" />
        </label>
      </div>

      {/* Telegram */}
      <div className="cell static">
        <span className="tile teal"><IconCloud /></span>
        <span className="body">
          <div className="t">Telegram</div>
          <div className="d">
            {tg.has_token
              ? tg.paired_chats > 0
                ? `已配对 ${tg.paired_chats} · 码 ${tg.pairing_code ?? "—"}`
                : `待配对 · 码 ${tg.pairing_code ?? "—"}`
              : "未配置"}
          </div>
        </span>
        {tg.has_token && (
          <label className={"switch" + (tg.enabled ? " on" : "")}>
            <input
              type="checkbox"
              checked={Boolean(tg.enabled)}
              onChange={(e) =>
                post("telegram/enable", { enabled: e.target.checked }, e.target.checked ? "TG 已开" : "TG 已关")
              }
            />
            <span className="sl" />
          </label>
        )}
      </div>
      {!tg.has_token && (
        <div className="cell static">
          <span className="body">
            <input
              className="input"
              type="password"
              placeholder="Bot Token（@BotFather）"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </span>
          <button className="act" type="button" disabled={busy || !token.trim()} onClick={setupTg}>
            连接
          </button>
        </div>
      )}
      {tg.has_token && (
        <div className="cell static">
          <span className="body"><div className="d">配对码泄露可轮换</div></span>
          <button className="act" type="button" disabled={busy} onClick={() => post("telegram/pairing/rotate", {}, "配对码已轮换")}>
            轮换
          </button>
        </div>
      )}
      {bindRow("telegram")}

      {/* QQ 官方机器人 */}
      <div className="cell static">
        <span className="tile purple"><IconCloud /></span>
        <span className="body">
          <div className="t">QQ 机器人</div>
          <div className="d">
            {qq.configured
              ? `AppID ${qq.app_id || "已配"} · 已配对 ${qq.paired_users ?? 0} · 码 ${qq.pairing_code ?? "—"}${qq.running ? " · 在线" : ""}`
              : "QQ 开放平台 · AppID + AppSecret（与 Hermes 同款）"}
          </div>
        </span>
        {qq.configured && (
          <label className={"switch" + (qq.enabled ? " on" : "")}>
            <input
              type="checkbox"
              checked={Boolean(qq.enabled)}
              onChange={(e) =>
                post("qqbot/enable", { enabled: e.target.checked }, e.target.checked ? "QQ 已开" : "QQ 已关")
              }
            />
            <span className="sl" />
          </label>
        )}
      </div>
      {!qq.configured && (
        <>
          <div className="cell static">
            <span className="body">
              <input className="input" placeholder="AppID" value={qqAppId} onChange={(e) => setQqAppId(e.target.value)} />
            </span>
          </div>
          <div className="cell static">
            <span className="body">
              <input className="input" type="password" placeholder="AppSecret" value={qqSecret} onChange={(e) => setQqSecret(e.target.value)} />
            </span>
            <button className="act" type="button" disabled={busy || !qqAppId.trim() || !qqSecret.trim()} onClick={setupQq}>
              连接
            </button>
          </div>
        </>
      )}
      {qq.configured && (
        <div className="cell static">
          <span className="body"><div className="d">配对码发给 QQ 机器人私聊完成绑定</div></span>
          <button className="act" type="button" disabled={busy} onClick={() => post("qqbot/pairing/rotate", {}, "配对码已轮换")}>
            轮换
          </button>
        </div>
      )}
      {bindRow("qqbot")}

      {/* 微信机器人 */}
      <div className="cell static">
        <span className="tile blue"><IconCloud /></span>
        <span className="body">
          <div className="t">微信机器人</div>
          <div className="d">
            {wx.configured
              ? `已登录 · 已配对 ${wx.paired_users ?? 0} · 码 ${wx.pairing_code ?? "—"}${wx.running ? " · 在线" : ""}`
              : "个人微信 · 扫码登录（iLink，与 Hermes 同款）"}
          </div>
        </span>
        {wx.configured && (
          <label className={"switch" + (wx.enabled ? " on" : "")}>
            <input
              type="checkbox"
              checked={Boolean(wx.enabled)}
              onChange={(e) =>
                post("weixin/enable", { enabled: e.target.checked }, e.target.checked ? "微信已开" : "微信已关")
              }
            />
            <span className="sl" />
          </label>
        )}
      </div>
      {!wx.configured && (
        <>
          <div className="cell static">
            <span className="body">
              <div className="d">点「扫码登录」后用手机微信扫码并确认；无需企业应用凭证</div>
            </span>
            <button className="act" type="button" disabled={busy || wxPolling} onClick={startWxQr}>
              {wxPolling ? "等待确认…" : "扫码登录"}
            </button>
          </div>
          {wxQrUrl && (
            <div className="cell static">
              <span className="body">
                <div className="d" style={{ wordBreak: "break-all" }}>
                  扫码链接（也可复制到浏览器打开）：
                  <br />
                  <a href={wxQrUrl} target="_blank" rel="noreferrer">{wxQrUrl}</a>
                </div>
              </span>
            </div>
          )}
        </>
      )}
      {wx.configured && (
        <div className="cell static">
          <span className="body"><div className="d">配对码发给微信机器人私聊完成绑定</div></span>
          <button className="act" type="button" disabled={busy} onClick={() => post("weixin/pairing/rotate", {}, "配对码已轮换")}>
            轮换
          </button>
        </div>
      )}
      {bindRow("weixin")}

    </>
  );
}

/** 备份区：导出/回忆读本/恢复，全部真实动作 */
function BackupSection({
  profileId,
  onToast,
}: {
  profileId: string;
  onToast: (m: string) => void;
}) {
  const [backups, setBackups] = useState<{ name: string; path: string; size: number }[]>([]);
  const [busy, setBusy] = useState(false);

  async function reload() {
    try {
      const r = await api.backupList();
      setBackups(r.items);
    } catch {
      /* 离线 */
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function doExport() {
    setBusy(true);
    try {
      const r = await api.backupExport();
      onToast(`备份完成：${r.path.split(/[\\/]/).pop()}（不含密钥）`);
      reload();
    } catch {
      onToast("备份失败");
    }
    setBusy(false);
  }

  async function doMemoir() {
    setBusy(true);
    try {
      const r = await api.exportMemoir(profileId);
      onToast(`回忆读本已导出：${r.path.split(/[\\/]/).pop()}`);
    } catch {
      onToast("导出失败");
    }
    setBusy(false);
  }

  async function doRestore(path: string, name: string) {
    if (!window.confirm(`用「${name}」覆盖当前数据？此操作不可撤销。`)) return;
    setBusy(true);
    try {
      const r = await api.backupImport(path);
      onToast(r.ok ? "恢复完成，重开应用生效" : `恢复失败：${r.error}`);
    } catch {
      onToast("恢复失败");
    }
    setBusy(false);
  }

  return (
    <>
      <div className="cell static">
        <span className="tile teal"><IconDownload /></span>
        <span className="body">
          <div className="t">备份 · 恢复</div>
          <div className="d">zip 落本地 · 默认不含密钥</div>
        </span>
        <button className="act" type="button" disabled={busy} onClick={doExport}>备份</button>
        <button className="act" type="button" disabled={busy} onClick={doMemoir}>回忆读本</button>
      </div>
      {backups.map((b) => (
        <div className="cell static" key={b.name}>
          <span className="tile gray"><IconFolder /></span>
          <span className="body">
            <div className="t">{b.name}</div>
            <div className="d">{(b.size / 1024).toFixed(0)} KB</div>
          </span>
          <button className="act danger" type="button" disabled={busy} onClick={() => doRestore(b.path, b.name)}>
            恢复
          </button>
        </div>
      ))}
    </>
  );
}

/** 设置抽屉：所有字段读写真配置；未接入的能力如实标注 */
export default function SettingsDrawer({
  open,
  profileId,
  onClose,
  onToast,
}: {
  open: boolean;
  profileId: string;
  onClose: () => void;
  onToast: (m: string) => void;
}) {
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [dataRoot, setDataRoot] = useState("…");
  const [llmBase, setLlmBase] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [llmKeySet, setLlmKeySet] = useState(false);
  const [l0Installed, setL0Installed] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    api
      .settings()
      .then((s) => {
        if (!alive) return;
        setSettings(s);
        setDataRoot(String(s.data_root ?? ""));
        const llm = (s.media?.llm ?? {}) as Record<string, any>;
        setLlmBase(String(llm.base_url ?? ""));
        setLlmModel(String(llm.model ?? ""));
        setLlmKeySet(Boolean(llm.api_key_set));
      })
      .catch(() => onToast("Core 未连接"));
    api
      .engineStatus()
      .then((e: { l0?: { installed?: boolean } }) => {
        if (alive) setL0Installed(Boolean(e.l0?.installed));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [open]);

  /** 保存 L1 云配置：base_url/model 进 app-settings，key 进 secrets（不回显） */
  async function saveLlm() {
    if (!settings) return;
    setSaving(true);
    try {
      const next = {
        ...settings,
        media: {
          ...settings.media,
          llm: {
            ...settings.media?.llm,
            base_url: llmBase.trim(),
            model: llmModel.trim(),
            enabled: Boolean(llmBase.trim() && llmModel.trim()),
          },
        },
      };
      await api.putSettings(next);
      if (llmKey.trim()) {
        await api.setLlmKey(llmKey.trim());
        setLlmKey("");
        setLlmKeySet(true);
      }
      setSettings(next);
      onToast("已保存 · 下轮聊天生效");
    } catch {
      onToast("保存失败");
    }
    setSaving(false);
  }

  return (
    <>
      <div className={"drawer-mask" + (open ? " show" : "")} onClick={onClose} />
      <aside className={"drawer" + (open ? " show" : "")}>
        <div className="drawer-head">
          <h2>设置</h2>
          <button className="iconbtn" type="button" onClick={onClose} aria-label="关闭">
            <IconSliders />
          </button>
        </div>

        <div className="panel-title">怎么聊</div>
        <div className="card">
          <button className="cell" type="button" onClick={() => onToast(l0Installed ? "本地小模型已就绪" : "模型未下载：把 GGUF 放进 数据目录/models，llama-server 装进 PATH 或 vendor/")}>
            <span className="tile green"><IconCpu /></span>
            <span className="body">
              <div className="t">先随便聊聊</div>
              <div className="d">完全本机 · 通义 3.5 小巧 · 能看图</div>
            </span>
            <span className="count" style={{ background: l0Installed ? "var(--green)" : "var(--faint)" }}>
              {l0Installed === null ? "…" : l0Installed ? "已安装" : "未安装"}
            </span>
          </button>
        </div>
        <div className="card" style={{ marginTop: 10 }}>
          <div className="cell static">
            <span className="tile blue"><IconCloud /></span>
            <span className="body">
              <div className="t">更懂我（L1 云）</div>
              <div className="d">{llmKeySet ? "钥匙已配置" : "填好下面三项即可用"}</div>
            </span>
          </div>
          <div className="field">
            <input
              placeholder="接口地址，如 https://api.openai.com/v1"
              value={llmBase}
              onChange={(e) => setLlmBase(e.target.value)}
            />
          </div>
          <div className="field">
            <input
              placeholder="模型名，如 gpt-4o-mini / qwen-plus"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
            />
          </div>
          <div className="field">
            <input
              type="password"
              placeholder={llmKeySet ? "API Key（已保存，输入则覆盖）" : "API Key（只存在这台设备）"}
              value={llmKey}
              onChange={(e) => setLlmKey(e.target.value)}
            />
            <p className="hint">OpenAI 兼容接口均可。Key 存本机 secrets，不上传、不回显。</p>
          </div>
          <div className="field" style={{ paddingBottom: 12 }}>
            <button className="act" type="button" disabled={saving} onClick={saveLlm}>
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>

        <div className="panel-title">画图</div>
        <div className="card">
          <MediaSection settings={settings} onSaved={(s) => { setSettings(s); onToast("画图配置已存"); }} onToast={onToast} />
          <p className="hint" style={{ padding: "0 12px 12px" }}>
            配置会真实保存。选局域网 ComfyUI 可用自建服务生图；会按当前角色锁脸（设定图/上次成图 + 特征提示词）。
          </p>
        </div>

        <div className="panel-title">语音朗读</div>
        <div className="card">
          <TtsSection settings={settings} onSaved={(s) => { setSettings(s); onToast("语音配置已存"); }} onToast={onToast} />
        </div>

        <div className="panel-title">消息通道</div>
        <div className="card">
          <ChannelSection onToast={onToast} />
        </div>

        <div className="panel-title">数据与备份</div>
        <div className="card">
          <button className="cell" type="button" onClick={() => onToast(dataRoot)}>
            <span className="tile gold"><IconFolder /></span>
            <span className="body">
              <div className="t">数据目录</div>
              <div className="d">{dataRoot}</div>
            </span>
          </button>
          <BackupSection profileId={profileId} onToast={onToast} />
        </div>
        <p className="note" style={{ textAlign: "center", paddingTop: 14 }}>
          Powered by Takton engine · 念匣
        </p>
      </aside>
    </>
  );
}
