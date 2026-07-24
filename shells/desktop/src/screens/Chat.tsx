import React, { useEffect, useRef, useState } from "react";
import { api, chatStream, swipeStream, regenStream, editMessage, uploadMedia, API_BASE } from "../api";
import type { Attachment } from "../api";
import { IconBookmark, IconSend, IconSparkle } from "../icons";

interface Chip {
  text: string;
  kind: "recall" | "tool";
}

interface Msg {
  role: "user" | "ai";
  text: string;
  time: string;
  id?: string; // 后端消息 id（swipe/edit 用）
  swipeIdx?: number;
  swipesCount?: number;
  chips?: Chip[];
  image?: string; // 画图产物（media/ 相对路径）
  atts?: Attachment[]; // 用户上传的附件
}

interface Props {
  profileId: string;
  connected: boolean;
  onToast: (msg: string) => void;
  onMemoryWritten: () => void;
  /** undefined=启动读最近会话；null=新会话；string=指定会话。key 变化强制重载 */
  sessionToLoad: { sid: string | null | undefined; key: number };
  onSessionChange: (sid: string | null) => void;
  /** 分支后跳转到新会话 */
  onOpenSession: (sid: string) => void;
}

function stamp(ts?: number) {
  const d = ts ? new Date(ts * 1000) : new Date();
  return (
    String(d.getHours()).padStart(2, "0") +
    ":" +
    String(d.getMinutes()).padStart(2, "0")
  );
}

