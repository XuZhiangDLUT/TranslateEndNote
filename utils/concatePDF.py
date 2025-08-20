# -*- coding: utf-8 -*-
"""
将两个页数相同的PDF进行横向拼接，保留左侧PDF的所有批注、高亮和链接。

操作流程：
- 复制左侧PDF的完整内容
- 扩展每页的宽度为原来的两倍（加上间距）
- 将右侧PDF对应页的内容嵌入到右侧区域

输出规则：
- 输出目录：D:\Downloads
- 文件名格式：基于左侧PDF文件名添加指定后缀
  例如：左侧 original.pdf -> 输出 original_merged.pdf

依赖包：
pip install pymupdf requests tqdm
"""

import os
import re
import tempfile
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests
from tqdm import tqdm

# ========= 在这里设置你的输入/输出 =========
LEFT_PDF   = r"D:\Docs\original.pdf"     # 左侧PDF文件路径（含批注的原文，支持本地路径或URL）
RIGHT_PDF  = r"D:\Docs\translated.pdf"   # 右侧PDF文件路径（译文，支持本地路径或URL）
OUTPUT_DIR = r"D:\Downloads"             # 输出目录路径
OUTPUT_SUFFIX = "_merged"                # 输出文件名后缀
GAP = 0                                  # 中缝间距（点），设为0时宽度翻倍
# ========================================


def is_url(path: str) -> bool:
    try:
        p = urlparse(path)
        return p.scheme in ("http", "https")
    except Exception:
        return False


def download_to_temp(url: str) -> str:
    """下载URL内容到临时文件，返回本地文件路径。"""
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    suffix = os.path.splitext(urlparse(url).path)[-1] or ".pdf"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    with open(tmp_path, "wb") as f, tqdm(
        total=total if total > 0 else None,
        unit="B", unit_scale=True, desc=f"Downloading {os.path.basename(tmp_path)}"
    ) as bar:
        for chunk in r.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)
                bar.update(len(chunk))
    return tmp_path


def open_pdf(maybe_url_or_path: str):
    """打开PDF文件，支持本地路径或URL。返回PDF文档对象和临时文件路径。"""
    tmp_file = None
    if is_url(maybe_url_or_path):
        tmp_file = download_to_temp(maybe_url_or_path)
        doc = fitz.open(tmp_file)
    else:
        doc = fitz.open(maybe_url_or_path)

    if doc.is_encrypted:
        # 尝试使用空密码解密，失败则抛出异常
        if not doc.authenticate(""):
            raise ValueError(f"PDF 受密码保护，无法打开：{maybe_url_or_path}")
    return doc, tmp_file


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符，确保Windows系统兼容性。"""
    # 去除控制字符并替换 <>:"/\|?* 为 _
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    # 去掉首尾空格与点
    name = name.strip(" .")
    return name or "output"


def left_based_output_name(left_src: str, suffix: str) -> str:
    """基于左侧PDF源文件路径生成输出文件名。"""
    if is_url(left_src):
        path = urlparse(left_src).path
        base = os.path.basename(path) or "output.pdf"
    else:
        base = os.path.basename(left_src) or "output.pdf"

    base = sanitize_filename(base)
    stem, ext = os.path.splitext(base)
    if not stem:
        stem = "output"
    # 强制使用 .pdf 后缀
    return f"{stem}{suffix}.pdf"


def _set_all_page_boxes(page: fitz.Page, rect: fitz.Rect):
    """设置页面的所有边界框，确保内容正确显示。"""
    for setter in ("set_mediabox", "set_cropbox", "set_trimbox", "set_bleedbox"):
        if hasattr(page, setter):
            try:
                getattr(page, setter)(rect)
            except Exception:
                pass


def merge_preserve_left_annotations(pdf_left: str, pdf_right: str, out_path: str, gap: float = 0):
    left_doc, left_tmp = open_pdf(pdf_left)
    right_doc, right_tmp = open_pdf(pdf_right)

    try:
        if len(left_doc) != len(right_doc):
            raise ValueError(f"两个PDF页数不同：左侧 {len(left_doc)} 页，右侧 {len(right_doc)} 页。")

        # 1) 以左侧PDF为基础，复制完整内容（保留所有批注和链接）
        out = fitz.open()
        out.insert_pdf(left_doc)  # 整册复制

        # 2) 逐页扩展页面宽度并嵌入右侧内容
        total = len(left_doc)
        for i in range(total):
            page = out[i]               # 已复制出的左侧第 i 页（含批注）
            lw, lh = page.rect.width, page.rect.height

            # 新页面宽度：2 * 左宽 + gap；高度保持
            new_w = 2 * lw + gap
            new_rect = fitz.Rect(0, 0, new_w, lh)

            # 扩大页面盒子，避免右半内容被裁剪
            _set_all_page_boxes(page, new_rect)

            # 把右侧 PDF 的第 i 页内容贴到右半区
            right_target = fitz.Rect(lw + gap, 0, 2 * lw + gap, lh)
            page.show_pdf_page(right_target, right_doc, i)

        # 3) 保存最终文件
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        out.save(out_path, garbage=4, deflate=True)
        out.close()
        print(f"已生成：{out_path}")

    finally:
        left_doc.close()
        right_doc.close()
        for tmp in (left_tmp, right_tmp):
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass


if __name__ == "__main__":
    output_name = left_based_output_name(LEFT_PDF, OUTPUT_SUFFIX)
    output_path = os.path.join(OUTPUT_DIR, output_name)
    merge_preserve_left_annotations(LEFT_PDF, RIGHT_PDF, output_path, gap=GAP)
