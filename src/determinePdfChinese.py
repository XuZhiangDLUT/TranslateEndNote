# -*- coding: utf-8 -*-
"""
PDF语言检测工具

使用视觉语言模型(VLM)检测PDF文件的主要语言

功能：
- 随机抽取PDF页面进行采样
- 将页面渲染为图像格式
- 调用VLM API进行语言判定
- 支持多种VLM模型
- 基于多数投票原则确定整体语言

依赖：
- PyMuPDF: PDF处理和渲染
- Pillow: 图像处理
- requests: HTTP请求
- openai: API客户端
"""

import io
import re
import os
import base64
import random
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

import fitz  # PyMuPDF
from PIL import Image
import requests

try:
    from openai import OpenAI
    _HAS_OPENAI_SDK = True
except ImportError:
    _HAS_OPENAI_SDK = False


# ======== 配置管理 ========
def load_config() -> Dict[str, Any]:
    """从配置文件加载设置参数"""
    config_path = Path(__file__).parent.parent / "configs" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"读取配置文件失败：{e}")

# ======== 配置参数 ========
CONFIG = load_config()

# VLM API配置 - 优先从环境变量读取
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", CONFIG["vlm_api_key"])
SILICONFLOW_MODEL   = CONFIG["vlm_model"]
SILICONFLOW_BASE    = CONFIG["vlm_base"]

# 模型特定配置
MODEL_HINTS = {
    "deepseek-ai/deepseek-vl2": {
        "note": "建议单次处理不超过2张图片，超出会自动缩放"
    },
    "THUDM/GLM-4.1V-9B-Thinking": {
        "note": "支持detail参数，可能产生思考风格输出"
    },
    "Qwen/Qwen2.5-VL-32B-Instruct": {
        "note": "支持detail参数，高分辨率会增加token消耗"
    },
}

# 提示词配置
SYSTEM_BRIEF = "返回语言分类结果，不输出推理过程"
PROMPT_CN = (
    "判断PDF页面的主要语言是中文还是非中文。\n"
    "只输出：中文 或 非中文"
)


def _render_page_to_jpeg_base64(doc: fitz.Document, page_index: int,
                                dpi: int = 150, jpeg_quality: int = 85) -> str:
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _build_vlm_message(image_b64: str, detail: str = "low") -> List[Dict[str, Any]]:
    """
    统一构造 VLM 输入消息（图片 + 文本）。
    支持 detail: low/high/auto（见官方说明）。:contentReference[oaicite:4]{index=4}
    """
    return [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}",
                "detail": detail
            },
        },
        {"type": "text", "text": PROMPT_CN},
    ]


def _post_vlm_openai_sdk(image_b64: str,
                         api_key: str,
                         base_url: str,
                         model: str,
                         detail: str = "low",
                         timeout: int = 60) -> str:
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    # GLM-4.1V-9B-Thinking 需要特殊参数和更长的输出
    if "GLM-4.1V-9B-Thinking" in model:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.7,
            max_tokens=512,
            messages=[
                {"role": "system", "content": SYSTEM_BRIEF},
                {"role": "user", "content": _build_vlm_message(image_b64, detail=detail)},
            ],
        )
    else:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=16,
            messages=[
                {"role": "system", "content": SYSTEM_BRIEF},
                {"role": "user", "content": _build_vlm_message(image_b64, detail=detail)},
            ],
            timeout=timeout,
        )
    return (resp.choices[0].message.content or "").strip()


def _post_vlm_requests(image_b64: str,
                       api_key: str,
                       base_url: str,
                       model: str,
                       detail: str = "low",
                       timeout: int = 60) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # GLM-4.1V-9B-Thinking 需要更长的输出和不同的温度设置
    if "GLM-4.1V-9B-Thinking" in model:
        payload = {
            "model": model,
            "temperature": 0.7,
            "max_tokens": 512,
            "messages": [
                {"role": "system", "content": SYSTEM_BRIEF},
                {"role": "user", "content": _build_vlm_message(image_b64, detail=detail)},
            ],
        }
    else:
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 16,
            "messages": [
                {"role": "system", "content": SYSTEM_BRIEF},
                {"role": "user", "content": _build_vlm_message(image_b64, detail=detail)},
            ],
        }
    
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return (j["choices"][0]["message"]["content"] or "").strip()


