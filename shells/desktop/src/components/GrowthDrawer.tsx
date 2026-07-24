import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, GrowthItem } from "../api";
import { IconSparkle } from "../icons";

/**
 * 他的领悟：待确认软约定队列（确认/拒绝/钉成硬规则）。
 *
 * 必须 portal 到 document.body：SidePanel 的 `.panel` 有 backdrop-filter + overflow，
 * 会把 position:fixed 抽屉裁成「只剩右侧一窄条 + 标题被截断」的残缺态。
 */
export default function GrowthDrawer({
  open,
  profileId,
  onClose,
  onChanged,
  onToast,
}: {
  open: boolean;
  profileId: string;
  onClose: () => void;
  onChanged: () => void;
  onToast: (m: string) => void;
}) {
  const [items, setItems] = useState<GrowthItem[]>([]);

  async function reload() {
    try {
      const r = await api.listGrowth(profileId, "pending");
      setItems(r.items);
    } catch {
      /* 离线保持空 */
    }
  }

  useEffect(() => {
    if (open) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, profileId]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function act(g: GrowthItem, action: "confirm" | "reject" | "pin") {
    try {
      await api.growthAction(profileId, g.id, action);
      onToast(
        action === "confirm"
          ? "已确认 · 下轮起效"
          : action === "pin"
          ? "已钉成硬规则 · 永远优先"
          : "已拒绝"
      );
      reload();
      onChanged();
    } catch {
      onToast("Core 未连接");
    }
  }

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        className={"drawer-mask" + (open ? " show" : "")}
        onClick={onClose}
        aria-hidden={!open}
      />
      <aside
        className={"drawer growth-drawer" + (open ? " show" : "")}
        role="dialog"
        aria-modal={open}
        aria-label="他的领悟"
        aria-hidden={!open}
      >
        <div className="drawer-head">
          <h2>他的领悟</h2>
          <button className="textbtn" type="button" onClick={onClose}>
            完成
          </button>
        </div>
        <p className="note" style={{ paddingTop: 0 }}>
          聊久了他会把自己的领悟放在这里等你点头。确认前不会生效。
        </p>
        <div className="card">
          {items.length === 0 && (
            <p className="hint" style={{ padding: 12 }}>
              暂时没有待确认的领悟。多聊聊，他会慢慢懂你。
            </p>
          )}
          {items.map((g) => (
            <div
              className="cell static"
              key={g.id}
              style={{ alignItems: "flex-start" }}
            >
              <span className="tile purple">
                <IconSparkle />
              </span>
              <span className="body">
                <div className="t" style={{ whiteSpace: "normal" }}>
                  {g.text}
                </div>
                <div className="d" style={{ whiteSpace: "normal" }}>
                  来自：「{g.source_excerpt}」· 置信{" "}
                  {Math.round(g.confidence * 100)}%
                </div>
                <div style={{ marginTop: 6, display: "flex", gap: 4, flexWrap: "wrap" }}>
                  <button
                    className="act"
                    type="button"
                    onClick={() => act(g, "confirm")}
                  >
                    确认
                  </button>
                  <button
                    className="act"
                    type="button"
                    onClick={() => act(g, "pin")}
                  >
                    钉成硬规则
                  </button>
                  <button
                    className="act danger"
                    type="button"
                    onClick={() => act(g, "reject")}
                  >
                    拒绝
                  </button>
                </div>
              </span>
            </div>
          ))}
        </div>
      </aside>
    </>,
    document.body
  );
}
