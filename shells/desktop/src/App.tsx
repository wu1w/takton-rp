import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import ChatScreen from "./screens/Chat";
import SidePanel from "./components/SidePanel";
import SettingsDrawer from "./components/SettingsDrawer";
import CardsDrawer from "./components/CardsDrawer";
import Wizard from "./components/Wizard";
import { IconGrid, IconPerson, IconSliders } from "./icons";

/**
 * 单聊天屏 · 猫箱模型：
 * - 角色 = 会话（启用谁就聊谁的那条连续线）
 * - 会话列表对小白隐藏；切换角色即自动切对话与记忆隔离域
 */
export default function App() {
  const [connected, setConnected] = useState(false);
  const [profileId, setProfileId] = useState("default");
  const [profileName, setProfileName] = useState("念念");
  const [metDays, setMetDays] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cardsOpen, setCardsOpen] = useState(false);
  const [sessionToLoad, setSessionToLoad] = useState<{
    sid: string | null | undefined;
    key: number;
  }>({ sid: undefined, key: 0 });
  const [panelRefresh, setPanelRefresh] = useState(0);
  const [wizardOpen, setWizardOpen] = useState(false);
  const toastTimer = useRef<number>();

  // 调试/截图：?open=settings|cards
  useEffect(() => {
    const open = new URLSearchParams(window.location.search).get("open");
    if (open === "settings") setSettingsOpen(true);
    if (open === "cards") setCardsOpen(true);
  }, []);

  const refreshPersonaName = useCallback(async (pid: string) => {
    try {
      const p = await api.persona(pid);
      setProfileName(p.active_card?.name || p.name);
    } catch {
      /* 读不到就保持 */
    }
  }, []);

  /** 启用角色后：刷新顶栏名 + 加载该角色专属会话 + 刷新记忆面板 */
  const onCharacterSwitched = useCallback(
    async (sessionId?: string | null) => {
      await refreshPersonaName(profileId);
      setPanelRefresh((k) => k + 1);
      if (sessionId) {
        setSessionToLoad((s) => ({ sid: sessionId, key: s.key + 1 }));
      } else {
        // 回默认陪伴 / 未知：拉 latest（后端已按 active_card 解析）
        try {
          const latest = await api.latestSession(profileId);
          setSessionToLoad((s) => ({
            sid: latest.session_id ?? null,
            key: s.key + 1,
          }));
        } catch {
          setSessionToLoad((s) => ({ sid: null, key: s.key + 1 }));
        }
      }
    },
    [profileId, refreshPersonaName]
  );

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1800);
  }, []);

  useEffect(() => {
    let alive = true;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    (async () => {
      while (alive) {
        try {
          await api.health();
          const p = await api.profiles();
          if (!alive) return;
          setConnected(true);
          if (p.items.length > 0) {
            setProfileId(p.items[0].id);
            refreshPersonaName(p.items[0].id);
            try {
              const b = await api.bond(p.items[0].id);
              if (!alive) return;
              const days = Math.max(
                1,
                Math.floor((Date.now() / 1000 - b.met_at) / 86400) + 1
              );
              setMetDays(days);
            } catch {
              /* bond 读不到就不显示天数 */
            }
            try {
              const s = await api.settings();
              if (!alive) return;
              if (!s.wizard?.done) setWizardOpen(true);
            } catch {
              /* */
            }
          }
          return;
        } catch {
          if (alive) setConnected(false);
          await sleep(2000);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [refreshPersonaName]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="pava" />
        <div className="who">
          <div className="name">{profileName}</div>
          <div className="sub">
            {metDays ? `相识第 ${metDays} 天 · ` : ""}本地运行 · 数据零上传
          </div>
        </div>
        <div className="spacer" />
        <span className={"conn" + (connected ? " ok" : "")}>
          <i />
          {connected ? "Core 已连接" : "Core 未连接"}
        </span>
        <button
          className="iconbtn"
          type="button"
          aria-label="角色"
          title="换角色"
          onClick={() => setCardsOpen(true)}
        >
          <IconPerson />
        </button>
        <button
          className="iconbtn panel-btn"
          type="button"
          aria-label="生活面板"
          onClick={() => setPanelOpen(true)}
        >
          <IconGrid />
        </button>
        <button
          className="iconbtn"
          type="button"
          aria-label="设置"
          onClick={() => setSettingsOpen(true)}
        >
          <IconSliders />
        </button>
      </header>

      <div className="body">
        <main className="chat-area">
          <ChatScreen
            profileId={profileId}
            connected={connected}
            onToast={showToast}
            onMemoryWritten={() => setPanelRefresh((k) => k + 1)}
            sessionToLoad={sessionToLoad}
            onSessionChange={() => {
              /* 角色模型下不维护多会话选择态 */
            }}
            onOpenSession={(sid) =>
              setSessionToLoad((p) => ({ sid, key: p.key + 1 }))
            }
          />
        </main>
        <aside className="panel">
          <SidePanel
            profileId={profileId}
            onToast={showToast}
            refreshKey={panelRefresh}
          />
        </aside>
      </div>

      <div
        className={"drawer-mask" + (panelOpen ? " show" : "")}
        onClick={() => setPanelOpen(false)}
      />
      <aside className={"drawer" + (panelOpen ? " show" : "")}>
        <div className="drawer-head">
          <h2>记忆与生活</h2>
          <button
            className="iconbtn"
            type="button"
            onClick={() => setPanelOpen(false)}
            aria-label="关闭"
          >
            <IconGrid />
          </button>
        </div>
        <SidePanel
          profileId={profileId}
          onToast={showToast}
          refreshKey={panelRefresh}
        />
      </aside>

      <SettingsDrawer
        open={settingsOpen}
        profileId={profileId}
        onClose={() => setSettingsOpen(false)}
        onToast={showToast}
      />

      <CardsDrawer
        open={cardsOpen}
        profileId={profileId}
        onClose={() => setCardsOpen(false)}
        onToast={showToast}
        onApplied={(sessionId) => {
          void onCharacterSwitched(sessionId);
        }}
      />

      <div className={"toast" + (toast ? " show" : "")}>{toast}</div>

      {wizardOpen && (
        <Wizard
          profileId={profileId}
          onToast={showToast}
          onDone={(name) => {
            setWizardOpen(false);
            setProfileName(name);
            showToast(`好，${name}上线啦`);
            void onCharacterSwitched();
          }}
        />
      )}
    </div>
  );
}