def _normalize_label(text: str) -> str:
    t = (text or "").strip()
    tl = t.lower()
    # 先看明确词
    if "非中文" in t or "non-chinese" in tl or "英文" in t or "english" in tl:
        return "非中文"
    if "中文" in t or "chinese" in tl:
        return "中文"
    # 兜底：是否含有中日韩统一表意文字
    return "中文" if re.search(r"[\u4e00-\u9fff]", t) else "非中文"


def detect_pdf_language_via_vlm(pdf_path: str,
                                k_pages: int = 5,
                                dpi: int = 150,
                                seed: Optional[int] = None,
                                model: str = SILICONFLOW_MODEL,
                                api_key: str = SILICONFLOW_API_KEY,
                                base_url: str = SILICONFLOW_BASE,
                                detail: str = "low",
                                per_page_timeout: int = 60) -> Dict[str, Any]:
    """
    使用 VLM 对 PDF 的随机 k 页进行语言判定（中文/非中文），并给出多数票结论。
    兼容模型:
        - deepseek-ai/deepseek-vl2
        - THUDM/GLM-4.1V-9B-Thinking
        - Qwen/Qwen2.5-VL-32B-Instruct

    detail: 'low'/'high'/'auto'（不同模型对 token 成本与预处理的规则不同）:contentReference[oaicite:5]{index=5}
    """
    if seed is not None:
        random.seed(seed)

    if detail not in ("low", "high", "auto"):
        raise ValueError("detail 必须为 'low' / 'high' / 'auto'")

    call_vlm = (_post_vlm_openai_sdk if _HAS_OPENAI_SDK else _post_vlm_requests)

    with fitz.open(pdf_path) as doc:
        n = doc.page_count
        if n == 0:
            return {
                "total_pages": 0,
                "sampled_pages": [],
                "page_results": [],
                "counts": {"中文": 0, "非中文": 0},
                "pdf_language": "非中文",
                "model": model,
                "detail": detail,
            }

        k = min(k_pages, n)
        indices = random.sample(range(n), k)

        page_results: List[Dict[str, Any]] = []
        count_zh = 0
        count_nonzh = 0

        for idx in indices:
            b64 = _render_page_to_jpeg_base64(doc, idx, dpi=dpi, jpeg_quality=85)
            raw = call_vlm(
                b64, api_key=api_key, base_url=base_url,
                model=model, detail=detail, timeout=per_page_timeout
            )
            label = _normalize_label(raw)
            (count_zh if label == "中文" else count_nonzh)  # no-op to avoid linter warnings
            if label == "中文":
                count_zh += 1
            else:
                count_nonzh += 1
            page_results.append({"page": idx, "label": label, "raw": raw})

        pdf_language = "非中文" if count_nonzh > count_zh else "中文"

        return {
            "total_pages": n,
            "sampled_pages": indices,
            "page_results": page_results,
            "counts": {"中文": count_zh, "非中文": count_nonzh},
            "pdf_language": pdf_language,
            "model": model,
            "detail": detail,
        }


if __name__ == "__main__":
    # 示例：可切换不同 VLM（任选其一）
    # model = "deepseek-ai/deepseek-vl2"
    # model = "THUDM/GLM-4.1V-9B-Thinking"
    # model = "Qwen/Qwen2.5-VL-32B-Instruct"
    result = detect_pdf_language_via_vlm(
        pdf_path=r"D:\Downloads\新建文件夹 (70)\1-s2.0-S0020740306002682-main.pdf",
        k_pages=5,
        dpi=150,
        seed=42,
        model="THUDM/GLM-4.1V-9B-Thinking",
        detail="low",  # 可改为 "high"/"auto"
    )
    print(result)
