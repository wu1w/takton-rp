# 念匣技术文档

> 面向开发者。用户向说明见 [README.md](../README.md)。

## 一、产品定位

本地自托管的陪伴型 AI（companion / RP）。单机运行，数据全部落在用户可见的
`文档/念匣`（platformdirs 解析），无任何遥测与上传。Takton 引擎血缘的独立产品线。

**延迟宪法**：聊天热路径禁止 LLM 调用、禁止联网。记忆装配（assemble）是纯规则
计算；一切需要模型的重活（摘要、领悟、策展）都在冷路径异步完成。

## 二、仓结构

```
takton-rp/
├─ core/                      # nianxia-core · Python 3.11 + FastAPI（真身）
│  ├─ launcher.py             # 冻结入口（PyInstaller）
│  ├─ nianxia-core.spec       # PyInstaller 构建配方
│  ├─ src/nianxia_core/
│  │  ├─ api/                 # /v1 薄路由：chat(SSE)/memory/cards/settings/
│  │  │                       #   media/backup/channels/system
│  │  ├─ memory/              # 记忆核心
│  │  │  ├─ assemble.py       #   上下文装配（纯规则，梯度收缩 scale 1.0→0.25）
│  │  │  ├─ recall.py         #   按需唤起（关键词打分，无向量库）
│  │  │  ├─ store.py          #   ProfileStore：facts/sessions(jsonl)/summaries
│  │  │  ├─ tokenmeter.py     #   CJK 保守 token 估算（1 token/字符）
│  │  │  ├─ tools.py          #   记忆工具（memory.remember 等，模型可调用）
│  │  │  └─ openloops.py      #   话头（未完结的话题，她会主动提起）
│  │  ├─ runtime/             # 编排层
│  │  │  ├─ companion.py      #   单轮主管线 run_chat / run_swipe / run_regen
│  │  │  ├─ cards.py          #   角色卡 CRUD（chara_card_v2 兼容）
│  │  │  ├─ growth.py         #   Growth 策展（冷路径，约定/偏好提炼）
│  │  │  ├─ summarize.py      #   会话摘要（冷路径）
│  │  │  ├─ epochs.py         #   封纪（长程记忆分期）
│  │  │  ├─ draft.py          #   AI 代笔（一句话扩写整张角色卡）
│  │  │  ├─ policy.py         #   base-safety 注入
│  │  │  └─ ambient.py        #   氛围轻工具
│  │  ├─ inference/           # 推理层
│  │  │  ├─ router.py         #   L0/L1 引擎选择 + ContextOverflowError
│  │  │  ├─ l0.py             #   L0 = llama-server sidecar（:7421，mmproj 视觉）
│  │  │  ├─ backend_packs.py  #   llama.cpp 后端包（cpu/vulkan…，sha256 锁定）
│  │  │  ├─ downloader.py     #   模型下载（流式+Range 断点续传）
│  │  │  ├─ image.py          #   生图（OpenAI 兼容 / 自建 ComfyUI 双采样，锁脸）
│  │  │  └─ tts.py            #   edge-tts 按卡音色朗读
│  │  ├─ channels/            # 社交通道：telegram / qqbot(官方) / onebot / weixin
│  │  │                       #   每通道可绑定专属角色（独立 profile，记忆隔离）
│  │  ├─ clock.py             # 设备时间唯一来源（ClockService）
│  │  ├─ config.py            # data_root 解析（NIANXIA_DATA_ROOT 可覆盖）
│  │  └─ storage/             # 原子写 + 文件锁
│  └─ tests/                  # pytest · 122 用例
├─ shells/desktop/            # PC 壳 · Vite + React 18 + TS + Tauri 2
│  ├─ src/                    # 单聊天屏 + 右侧生活面板 + 抽屉（iOS 玻璃风）
│  └─ src-tauri/              # Rust 壳：拉起/回收 core sidecar，首启播种模型
└─ scripts/install.ps1        # 源码一行安装
```

## 三、核心机制

### 3.1 记忆系统（SLM 分层长忆）

| 层 | 内容 | 写入路径 |
|---|---|---|
| 钉选事实 | 用户手动「记住」/模型工具记住 | 热（工具调用） |
| 会话摘要 | 老对话压缩成摘要注入 | 冷（阈值触发） |
| 年表/封纪 | 超长程分期 | 冷 |
| 话头 | 未完结话题 | 冷 |
| 软约定 | Growth 策展出的相处约定，用户确认后生效 | 冷+用户确认 |

**装配优先级**（assemble，预算紧张时从低到高砍）：
base-safety → 人设/卡 → 钉选 → 设备时间 → 活跃事实 → 摘要 → 年表 →
话头 → 氛围 → 软约定 → 设定书(6.6) → few-shot。

### 3.2 上下文守卫

