import React, { useEffect, useState } from "react";
import { api, Fact } from "../api";
import GrowthDrawer from "./GrowthDrawer";
import {
  IconBookmark,
  IconCheck,
  IconClock,
  IconCloud,
  IconDoc,
  IconSparkle,
} from "../icons";

interface Stats {
  facts_total: number;
  facts_pinned: number;
  facts_loose: number;
  sessions: number;
  growth_pending: number;
  last_active: number;
}

type AmbientKey = "weather_enabled" | "headlines_enabled" | "device_time_enabled";

function Toggle({
  on,
  onClick,
  label,
}: {
  on: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      className={"switch" + (on ? " on" : "")}
      type="button"
      aria-label={label}
      onClick={onClick}
    />
  );
}

/** 右侧生活面板：记忆 + 领悟 + 生活小助手（开关真实落库到 app-settings） */
export default function SidePanel({
  profileId,
  onToast,
  refreshKey,
}: {
  profileId: string;
  onToast: (m: string) => void;
  refreshKey: number;
}) {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [newFact, setNewFact] = useState("");
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [growthOpen, setGrowthOpen] = useState(false);

  const ambient = (settings?.ambient ?? {}) as Record<string, any>;

  async function reload() {
    try {
      const [f, s, cfg] = await Promise.all([
        api.facts(profileId),
        api.memoryStats(profileId),
        api.settings(),
      ]);
      setFacts(f.items);
      setStats(s);
      setSettings(cfg);
    } catch {
      /* Core 离线时保持空态 */
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, refreshKey]);

  const pinned = facts.filter((f) => f.pinned);
  const loose = facts.filter((f) => !f.pinned);

  async function remember() {
    const text = newFact.trim();
    if (!text) return;
    try {
      await api.addFact(profileId, text, true);
      setNewFact("");
      onToast("已钉进记忆 · 下轮生效");
      reload();
    } catch {
      onToast("Core 未连接，没存上");
    }
  }

  async function unpin(f: Fact) {
    try {
      await api.setPin(profileId, f.id, !f.pinned);
      reload();
    } catch {
      onToast("Core 未连接");
    }
  }

  async function remove(f: Fact) {
    try {
      await api.deleteFact(profileId, f.id);
      onToast("已删除");
      reload();
    } catch {
      onToast("Core 未连接");
    }
  }

  /** 氛围开关：真实写回 app-settings.json，下轮装配生效 */
  async function flip(key: AmbientKey) {
    if (!settings) {
      onToast("Core 未连接，改不了");
      return;
    }
    const nextVal = !ambient[key];
    const next = {
      ...settings,
      ambient: { ...ambient, [key]: nextVal },
    };
    setSettings(next); // 乐观更新
    try {
      await api.putSettings(next);
      onToast(nextVal ? "已开启 · 下轮生效" : "已关闭 · 下轮生效");
    } catch {
      setSettings(settings); // 回滚
      onToast("保存失败");
    }
  }

  const swOn = (k: AmbientKey) => ambient[k] !== false;

  return (
    <div>
      <div className="panel-title">记忆</div>
      <div className="stat-row">
        <div className="stat">
          <div className="n">{stats?.facts_pinned ?? "–"}</div>
          <div className="l">钉选</div>
        </div>
        <div className="stat">
          <div className="n">{stats?.facts_loose ?? "–"}</div>
          <div className="l">记得</div>
        </div>
        <div className="stat">
          <div className="n">{stats?.sessions ?? "–"}</div>
          <div className="l">对话</div>
        </div>
      </div>

      <div className="panel-title">让 Ta 记住</div>
      <div className="card">
        <div className="field">
          <input
            placeholder="一句话，例如：用户住在杭州"
            value={newFact}
            onChange={(e) => setNewFact(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && remember()}
          />
          <p className="hint">写进就是钉选，装配时永远优先，永不裁掉。</p>
        </div>
        {pinned.map((f) => (
          <div className="cell static" key={f.id}>
            <span className="tile gold"><IconCheck /></span>
            <span className="body"><div className="t">{f.text}</div></span>
            <button className="act danger" type="button" onClick={() => remove(f)}>删</button>
          </div>
        ))}
        {pinned.length === 0 && (
          <p className="hint" style={{ padding: "0 12px 12px" }}>还没有钉选记忆。</p>
        )}
      </div>

      {loose.length > 0 && (
        <>
          <div className="panel-title">记得的事</div>
          <div className="card">
            {loose.map((f) => (
              <div className="cell static" key={f.id}>
                <span className="tile green"><IconBookmark /></span>
                <span className="body"><div className="t">{f.text}</div></span>
                <button className="act" type="button" onClick={() => unpin(f)}>钉</button>
                <button className="act danger" type="button" onClick={() => remove(f)}>删</button>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="panel-title">他的领悟</div>
      <div className="card">
        <button className="cell" type="button" onClick={() => setGrowthOpen(true)}>
          <span className="tile purple"><IconSparkle /></span>
          <span className="body">
            <div className="t">软约定 · 待确认</div>
            <div className="d">聊久了 Ta 会把想确认的习惯放这里</div>
          </span>
          {(stats?.growth_pending ?? 0) > 0 && <span className="count">{stats!.growth_pending}</span>}
        </button>
      </div>

      <div className="panel-title">生活小助手</div>
      <div className="card">
        <div className="cell static">
          <span className="tile teal"><IconCloud /></span>
          <span className="body">
            <div className="t">今天天气</div>
            <div className="d">有城市才生效 · 不强制提及</div>
          </span>
          <Toggle on={swOn("weather_enabled")} onClick={() => flip("weather_enabled")} label="天气" />
        </div>
        <div className="cell static">
          <span className="tile blue"><IconDoc /></span>
          <span className="body">
            <div className="t">今日谈资</div>
            <div className="d">隐性注入 · 绝非播报</div>
          </span>
          <Toggle on={swOn("headlines_enabled")} onClick={() => flip("headlines_enabled")} label="谈资" />
        </div>
        <div className="cell static">
          <span className="tile orange"><IconClock /></span>
          <span className="body">
            <div className="t">设备时间</div>
            <div className="d">每轮随本机时钟写入</div>
          </span>
          <Toggle on={swOn("device_time_enabled")} onClick={() => flip("device_time_enabled")} label="时间" />
        </div>
      </div>
      <p className="note">脑子和记忆都在这台电脑里。开关写进 app-settings，下轮生效。</p>

      <GrowthDrawer
        open={growthOpen}
        profileId={profileId}
        onClose={() => setGrowthOpen(false)}
        onChanged={reload}
        onToast={onToast}
      />
    </div>
  );
}
