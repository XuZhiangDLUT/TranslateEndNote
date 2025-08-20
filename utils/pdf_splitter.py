# -*- coding: utf-8 -*-
"""
从横向拼接的PDF中恢复左半部分，保留所有批注、高亮和链接。

该脚本执行以下操作：
- 逐页读取拼接后的PDF文件
- 将每页宽度裁剪为原宽度的一半
- 保存为新的PDF文件

此脚本是PDF横向拼接操作的逆过程。

输出规则：
- 输出目录：D:\Downloads
- 文件名格式：基于原文件名添加指定后缀
  例如：输入 file_merged.pdf -> 输出 file_merged_restored.pdf
"""

import os
import re
import tempfile
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests
from tqdm import tqdm

# ========= 在这里设置你的输入/输出 =========
MERGED_PDF = r"D:\User_Files\Homework\250817-EndNotePDF翻译\2\2105936161\Qian-2025-A guidance to intelligent metamateri.pdf"  # 待处理的拼接PDF文件路径（支持本地路径或URL）
OUTPUT_DIR = r"D:\Downloads"  # 输出目录路径
OUTPUT_SUFFIX = "_restored"  # 输出文件名后缀


# ========================================


def is_valid_url(path: str) -> bool:
    """检查字符串是否为有效的URL地址"""
    try:
        p = urlparse(path)
        return p.scheme in ("http", "https")
    except Exception:
        return False


def download_url_to_temporary_file(url: str) -> str:
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


def open_pdf_document(maybe_url_or_path: str):
    """打开PDF文档，支持本地路径或URL。返回PDF文档对象和临时文件路径。"""
    tmp_file = None
    if is_valid_url(maybe_url_or_path):
        tmp_file = download_url_to_temporary_file(maybe_url_or_path)
        doc = fitz.open(tmp_file)
    else:
        doc = fitz.open(maybe_url_or_path)

    if doc.is_encrypted:
        # 尝试使用空密码解密，失败则抛出异常
        if not doc.authenticate(""):
            raise ValueError(f"PDF 受密码保护，无法打开：{maybe_url_or_path}")
    return doc, tmp_file


def sanitize_filename_for_windows(name: str) -> str:
    """清理文件名中的非法字符，确保Windows系统兼容性。"""
    # 去除控制字符并替换 <>:"/\|?* 为 _
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    # 去掉首尾空格与点
    name = name.strip(" .")
    return name or "output"


def generate_output_filename_from_source(source_path: str, suffix: str) -> str:
    """基于源文件路径生成输出文件名。"""
    if is_valid_url(source_path):
        path = urlparse(source_path).path
        base = os.path.basename(path) or "output.pdf"
    else:
        base = os.path.basename(source_path) or "output.pdf"

    base = sanitize_filename_for_windows(base)
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


def extract_left_half_from_merged_pdf(merged_pdf: str, out_path: str):
    """
    从横向拼接的PDF中恢复左侧内容，保留所有批注和链接。
    
    参数：
        merged_pdf: 拼接后的PDF文件路径
        out_path: 输出文件路径
    
    说明：
        假设拼接时没有中缝间距，直接将页面宽度减半进行裁剪。
    """
    doc, tmp_file = open_pdf(merged_pdf)

    try:
        # 直接修改文档对象，然后保存为新文件
        for page in doc:
            current_rect = page.rect

            # 新宽度为原宽度的一半，高度保持不变
            new_width = current_rect.width / 2
            new_rect = fitz.Rect(0, 0, new_width, current_rect.height)

            # 通过重新设置页面边界框来裁剪右侧内容
            # 左侧的批注等对象由于坐标位于新边界内，因此会被完整保留
            _set_all_page_boxes(page, new_rect)

        # 保存修改后的文档
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        doc.save(out_path, garbage=4, deflate=True)
        print(f"已生成恢复后的文件：{out_path}")

    finally:
        doc.close()
        # 清理临时下载文件
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


if __name__ == "__main__":
    output_name = generate_output_filename_from_source(MERGED_PDF, OUTPUT_SUFFIX)
    output_path = os.path.join(OUTPUT_DIR, output_name)
    extract_left_half_from_merged_pdf(MERGED_PDF, output_path)