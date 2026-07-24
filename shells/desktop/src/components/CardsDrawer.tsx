import React, { useEffect, useRef, useState } from "react";
import { api, importCard, API_BASE } from "../api";
import type { Card } from "../api";
import { IconCheck, IconDownload, IconPerson } from "../icons";

interface Props {
  profileId: string;
  open: boolean;
  onClose: () => void;
  onToast: (msg: string) => void;
  /** 启用/停用后：外层刷新顶栏 + 切到该角色会话；sessionId 有则直达 */
  onApplied: (sessionId?: string | null) => void;
}

const EMPTY: Omit<Card, "id" | "source"> = {
  name: "",
  description: "",
  personality: "",
  scenario: "",
  first_mes: "",
  mes_example: "",
  system_prompt: "",
  post_history_instructions: "",
  creator_notes: "",
  tags: [],
  alternate_greetings: [],
  voice: "",
};

/** 朗读音色（edge-tts 中文精选） */
const VOICES: { id: string; label: string }[] = [
  { id: "", label: "默认（晓晓·温暖女声）" },
  { id: "zh-CN-XiaoyiNeural", label: "晓伊·活泼女声" },
  { id: "zh-CN-XiaohanNeural", label: "晓涵·知性好听" },
  { id: "zh-CN-XiaomengNeural", label: "晓梦·甜美女声" },
  { id: "zh-CN-XiaoruiNeural", label: "晓睿·成熟女声" },
  { id: "zh-CN-YunxiNeural", label: "云希·清亮男声" },
  { id: "zh-CN-YunjianNeural", label: "云健·沉稳男声" },
  { id: "zh-CN-YunxiaNeural", label: "云夏·少年音" },
];