export default function ChatScreen({ profileId, connected, onToast, onMemoryWritten, sessionToLoad, onSessionChange, onOpenSession }: Props) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [cardVoice, setCardVoice] = useState("");
  const [branching, setBranching] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [atts, setAtts] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  // 启用角色卡的朗读音色（空=默认）
  useEffect(() => {
    let alive = true;
    api
      .persona(profileId)
      .then((p) => {
        if (alive) setCardVoice(String((p.active_card as { voice?: string } | undefined)?.voice ?? ""));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [profileId]);

  async function pickFiles(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        const a = await uploadMedia(f);
        setAtts((prev) => [...prev, a]);
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  // 开屏/切换会话：全部读真实落盘数据；没有就是真空态
  useEffect(() => {
    let alive = true;
    (async () => {
      setLoaded(false);
      try {
        if (sessionToLoad.sid === null) {
          // 新会话
          if (!alive) return;
          setSessionId(null);
          onSessionChange(null);
          setMessages([]);
        } else {
          const s =
            sessionToLoad.sid === undefined
              ? await api.latestSession(profileId)
              : await api.getSession(profileId, sessionToLoad.sid);
          if (!alive) return;
          if (s.session_id) {
            setSessionId(s.session_id);
            onSessionChange(s.session_id);
          }
          setMessages(
            s.items
              .filter((m) => m.role === "user" || m.role === "assistant")
              .map((m: any) => ({
                role: m.role === "user" ? ("user" as const) : ("ai" as const),
                text: m.content,
                time: stamp(m.ts),
                id: m.id,
                swipeIdx: m.swipe_idx ?? 0,
                swipesCount: Array.isArray(m.swipes) && m.swipes.length > 0 ? m.swipes.length : undefined,
              }))
          );
        }
      } catch {
        /* Core 离线：保持空态 */
      } finally {
        if (alive) setLoaded(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [profileId, sessionToLoad.key]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function autosize() {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }

  function appendChipToLast(chip: Chip) {
    setMessages((m) => {
      const next = [...m];
      const last = next[next.length - 1];
      if (last && last.role === "ai") {
        const chips = [...(last.chips ?? []), chip];
        next[next.length - 1] = { ...last, chips };
      }
      return next;
    });
  }

  function setLastAiText(text: string) {
    setMessages((m) => {
      const next = [...m];
      const last = next[next.length - 1];
      if (last && last.role === "ai") next[next.length - 1] = { ...last, text };
      return next;
    });
  }

  async function rememberMessage(text: string) {
    try {
      await api.addFact(profileId, text, true);
      onToast("已钉进记忆 · 下轮生效");
      onMemoryWritten();
    } catch {
      onToast("Core 未连接，没存上");
    }
  }

  async function speakMessage(text: string) {
    try {
      const r = await api.tts(text, cardVoice);
      if (r.ok && r.path) {
        new Audio(api.mediaUrl(r.path)).play().catch(() => onToast("播放失败"));
      } else {
        onToast(r.error || "朗读失败");
      }
    } catch {
      onToast("Core 未连接");
    }
  }

  /** 从第 i 条消息之后重开一条分支（旧会话保留，随时回溯） */
  async function branchFrom(i: number) {
    if (!sessionId || branching) return;
    setBranching(true);
    try {
      const r = await api.branchSession(profileId, sessionId, i);
      onToast(`已开出分支（带走前 ${r.msg_count} 条）`);
      onOpenSession(r.session_id);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "分支失败");
    } finally {
      setBranching(false);
    }
  }

  async function getTier(): Promise<string> {
    const st = await api.settings().catch(() => null);
    return (st as any)?.media?.llm?.enabled ? "L1" : "L0";
  }

  /** Swipes：prev/next 切变体；new 重抽一个新变体（流式写回该条消息） */
  async function swipeMessage(idx: number, direction: "prev" | "next" | "new") {
    const m = messages[idx];
    if (!m?.id || !sessionId || streaming) return;
    if (direction === "new") setStreaming(true);
    let gotAny = false;
    try {
      const tier = await getTier();
      await swipeStream(profileId, sessionId, m.id, direction, tier, {
        onDelta: (t) => {
          gotAny = true;
          setMessages((prev) => {
            const next = [...prev];
            const cur = next[idx];
            if (cur) next[idx] = { ...cur, text: cur.text + t };
            return next;
          });
        },
        onSwipe: (p) => {
          setMessages((prev) => {
            const next = [...prev];
            const cur = next[idx];
            if (cur && cur.id === p.message_id) {
              next[idx] = { ...cur, text: p.content, swipeIdx: p.swipe_idx, swipesCount: p.swipes_count };
            }
            return next;
          });
        },
        onError: (msg) => {
          if (!gotAny && direction === "new") onToast(msg);
        },
      });
    } catch {
      if (direction === "new") onToast("重抽失败：Core 没连上");
    }
    if (direction === "new") setStreaming(false);
  }

  /** 编辑自己的消息 → 截断后续 → 自动重生成 */
  async function saveEdit(idx: number, text: string) {
    const m = messages[idx];
    if (!m?.id || !sessionId || !text.trim()) return;
    setEditingIdx(null);
    try {
      await editMessage(profileId, sessionId, m.id, text.trim());
      // 本地同步：改掉该条，截掉其后
      setMessages((prev) => {
        const next = prev.slice(0, idx + 1);
        next[idx] = { ...next[idx], text: text.trim() };
        return next;
      });
      // 自动重生成一条新回复
      setStreaming(true);
      setMessages((prev) => [...prev, { role: "ai", text: "", time: stamp(), chips: [] }]);
      let gotAny = false;
      const tier = await getTier();
      await regenStream(profileId, sessionId, tier, {
        onDelta: (t) => {
          gotAny = true;
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "ai") next[next.length - 1] = { ...last, text: last.text + t };
            return next;
          });
        },
        onError: (msg) => {
          if (!gotAny) onToast(msg);
        },
      });
    } catch (e) {
      onToast(e instanceof Error ? e.message : "编辑失败");
    } finally {
      setStreaming(false);
    }
  }

  async function send() {
    const text = input.trim();
    if ((!text && atts.length === 0) || streaming) return;
    const sentAtts = atts;
    setInput("");
    setAtts([]);
    requestAnimationFrame(autosize);
    setMessages((m) => [...m, { role: "user", text, time: stamp(), atts: sentAtts.length ? sentAtts : undefined }]);
    setStreaming(true);
    setMessages((m) => [...m, { role: "ai", text: "", time: stamp(), chips: [] }]);

    let gotAny = false;
    let failed = false;
    let memoryWritten = false;
    try {
      // 引擎：媒体设置里启用了云模型(L1)就优先走云端，否则本地 L0
      const st = await api.settings().catch(() => null);
      const tier = (st as any)?.media?.llm?.enabled ? "L1" : "L0";
      await chatStream(profileId, sessionId, text, tier, {
        onSession: (sid) => {
          setSessionId(sid);
          onSessionChange(sid);
        },
        onTrace: (info) => {
          const usage = (info.memory_usage ?? {}) as Record<string, any>;
          const recalled = (usage.recalled ?? []).length;
          if (recalled > 0) {
            appendChipToLast({ text: `唤起 ${recalled} 条相关记忆`, kind: "recall" });
          }
        },
        onDelta: (t) => {
          gotAny = true;
          setMessages((m) => {
            const next = [...m];
            const last = next[next.length - 1];
            if (last && last.role === "ai") {
              next[next.length - 1] = { ...last, text: last.text + t };
            }
            return next;
          });
        },
        onTool: (phase, human, payload) => {
          if (phase === "call") {
            appendChipToLast({ text: `用了：${human}`, kind: "tool" });
          } else {
            appendChipToLast({ text: human, kind: "tool" });
            if (human.startsWith("记下了")) memoryWritten = true;
            // 画图产物 → 图片消息插进聊天
            const img = payload?.image_path as string | undefined;
            if (img) {
              setMessages((prev) => [
                ...prev,
                { role: "ai", text: "", time: stamp(), image: img },
              ]);
            }
          }
        },
        onGrowth: (text) => {
          memoryWritten = true; // 刷新面板红点
          onToast(`Ta 有了新的领悟，等你确认：${text.slice(0, 18)}…`);
        },
        onError: (msg) => {
          failed = true;
          if (!gotAny) setLastAiText(msg); // 真实错误/未接入状态，直接给用户看
        },
      },
      sentAtts
    );
    } catch {
      failed = true;
      if (!gotAny) setLastAiText("（Core 没连上，先确认它已启动：python -m nianxia_core）");
    }
    if (failed) onToast("这轮没有生成回答");
    if (memoryWritten) onMemoryWritten();
    setStreaming(false);
  }

  return (
    <div className="chat-col">
      <div className="messages" ref={listRef}>
        {loaded && messages.length === 0 && (
          <div className="empty-state">
            <p>还没有对话。</p>
            <p className="dim">
              {connected
                ? "说点什么吧——不过提醒：推理引擎还没接入，先去「设置 · 怎么聊」配云钥匙。"
                : "Core 未连接。先启动它：python -m nianxia_core"}
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <React.Fragment key={i}>
            <div className={"row " + m.role}>
              {m.role === "ai" && <div className="ava" />}
              <div>
                <div className="bubble">
                  {m.image && (
                    <img
                      src={api.mediaUrl(m.image)}
                      alt="画"
                      style={{ display: "block", maxWidth: 260, borderRadius: 12, marginBottom: m.text ? 6 : 0 }}
                    />
                  )}
                  {m.atts?.map((a, j) =>
                    a.kind === "image" ? (
                      <img
                        key={j}
                        src={`${API_BASE}${a.url}`}
                        alt={a.name}
                        style={{ display: "block", maxWidth: 220, borderRadius: 12, marginBottom: m.text ? 6 : 0 }}
                      />
                    ) : (
                      <span key={j} className="att-file">附件：{a.name}</span>
                    )
                  )}
                  {editingIdx === i ? (
                    <div className="edit-box">
                      <textarea
                        value={editText}
                        autoFocus
                        onChange={(e) => setEditText(e.target.value)}
                        rows={3}
                      />
                      <div className="edit-actions">
                        <button type="button" className="textbtn" onClick={() => saveEdit(i, editText)}>保存</button>
                        <button type="button" className="textbtn dim" onClick={() => setEditingIdx(null)}>取消</button>
                      </div>
                    </div>
                  ) : (
                    m.text || (m.image || m.atts?.length ? "" : "…")
                  )}
                </div>
                <div className="stamp">
                  {m.time}
                  {m.role === "ai" && m.id && sessionId && (
                    <span className="swipe-ctl">
                      {(m.swipesCount ?? 0) > 1 && (
                        <>
                          <button
                            className="remember-btn"
                            type="button"
                            disabled={streaming || (m.swipeIdx ?? 0) <= 0}
                            onClick={() => swipeMessage(i, "prev")}
                          >
                            ‹
                          </button>
                          <span className="swipe-num">{(m.swipeIdx ?? 0) + 1}/{m.swipesCount}</span>
                          <button
                            className="remember-btn"
                            type="button"
                            disabled={streaming || (m.swipeIdx ?? 0) >= (m.swipesCount ?? 1) - 1}
                            onClick={() => swipeMessage(i, "next")}
                          >
                            ›
                          </button>
                        </>
                      )}
                      <button
                        className="remember-btn"
                        type="button"
                        disabled={streaming}
                        title="换个说法重抽一条（旧版保留，可左右切换）"
                        onClick={() => swipeMessage(i, "new")}
                      >
                        重抽
                      </button>
                    </span>
                  )}
                  {m.text && m.role === "ai" && (
                    <button
                      className="remember-btn"
                      type="button"
                      onClick={() => speakMessage(m.text)}
                    >
                      朗读
                    </button>
                  )}
                  {m.text && m.role === "user" && m.id && sessionId && editingIdx !== i && (
                    <button
                      className="remember-btn"
                      type="button"
                      disabled={streaming}
                      title="改掉这条，后面的对话重来"
                      onClick={() => { setEditingIdx(i); setEditText(m.text); }}
                    >
                      编辑
                    </button>
                  )}
                  {m.text && (
                    <button
                      className="remember-btn"
                      type="button"
                      onClick={() => rememberMessage(m.text)}
                    >
                      记住
                    </button>
                  )}
                </div>
              </div>
            </div>
            {m.chips && m.chips.length > 0 && (
              <div className="mem-chips">
                {m.chips.map((c, j) => (
                  <span key={j} className={"mem-chip" + (c.kind === "recall" ? "" : " gold")}>
                    {c.kind === "recall" ? <IconBookmark /> : <IconSparkle />}
                    {c.text}
                  </span>
                ))}
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
      <div className="composer-wrap">
        {atts.length > 0 && (
          <div className="att-chips">
            {atts.map((a, i) => (
              <span key={i} className="att-chip">
                {a.kind === "image" ? (
                  <img src={`${API_BASE}${a.url}`} alt={a.name} />
                ) : (
                  <span className="att-name">{a.name}</span>
                )}
                <button type="button" aria-label="移除" onClick={() => setAtts((p) => p.filter((_, j) => j !== i))}>
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="composer">
          <input
            ref={fileRef}
            type="file"
            multiple
            accept="image/*,.txt,.md,.csv,.log,.json,.yaml,.yml,.py,.js,.ts,.html,.css,.xml,.toml,.ini"
            style={{ display: "none" }}
            onChange={(e) => pickFiles(e.target.files)}
          />
          <button
            className="attach-btn"
            type="button"
            aria-label="添加图片或文件"
            disabled={uploading || streaming}
            onClick={() => fileRef.current?.click()}
          >
            {uploading ? "…" : "+"}
          </button>
          <textarea
            ref={areaRef}
            rows={1}
            placeholder={connected ? "写点什么…" : "Core 未连接"}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              autosize();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button
            className="send"
            type="button"
            aria-label="发送"
            disabled={(!input.trim() && atts.length === 0) || streaming}
            onClick={send}
          >
            <IconSend size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
