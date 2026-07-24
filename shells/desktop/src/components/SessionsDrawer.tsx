import React, { useEffect, useState } from "react";
import { api } from "../api";
import type { SearchHit } from "../api";
import { IconChat, IconSend } from "../icons";

interface SessionItem {
  session_id: string;
  updated_at: number;
  msg_count: number;
  preview: string;
}

function fmtTime(ts: number) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const hm =
    String(d.getHours()).padStart(2, "0") +
    ":" +
    String(d.getMinutes()).padStart(2, "0");
  return sameDay
    ? hm
    : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

/** 会话抽屉：列表 + 切换 + 新建 + 删除（全部真实数据） */
export default function SessionsDrawer({
  open,
  profileId,
  activeSessionId,
  onClose,
  onPick,
  onToast,
}: {
  open: boolean;
  profileId: string;
  activeSessionId: string | null;
  onClose: () => void;
  onPick: (sid: string | null) => void; // null = 新会话
  onToast: (m: string) => void;
}) {
  const [items, setItems] = useState<SessionItem[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  /** 跨会话搜索聊天记录；清空退回会话列表 */
  async function doSearch(text: string) {
    setQ(text);
    if (!text.trim()) {
      setHits(null);
      return;
    }
    setSearching(true);
    try {
      const r = await api.searchMessages(profileId, text.trim());
      setHits(r.items);
    } catch {
      onToast("Core 未连接");
    } finally {
      setSearching(false);
    }
  }

  async function reload() {
    try {
      const r = await api.listSessions(profileId);
      setItems(r.items);
    } catch {
      onToast("Core 未连接");
    }
  }

  useEffect(() => {
    if (open) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, profileId]);

  async function remove(sid: string) {
    try {
      await api.deleteSession(profileId, sid);
      onToast("已删除会话");
      if (sid === activeSessionId) onPick(null);
      reload();
    } catch {
      onToast("删除失败");
    }
  }

  return (
    <>
      <div className={"drawer-mask" + (open ? " show" : "")} onClick={onClose} />
      <aside className={"drawer" + (open ? " show" : "")}>
        <div className="drawer-head">
          <h2>会话</h2>
          <button className="textbtn" type="button" onClick={() => { onPick(null); onClose(); }}>
            新会话
          </button>
        </div>
        <div className="session-search">
          <input
            className="input"
            placeholder="搜索聊天记录…"
            value={q}
            onChange={(e) => doSearch(e.target.value)}
          />
        </div>
        {hits !== null ? (
          <div className="card">
            {searching && <p className="hint" style={{ padding: 12 }}>搜索中…</p>}
            {!searching && hits.length === 0 && (
              <p className="hint" style={{ padding: 12 }}>没有聊过「{q.trim()}」。</p>
            )}
            {!searching &&
              hits.map((h, i) => (
                <button
                  key={i}
                  className="cell"
                  type="button"
                  onClick={() => { onPick(h.session_id); onClose(); }}
                >
                  <span className={"tile " + (h.role === "user" ? "blue" : "pink")}>
                    <IconChat />
                  </span>
                  <span className="body">
                    <div className="t">{h.snippet}</div>
                    <div className="d">
                      {h.role === "user" ? "我" : "她"} · {fmtTime(h.ts)} · {h.session_preview || "新会话"}
                    </div>
                  </span>
                </button>
              ))}
          </div>
        ) : (
        <div className="card">
          {items.length === 0 && (
            <p className="hint" style={{ padding: 12 }}>还没有会话。</p>
          )}
          {items.map((s) => (
            <button
              key={s.session_id}
              className="cell"
              type="button"
              onClick={() => { onPick(s.session_id); onClose(); }}
            >
              <span className={"tile " + (s.session_id === activeSessionId ? "blue" : "gray")}>
                <IconChat />
              </span>
              <span className="body">
                <div className="t">{s.preview || "新会话"}</div>
                <div className="d">
                  {fmtTime(s.updated_at)} · {s.msg_count} 条
                  {s.session_id === activeSessionId ? " · 当前" : ""}
                </div>
              </span>
              <span
                className="act danger"
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); remove(s.session_id); }}
                onKeyDown={(e) => e.key === "Enter" && remove(s.session_id)}
              >
                删
              </span>
            </button>
          ))}
        </div>
        )}
        <p className="note">会话逐条落盘在本地 jsonl，崩溃不丢已写消息。</p>
      </aside>
    </>
  );
}
