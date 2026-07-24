import React, { useEffect, useState } from "react";
import { api } from "../api";
import { IconChat, IconCheck, IconCloud, IconCpu, IconSparkle } from "../icons";

/** M1 首启向导：免责强触达 → 称呼与人设 → 模型路径。
 *  重装检测：本机已有数据时明确提示「不会覆盖」。
 */

const PRESETS = [
  { id: "gentle", name: "念念", style: "温柔陪伴型", short: "温柔知性的陪伴者。说话轻声细语，会记得你随口提过的小事，情绪稳定，擅长倾听。忙碌时安静陪着，难过时先抱抱再说话。" },
  { id: "sunny", name: "小晴", style: "元气活泼型", short: "开朗元气的伙伴。说话有精神，爱用语气词，会主动分享有趣的事，怕冷场，鼓励人时特别起劲。" },
  { id: "calm", name: "沈默", style: "冷静理性型", short: "冷静可靠的搭档。话不多但句句有用，逻辑清晰，遇到事情先帮你理思路，情绪平稳像深水。" },
  { id: "tsun", name: "小凛", style: "傲娇青梅型", short: "嘴上不饶人心里全是你。会嫌弃你不按时吃饭，转头又提醒你带伞。被夸会别扭，其实很在意你。" },
  { id: "mature", name: "阿岚", style: "成熟倾听型", short: "成熟稳重的倾听者。阅历感强，不打断不评判，回应简短有分量，像深夜还亮着的一盏灯。" },
];

export default function Wizard({
  profileId,
  onDone,
  onToast,
}: {
  profileId: string;
  onDone: (name: string) => void;
  onToast: (m: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [agreed, setAgreed] = useState(false);
  const [preset, setPreset] = useState(0);
  const [name, setName] = useState(PRESETS[0].name);
  const [custom, setCustom] = useState("");
  const [existing, setExisting] = useState<{ sessions: number; facts: number } | null>(null);
  const [busy, setBusy] = useState(false);

  // 重装检测：本机已有数据 → 明示不会覆盖
  useEffect(() => {
    (async () => {
      try {
        const s = await api.memoryStats(profileId);
        if (s.sessions > 0 || s.facts_total > 0) {
          setExisting({ sessions: s.sessions, facts: s.facts_total });
        }
      } catch {
        /* 离线也照常向导 */
      }
    })();
  }, [profileId]);

  async function finish() {
    setBusy(true);
    try {
      const short = custom.trim() || PRESETS[preset].short;
      await api.putPersona(profileId, { name: name.trim() || PRESETS[preset].name, short });
      await api.updateSettings({ wizard: { done: true } });
      onDone(name.trim() || PRESETS[preset].name);
    } catch {
      onToast("Core 未连接，设置没存上");
    }
    setBusy(false);
  }

  return (
    <div className="wizard-mask">
      <div className="wizard glass">
        {step === 0 && (
          <>
            <h1>欢迎来到念匣</h1>
            <p className="w-sub">开始之前，请花十秒读完这几句</p>
            <div className="w-scroll">
              <p><b>他是 AI，不是真人。</b>他会记住你说的话，会模拟在乎你，但他没有真实的情感和意识。</p>
              <p><b>你的数据只在这台电脑里。</b>聊天记录、记忆、人设全部存在本机文件，不上传、不同步，卸载应用也不会删除。</p>
              <p><b>云端大脑是例外。</b>如果你填入云模型的钥匙，聊天内容会发给那家模型厂商。用本地小模型则完全不联网。</p>
              <p><b>你可以随时清空一切。</b>数据目录里的文件删掉，他就什么也不记得了。</p>
            </div>
            {existing && (
              <p className="w-note">
                检测到本机已有数据（{existing.sessions} 段会话 · {existing.facts} 条记忆）——向导不会覆盖它们。
              </p>
            )}
            <button className="w-primary" disabled={!agreed} onClick={() => setStep(1)}>
              {agreed ? "我知道了，继续" : "请先勾选下方确认"}
            </button>
            <label className="w-agree">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              我明白他是 AI，数据只存在本机
            </label>
          </>
        )}

        {step === 1 && (
          <>
            <h1>他是谁</h1>
            <p className="w-sub">挑一个底色，之后都能改</p>
            <div className="w-presets">
              {PRESETS.map((p, i) => (
                <button
                  key={p.id}
                  className={"w-preset" + (preset === i ? " on" : "")}
                  type="button"
                  onClick={() => { setPreset(i); setName(p.name); }}
                >
                  <span className="w-preset-name">{p.name}</span>
                  <span className="w-preset-style">{p.style}</span>
                  <span className="w-preset-desc">{p.short.slice(0, 34)}…</span>
                </button>
              ))}
            </div>
            <div className="w-field">
              <label>叫他什么</label>
              <input value={name} maxLength={12} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="w-field">
              <label>补一句他的样子（可选）</label>
              <textarea
                rows={2}
                placeholder={PRESETS[preset].short.slice(0, 30) + "…"}
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
              />
            </div>
            <div className="w-actions">
              <button className="textbtn" type="button" onClick={() => setStep(0)}>上一步</button>
              <button className="w-primary" onClick={() => setStep(2)}>下一步</button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h1>他怎么思考</h1>
            <p className="w-sub">三选一，随时能换</p>
            <div className="w-models">
              <div className="w-model">
                <span className="tile green"><IconCpu /></span>
                <div className="w-model-body">
                  <b>本地小模型</b>
                  <p>完全离线 · 免费 · 把模型文件放进数据目录/models 即可</p>
                </div>
              </div>
              <div className="w-model">
                <span className="tile blue"><IconCloud /></span>
                <div className="w-model-body">
                  <b>云模型钥匙</b>
                  <p>更强更聪明 · 聊天会发给厂商 · 稍后在设置里填</p>
                </div>
              </div>
              <div className="w-model">
                <span className="tile gray"><IconChat /></span>
                <div className="w-model-body">
                  <b>先逛逛</b>
                  <p>不配模型也能记住事 · 随时回设置里补</p>
                </div>
              </div>
            </div>
            <div className="w-actions">
              <button className="textbtn" type="button" onClick={() => setStep(1)}>上一步</button>
              <button className="w-primary" disabled={busy} onClick={finish}>
                {busy ? "写入中…" : `好，就叫${name || PRESETS[preset].name}`}
              </button>
            </div>
          </>
        )}

        <div className="w-dots">
          {[0, 1, 2].map((i) => (
            <i key={i} className={step === i ? "on" : ""} />
          ))}
        </div>
      </div>
    </div>
  );
}