/** 角色卡库：网格浏览 + 编辑器 + chara_card_v2 导入 */
export default function CardsDrawer({ profileId, open, onClose, onToast, onApplied }: Props) {
  const [cards, setCards] = useState<Card[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editing, setEditing] = useState<(Partial<Card> & { id?: string }) | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mediaBusy, setMediaBusy] = useState("");
  const [draftHint, setDraftHint] = useState("");
  const importRef = useRef<HTMLInputElement>(null);
  const avatarRef = useRef<HTMLInputElement>(null);

  /** AI 代笔：一句话 → L0 写草稿填进编辑器（不直接保存，用户过目） */
  async function aiDraft() {
    if (!draftHint.trim()) {
      onToast("先写一句她的设定");
      return;
    }
    setMediaBusy("draft");
    try {
      const r = await api.draftCard(draftHint.trim(), editing?.name?.trim() ?? "");
      if (!r.ok || !r.draft) {
        onToast(r.error || "代笔失败");
        return;
      }
      setEditing((e) => (e ? { ...e, ...r.draft, id: e.id } : e));
      onToast("草稿写好了，过目后保存");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "代笔失败");
    } finally {
      setMediaBusy("");
    }
  }

  /** 上传形象照为头像（需先保存卡片） */
  async function uploadAvatar(files: FileList | null) {
    if (!files?.length || !editing?.id) return;
    setMediaBusy("upload");
    try {
      const card = await api.uploadCardAvatar(editing.id, files[0]);
      setEditing((e) => (e ? { ...e, avatar: card.avatar, avatar_url: card.avatar_url } : e));
      await reload();
      onToast("形象照已换上");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "上传失败");
    } finally {
      setMediaBusy("");
      if (avatarRef.current) avatarRef.current.value = "";
    }
  }

  /** AI 生成形象：用名字+人设拼提示词，真实调用画图配置；产物设为头像 */
  async function genAvatar() {
    if (!editing?.id) return;
    const prompt = `character portrait: ${editing.name}, ${(editing.description || "").slice(0, 200)}, ${(editing.personality || "").slice(0, 80)}, anime style, high quality, solo, upper body`;
    setMediaBusy("gen");
    try {
      const r = await api.generateImage(prompt);
      if (!r.ok || !r.path) {
        onToast(r.error || "生成失败");
        return;
      }
      const card = await api.cardAvatarFrom(editing.id, r.path);
      setEditing((e) => (e ? { ...e, avatar: card.avatar, avatar_url: card.avatar_url } : e));
      await reload();
      onToast("形象已生成并换上");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "生成失败");
    } finally {
      setMediaBusy("");
    }
  }

  /** 视觉补人设：L0 读头像图 → 草稿填进人设/性格（不直接保存，用户过目） */
  async function inferFromAvatar() {
    if (!editing?.id || !editing.avatar) return;
    setMediaBusy("infer");
    try {
      const r = await api.inferPersona(editing.avatar);
      if (!r.ok || !r.draft) {
        onToast(r.error || "读图失败");
        return;
      }
      // 草稿两段【外貌】【性格】→ 外貌进人设（ prepend ）、性格进性格
      const appearance = r.draft.match(/【外貌】\s*([\s\S]*?)(?=【性格】|$)/)?.[1]?.trim() ?? "";
      const persona = r.draft.match(/【性格】\s*([\s\S]*?)$/)?.[1]?.trim() ?? "";
      setEditing((e) =>
        e
          ? {
              ...e,
              description: appearance ? `${appearance}${e.description ? "\n" + e.description : ""}` : e.description,
              personality: persona || e.personality,
            }
          : e
      );
      onToast("已按图写好草稿，过目后保存");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "读图失败");
    } finally {
      setMediaBusy("");
    }
  }

  async function reload() {
    try {
      const [cs, p] = await Promise.all([api.listCards(), api.persona(profileId)]);
      setCards(cs.items);
      setActiveId(p.active_card_id ?? null);
    } catch {
      /* 未连接时保持现状 */
    }
  }

  useEffect(() => {
    if (open) {
      setEditing(null);
      reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, profileId]);

  async function apply(id: string | null) {
    setBusy(true);
    try {
      const r = await api.setActiveCard(profileId, id);
      setActiveId(id);
      onApplied(r.session_id ?? null);
      onToast(id ? "已切换角色" : "已回到默认陪伴");
      onClose();
    } catch {
      onToast("切换失败");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!editing?.name?.trim()) {
      onToast("角色要有名字");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        ...editing,
        tags: typeof editing.tags === "string"
          ? (editing.tags as string).split(/[,，]/).map((t: string) => t.trim()).filter(Boolean)
          : editing.tags ?? [],
      };
      if (editing.id) await api.updateCard(editing.id, payload);
      else await api.createCard(payload);
      setEditing(null);
      await reload();
      onToast("已保存");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string, name: string) {
    if (!window.confirm(`删除角色「${name}」？（聊天记录保留）`)) return;
    setBusy(true);
    try {
      await api.deleteCard(id);
      if (activeId === id) setActiveId(null);
      setEditing(null);
      await reload();
      onApplied();
      onToast("已删除");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function doExport(card: Card) {
    try {
      const payload = await api.exportCard(card.id);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${card.name}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "导出失败");
    }
  }

  async function doImport(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    try {
      for (const f of Array.from(files)) {
        const card = await importCard(f);
        onToast(`已导入「${card.name}」`);
      }
      await reload();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "导入失败");
    } finally {
      setBusy(false);
      if (importRef.current) importRef.current.value = "";
    }
  }

  return (
    <>
      <div className={"drawer-mask" + (open ? " show" : "")} onClick={onClose} />
      <aside className={"drawer cards-drawer" + (open ? " show" : "")}>
        <div className="drawer-head">
          <h2>{editing ? (editing.id ? "编辑角色" : "新建角色") : "角色"}</h2>
          <button className="iconbtn" type="button" onClick={editing ? () => setEditing(null) : onClose} aria-label="关闭">
            ×
          </button>
        </div>

        {!editing ? (
          <div className="cards-body">
            <div className="cards-actions">
              <button className="act" type="button" onClick={() => setEditing({ ...EMPTY })}>
                新建角色
              </button>
              <button className="act ghost" type="button" disabled={busy} onClick={() => importRef.current?.click()}>
                导入卡（PNG/JSON）
              </button>
              <input
                ref={importRef}
                type="file"
                multiple
                accept=".png,.json"
                style={{ display: "none" }}
                onChange={(e) => doImport(e.target.files)}
              />
            </div>
            {activeId && (
              <button className="act ghost wide" type="button" disabled={busy} onClick={() => apply(null)}>
                停用当前角色（回到默认陪伴）
              </button>
            )}
            <div className="card-grid">
              {cards.length === 0 && (
                <div className="cards-empty">
                  还没有角色。
                  <br />
                  点上方「新建角色」捏一个，或导入 PNG/JSON 角色卡
                </div>
              )}
              {cards.map((c) => (
                <div key={c.id} className={"card-tile" + (c.id === activeId ? " active" : "")}>
                  <button className="card-face" type="button" onClick={() => setEditing({ ...c })}>
                    {c.avatar_url ? (
                      <img className="card-ava" src={`${API_BASE}${c.avatar_url}`} alt={c.name} />
                    ) : (
                      <span className="card-ava placeholder"><IconPerson size={26} /></span>
                    )}
                    <span className="card-name">{c.name}</span>
                    <span className="card-desc">
                      {(c.description || c.personality || "（未填人设）")
                        .split("{{user}}").join("你")
                        .split("{{char}}").join(c.name ?? "她")}
                    </span>
                    {c.tags.length > 0 && (
                      <span className="card-tags">{c.tags.slice(0, 3).map((t) => <i key={t}>{t}</i>)}</span>
                    )}
                  </button>
                  {c.id === activeId ? (
                    <span className="card-active-badge"><IconCheck size={12} /> 使用中</span>
                  ) : (
                    <button className="act small" type="button" disabled={busy} onClick={() => apply(c.id)}>
                      启用
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="cards-body editor">
            <div className="draft-box">
              <span className="draft-title">不会写？说一句设定，AI 帮你写整张卡</span>
              <div className="draft-row">
                <input
                  value={draftHint}
                  onChange={(e) => setDraftHint(e.target.value)}
                  placeholder="比如：19岁猫耳咖啡店店长，外冷内热"
                  onKeyDown={(e) => e.key === "Enter" && aiDraft()}
                />
                <button className="act small" type="button" disabled={mediaBusy !== ""} onClick={aiDraft}>
                  {mediaBusy === "draft" ? "撰写中…" : "帮我写"}
                </button>
              </div>
            </div>
            <label className="fld">
              <span>名字</span>
              <input value={editing.name ?? ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="她叫什么" />
            </label>
            <div className="fld">
              <span>形象照</span>
              <div className="avatar-row">
                {editing.avatar_url ? (
                  <img className="avatar-preview" src={`${API_BASE}${editing.avatar_url}`} alt="形象" />
                ) : (
                  <span className="avatar-preview placeholder"><IconPerson size={22} /></span>
                )}
                <div className="avatar-btns">
                  <button className="act small" type="button" disabled={!editing.id || mediaBusy !== ""} onClick={() => avatarRef.current?.click()}>
                    {mediaBusy === "upload" ? "上传中…" : "上传形象"}
                  </button>
                  <button className="act small ghost" type="button" disabled={!editing.id || mediaBusy !== ""} onClick={genAvatar}>
                    {mediaBusy === "gen" ? "生成中…" : "AI 生成"}
                  </button>
                  <button className="act small ghost" type="button" disabled={!editing.id || !editing.avatar || mediaBusy !== ""} onClick={inferFromAvatar}>
                    {mediaBusy === "infer" ? "读图中…" : "读图补人设"}
                  </button>
                </div>
              </div>
              {!editing.id && <span className="fld-hint">先保存一次，才能传形象照</span>}
              <input
                ref={avatarRef}
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                style={{ display: "none" }}
                onChange={(e) => uploadAvatar(e.target.files)}
              />
            </div>
            <label className="fld">
              <span>人设描述</span>
              <textarea rows={3} value={editing.description ?? ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} placeholder="她是谁？外貌、背景、和世界的关系…" />
            </label>
            <label className="fld">
              <span>性格</span>
              <textarea rows={2} value={editing.personality ?? ""} onChange={(e) => setEditing({ ...editing, personality: e.target.value })} placeholder="温柔、毒舌、慢热…" />
            </label>
            <label className="fld">
              <span>场景</span>
              <textarea rows={2} value={editing.scenario ?? ""} onChange={(e) => setEditing({ ...editing, scenario: e.target.value })} placeholder="故事发生在哪？你们现在什么处境？" />
            </label>
            <label className="fld">
              <span>开场白</span>
              <textarea rows={3} value={editing.first_mes ?? ""} onChange={(e) => setEditing({ ...editing, first_mes: e.target.value })} placeholder="新会话她说的第一句话。可以用 {{user}} 指代你、{{char}} 指代她" />
            </label>
            <label className="fld">
              <span>朗读音色</span>
              <select value={editing.voice ?? ""} onChange={(e) => setEditing({ ...editing, voice: e.target.value })}>
                {VOICES.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
            </label>
            <label className="fld">
              <span>示例对话</span>
              <textarea rows={4} value={editing.mes_example ?? ""} onChange={(e) => setEditing({ ...editing, mes_example: e.target.value })} placeholder={"{{user}}: 今天好累\n{{char}}: （靠过来）辛苦啦，我在听"} />
            </label>
            <div className="fld">
              <span>设定书<span className="fld-hint">（聊到关键词时才想起来的设定，会随角色卡一起导出）</span></span>
              {(editing.lorebook ?? []).length === 0 && (
                <span className="fld-hint lore-empty">还没有条目。例：关键词「青茗山」→ 内容「青茗山是她的故乡，山顶有千年灵泉」</span>
              )}
              {(editing.lorebook ?? []).map((entry, li) => (
                <div className="lore-entry" key={li}>
                  <div className="lore-head">
                    <input
                      value={(entry.keys ?? []).join(", ")}
                      onChange={(e) => {
                        const keys = e.target.value.split(/[,，]/).map((k) => k.trim()).filter(Boolean);
                        const lb = [...(editing.lorebook ?? [])];
                        lb[li] = { ...entry, keys };
                        setEditing({ ...editing, lorebook: lb });
                      }}
                      placeholder="关键词，逗号分隔（如：青茗山, 灵茶）"
                    />
                    <label className="lore-const" title="不看关键词，每轮都注入">
                      <input
                        type="checkbox"
                        checked={entry.constant ?? false}
                        onChange={(e) => {
                          const lb = [...(editing.lorebook ?? [])];
                          lb[li] = { ...entry, constant: e.target.checked };
                          setEditing({ ...editing, lorebook: lb });
                        }}
                      />
                      常驻
                    </label>
                    <button
                      className="iconbtn"
                      type="button"
                      aria-label="删除条目"
                      onClick={() => {
                        const lb = (editing.lorebook ?? []).filter((_, j) => j !== li);
                        setEditing({ ...editing, lorebook: lb });
                      }}
                    >
                      ×
                    </button>
                  </div>
                  <textarea
                    rows={2}
                    value={entry.content ?? ""}
                    onChange={(e) => {
                      const lb = [...(editing.lorebook ?? [])];
                      lb[li] = { ...entry, content: e.target.value };
                      setEditing({ ...editing, lorebook: lb });
                    }}
                    placeholder="这条设定的正文（自包含的一句话/一段话）"
                  />
                </div>
              ))}
              <button
                className="act small ghost"
                type="button"
                onClick={() =>
                  setEditing({
                    ...editing,
                    lorebook: [...(editing.lorebook ?? []), { keys: [], content: "", constant: false, order: 100, enabled: true }],
                  })
                }
              >
                + 加一条设定
              </button>
            </div>
            <label className="fld">
              <span>标签（逗号分隔，中英文逗号都行）</span>
              <input
                value={Array.isArray(editing.tags) ? editing.tags.join(", ") : (editing.tags as unknown as string) ?? ""}
                onChange={(e) => setEditing({ ...editing, tags: e.target.value as unknown as string[] })}
                placeholder="陪伴, 古风, 治愈"
              />
            </label>

            <button className="act ghost wide" type="button" onClick={() => setAdvanced(!advanced)}>
              {advanced ? "收起高级设置" : "高级设置"}
            </button>
            {advanced && (
              <>
                <label className="fld">
                  <span>角色专属系统提示</span>
                  <textarea rows={2} value={editing.system_prompt ?? ""} onChange={(e) => setEditing({ ...editing, system_prompt: e.target.value })} placeholder="附加的系统级指令（一般留空）" />
                </label>
                <label className="fld">
                  <span>历史尾部备注</span>
                  <textarea rows={2} value={editing.post_history_instructions ?? ""} onChange={(e) => setEditing({ ...editing, post_history_instructions: e.target.value })} placeholder="注入到对话尾部的指令（如：保持第一人称）" />
                </label>
                <label className="fld">
                  <span>作者备注（不发给模型）</span>
                  <textarea rows={2} value={editing.creator_notes ?? ""} onChange={(e) => setEditing({ ...editing, creator_notes: e.target.value })} />
                </label>
              </>
            )}

            <div className="editor-actions">
              <button className="act primary" type="button" disabled={busy} onClick={save}>
                保存
              </button>
              {editing.id && (
                <>
                  <button className="act ghost" type="button" onClick={() => doExport(editing as Card)} aria-label="导出">
                    <IconDownload size={13} /> 导出
                  </button>
                  <button className="act danger" type="button" disabled={busy} onClick={() => remove(editing.id!, editing.name ?? "")}>
                    删除
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
