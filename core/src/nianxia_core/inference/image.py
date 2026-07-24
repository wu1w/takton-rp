"""画图：OpenAI 兼容 images API 或自建 ComfyUI 双采样；支持按角色卡锁脸。

- openai：media.image.base_url + model → /images/generations
- comfy：media.image.base_url=http://<comfy主机>:8188（或 backend=comfy）
  走 Z-Image Base→精修 双采样

锁脸策略（随启用角色切换）：
1. 文本锁：card.face_prompt > description 外貌句 > 名字
2. 参考图路径：card.last_portrait > card.avatar（写入元数据；文生图主路径靠提示词锁脸）
3. 成功后回写 last_portrait，供下次同一角色复用
"""

from __future__ import annotations

import base64
import json
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import httpx

from ..models import CharacterCard


def _image_key(data_root: Path) -> str | None:
    p = data_root / "secrets" / "image.key"
    if p.exists():
        k = p.read_text(encoding="utf-8").strip()
        return k or None
    return None


def resolve_backend(image_cfg: dict[str, Any]) -> str:
    """openai | comfy"""
    b = (image_cfg.get("backend") or image_cfg.get("preset_id") or "").lower().strip()
    if b in ("comfy", "comfyui", "aiga", "aiga-comfy"):
        return "comfy"
    base = (image_cfg.get("base_url") or "").lower()
    if "8188" in base or "comfy" in base:
        return "comfy"
    return "openai"


def face_lock_text(card: CharacterCard | None) -> str:
    if card is None:
        return ""
    if (card.face_prompt or "").strip():
        return f"同一位角色「{card.name}」，外貌锁定：{card.face_prompt.strip()}。五官发型气质始终一致，禁止换脸"
    desc = (card.description or "").strip()
    if not desc:
        return f"同一位角色「{card.name}」，外貌身份始终一致，五官固定"
    # 取 description 前 160 字作弱锁
    snippet = re.sub(r"\s+", " ", desc)[:160]
    return f"同一位角色「{card.name}」，外貌锁定：{snippet}。五官发型气质始终一致，禁止换脸"


def reference_portrait_rel(card: CharacterCard | None) -> str:
    if card is None:
        return ""
    return (card.last_portrait or card.avatar or "").strip()


def assemble_locked_prompt(
    scene: str,
    card: CharacterCard | None = None,
    *,
    compose: str = "half",
) -> tuple[str, str, str]:
    """返回 (positive, negative, ref_rel)。"""
    scene = (scene or "").strip()
    lock = face_lock_text(card)
    compose_hint = {
        "full": "全身旅行纪实构图，从头顶到脚完整入镜",
        "half": "半身构图，大腿中部到头顶，脸清晰",
        "portrait": "胸像构图，强调面部细节",
    }.get(compose, "半身构图，脸清晰")
    if lock:
        positive = f"{lock}。构图：{compose_hint}。场景：{scene}"
    else:
        positive = f"{compose_hint}。{scene}"
    negative = (
        "换脸，另一张脸，五官不一致，不同的人，塑料皮肤，磨皮，CGI，3D渲染，"
        "水印，文字，logo，畸形手指，多余肢体"
    )
    return positive, negative, reference_portrait_rel(card)


def _http_json(method: str, url: str, data: dict | None = None, timeout: float = 180.0) -> dict:
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_dual_workflow(
    positive: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    base_steps: int = 24,
    base_cfg: float = 3.5,
    refine_steps: int = 8,
    refine_denoise: float = 0.3,
) -> dict:
    """Z-Image Base→精修 双采样工作流。"""
    return {
        "40": {
            "class_type": "ZEngineerCLIPLoaderGGUF",
            "inputs": {"gguf_name": "Z-Image-Engineer-V6-Q8_0.gguf", "device": "default"},
        },
        "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "28": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "z_image_base_int8_convrot.safetensors",
                "weight_dtype": "default",
            },
        },
        "31": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "beyond_reality_z_image_3.0_fp8.safetensors",
                "weight_dtype": "default",
            },
        },
        "110": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["28", 0], "shift": 3.0},
        },
        "111": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["31", 0], "shift": 3.0},
        },
        "27": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["40", 0], "text": positive},
        },
        "26": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["40", 0], "text": negative},
        },
        "13": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "300": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["110", 0],
                "positive": ["27", 0],
                "negative": ["26", 0],
                "latent_image": ["13", 0],
                "seed": seed,
                "steps": base_steps,
                "cfg": base_cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "800": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["300", 0], "vae": ["29", 0]},
        },
        "15": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["800", 0], "vae": ["29", 0]},
        },
        "301": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["111", 0],
                "positive": ["27", 0],
                "negative": ["26", 0],
                "latent_image": ["15", 0],
                "seed": seed,
                "steps": refine_steps,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": refine_denoise,
            },
        },
        "801": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["301", 0], "vae": ["29", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["801", 0], "filename_prefix": "nianxia"},
        },
    }