- `tokenmeter`：CJK 1 token/字符保守估算；预算 = ctx×0.85 − 800 输出预留
- **主动收缩**：估算超预算 → 装配降档 1.0→0.5→0.25 再发
- **撞墙重试**：provider 返回 context overflow 特征错误 → 降档重试；
  已吐 delta 则不重试（防半截话重复写）
- 全档耗尽 → `context_overflow` 人话报错

### 3.3 角色卡

- chara_card_v2 兼容：PNG tEXt(keyword="chara") / JSON 导入导出
- `{{user}}`/`{{char}}` 渲染；mes_example few-shot 按原始占位符解析（先解析后渲染，顺序反了会静默全灭）
- **设定书 Lite**：触发词/内容/常驻/顺序/开关五要素（砍互斥组/递归/概率），
  随卡导入导出；子串匹配（中文友好），扫描当前 query+近期历史
- **Swipes**：回复变体重抽（‹ 1/2 › 切换，旧版保留）
- **消息编辑**：改自己上一条 → 截断后续 → 重新生成
- 角色 = 会话隔离：每张卡独立会话/记忆作用域（卡级 `card_id` scope）

### 3.4 推理分层

| 层 | 引擎 | 用途 |
|---|---|---|
| L0 | llama.cpp sidecar（Qwen3.5-2B Q4_K_M + mmproj 视觉） | 默认，离线，CPU 可跑 |
| L1 | 任意 OpenAI 兼容端点（tools 支持） | 设置里启用即接管聊天 |
| 生图 | OpenAI images / 自建 ComfyUI（Z-Image 双采样+锁脸） | 媒体设置配置 |

小模型结构化输出注意：Qwen3.5 系非流式草稿任务要 `chat_template_kwargs:
{enable_thinking: false}` + 足量 max_tokens，否则思考烧光 token 返回空；
JSON 解析需三级容错（严格→正则→整段兜底）。

### 3.5 社交通道

Telegram（长轮询）/ QQ 官方机器人 / OneBot / 微信（iLink 扫码）。
配对码白名单 → 消息走与 App 完全相同的 `run_chat` 管线（工具开启）→
记忆/会话与 App 共享同一 profile。每通道可 `POST /v1/channels/{ch}/bind`
绑定专属角色卡——内部建 `ch_<channel>` 独立 profile，人设/记忆/会话物理隔离。

## 四、从源码构建

### 4.1 环境

- Python 3.11+（core）、Node 18+（前端）、Rust stable + VS BuildTools（Tauri，可选）

### 4.2 core

```bash
cd core
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e .
PYTHONPATH=src python -m pytest -q               # 122 用例
PYTHONPATH=src python -m nianxia_core            # :7420，含同源托管前端
```

### 4.3 桌面壳

```bash
cd shells/desktop
npm ci && npm run build        # tsc + vite → dist/（core 可直接托管）
npm run tauri:build            # 需 Rust；产出 MSI + NSIS 安装包
```

### 4.4 一键包（维护者）

```bash
# 1) core 冻结（必须先清空 PYTHONPATH 再精确注入，否则 exe 静默缺包）
cd core && PYTHONPATH=src .venv/Scripts/python -m PyInstaller nianxia-core.spec --noconfirm
cp dist/nianxia-core.exe ../shells/desktop/src-tauri/binaries/nianxia-core-x86_64-pc-windows-msvc.exe
# 2) 模型播种目录（安装包内置 L0 主模型，~1.4GB）
#    把 *.gguf 放进 shells/desktop/resources/models/
#    注意：NSIS 安装包有 2GB 上限——只放主模型，视觉组件 mmproj 走运行时下载
#    （POST /v1/engine/l0/download 传 mmproj URL，见 inference/downloader.py）
# 3) Tauri 重打（重打前三连杀：nianxia-shell / nianxia-core / llama-server）
cd shells/desktop && npm run tauri:build
```

## 五、配置与数据

| 位置 | 内容 |
|---|---|
| `文档/念匣/profiles/<id>/` | persona / facts / sessions(jsonl) / summaries |
| `文档/念匣/cards/` | 角色卡（全局，跨 profile 启用） |
| `文档/念匣/models/` | L0 模型（安装包播种或 App 内下载） |
| `文档/念匣/secrets/` | API key（gitignore 同级保护，备份默认剥离） |
| `文档/念匣/app-settings.json` | 媒体/通道/引擎设置 |

环境变量：`NIANXIA_PORT`（默认 7420）、`NIANXIA_DATA_ROOT`（默认 Documents/念匣）。

## 六、工程纪律（贡献者）

1. 热路径禁 LLM / 禁联网；2. 设备时间统一 ClockService；3. 禁写死路径；
4. Profile 物理隔离，一切读写带 `profile_id`；5. 手动钉选永远优先；
6. 密钥不回显；7. facts/sessions append-only（supersede 不撕历史）；
8. 改 core 必过 `pytest -q` 全绿，改壳必过 `npm run build`。