def _generate_comfy(
    data_root: Path,
    image_cfg: dict[str, Any],
    positive: str,
    negative: str,
    *,
    timeout: float = 300.0,
) -> dict[str, Any]:
    host = (image_cfg.get("base_url") or "").rstrip("/")
    if not host:
        return {"ok": False, "error": "ComfyUI 地址未配置：设置里填自建 ComfyUI 的地址"}
    # strip trailing /v1 if user pasted openai-style
    if host.endswith("/v1"):
        host = host[:-3]
    compose = (image_cfg.get("compose") or "half").lower()
    wh = {
        "full": (1152, 2048),
        "half": (1024, 1536),
        "portrait": (1024, 1280),
    }.get(compose, (1024, 1536))
    width = int(image_cfg.get("width") or wh[0])
    height = int(image_cfg.get("height") or wh[1])
    seed = int(image_cfg.get("seed") or random.randint(0, 2**31 - 1))
    wf = _build_dual_workflow(positive, negative, width, height, seed)
    try:
        r = _http_json("POST", f"{host}/prompt", {"prompt": wf}, timeout=60.0)
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"ComfyUI 不可达（{host}）：{e}"}
    except Exception as e:
        return {"ok": False, "error": f"提交 Comfy 失败：{e}"}
    if r.get("error") or r.get("node_errors"):
        return {
            "ok": False,
            "error": f"Comfy 拒收：{json.dumps(r, ensure_ascii=False)[:400]}",
        }
    pid = r.get("prompt_id")
    if not pid:
        return {"ok": False, "error": "Comfy 未返回 prompt_id"}
    t0 = time.time()
    hist: dict = {}
    while time.time() - t0 < timeout:
        try:
            hist = _http_json("GET", f"{host}/history/{pid}", timeout=30.0)
        except Exception:
            time.sleep(2)
            continue
        if pid in hist:
            break
        time.sleep(2)
    else:
        return {"ok": False, "error": "Comfy 生成超时"}
    status = (hist[pid].get("status") or {})
    if status.get("status_str") == "error":
        return {"ok": False, "error": f"Comfy 执行错误：{json.dumps(status, ensure_ascii=False)[:300]}"}
    images = [
        im
        for out in (hist[pid].get("outputs") or {}).values()
        for im in out.get("images") or []
    ]
    if not images:
        return {"ok": False, "error": "Comfy 无输出图"}
    img = images[0]
    q = (
        f"filename={img['filename']}"
        f"&subfolder={img.get('subfolder', '')}"
        f"&type={img.get('type', 'output')}"
    )
    try:
        with urllib.request.urlopen(f"{host}/view?{q}", timeout=120) as resp:
            raw = resp.read()
    except Exception as e:
        return {"ok": False, "error": f"下载成图失败：{e}"}
    out_dir = data_root / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"img-{int(time.time())}.png"
    out = out_dir / name
    out.write_bytes(raw)
    return {
        "ok": True,
        "path": f"media/{name}",
        "engine": "comfy-dual",
        "seed": seed,
        "width": width,
        "height": height,
    }


def _generate_openai(
    data_root: Path,
    image_cfg: dict[str, Any],
    prompt: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    base_url = (image_cfg.get("base_url") or "").rstrip("/")
    model = image_cfg.get("model") or ""
    if not base_url or not model:
        return {"ok": False, "error": "画图未配置：设置里填 base_url 和模型（或选自建 ComfyUI）"}
    key = _image_key(data_root)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    owns = client is None
    c = client or httpx.Client(timeout=60.0)
    try:
        r = c.post(
            f"{base_url}/images/generations",
            json={"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            return {"ok": False, "error": "服务商返回空结果"}
        out_dir = data_root / "media"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"img-{int(time.time())}.png"
        item = data[0]
        if item.get("b64_json"):
            out.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            ir = c.get(item["url"])
            ir.raise_for_status()
            out.write_bytes(ir.content)
        else:
            return {"ok": False, "error": "返回里既没有图也没有链接"}
        return {"ok": True, "path": f"media/{out.name}", "engine": "openai-images"}
    except Exception as e:
        return {"ok": False, "error": f"画图失败：{e}"}
    finally:
        if owns:
            c.close()


def generate_image(
    data_root: Path,
    image_cfg: dict[str, Any],
    prompt: str,
    client: httpx.Client | None = None,
    *,
    card: CharacterCard | None = None,
    face_lock: bool = True,
    compose: str | None = None,
) -> dict[str, Any]:
    """返回 {ok, path | error, face_lock?, ref?}。"""
    if not (image_cfg or {}).get("enabled", True) and not image_cfg.get("base_url"):
        # enabled 缺省 True 以兼容旧配置；base_url 空则下面会报未配置
        pass
    scene = (prompt or "").strip()
    if not scene:
        return {"ok": False, "error": "提示词为空"}

    cfg = dict(image_cfg or {})
    if compose:
        cfg["compose"] = compose
    backend = resolve_backend(cfg)

    if face_lock and card is not None:
        positive, negative, ref = assemble_locked_prompt(
            scene, card, compose=cfg.get("compose") or "half"
        )
    else:
        positive, negative, ref = scene, "watermark, text, logo", ""

    if backend == "comfy":
        r = _generate_comfy(data_root, cfg, positive, negative)
    else:
        r = _generate_openai(data_root, cfg, positive, client=client)

    if r.get("ok"):
        r["face_lock"] = bool(face_lock and card is not None)
        r["ref"] = ref
        r["locked_prompt"] = positive[:200]
        # 回写角色 last_portrait
        if card is not None and r.get("path"):
            try:
                from ..runtime.cards import CardStore

                store = CardStore(data_root)
                live = store.get(card.id)
                if live is not None:
                    # 复制一份到 portraits/ 固定名，便于「上一张」稳定引用
                    src = data_root / r["path"]
                    port_dir = data_root / "media" / "portraits"
                    port_dir.mkdir(parents=True, exist_ok=True)
                    dest_rel = f"media/portraits/{card.id}_last.png"
                    dest = data_root / dest_rel
                    if src.is_file():
                        dest.write_bytes(src.read_bytes())
                        live.last_portrait = dest_rel
                        store.save(live)
                        r["last_portrait"] = dest_rel
            except Exception:
                pass
    return r
