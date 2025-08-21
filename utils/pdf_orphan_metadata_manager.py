# -*- coding: utf-8 -*-
"""
PDF元数据补全工具

功能：
- 为未配对的PDF文件补全元数据
- 使用VLM检测PDF是否为翻译版本
- 支持多级筛选规则
- 嵌入元数据JSON附件

依赖：
- PyMuPDF: PDF处理
- Pillow: 图像处理
- requests: HTTP请求
- openai: API客户端
"""

import os
import sys
import json
from pathlib import Path
from typing import Any, Dict
import argparse
import random
import time
import io
import base64
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image
import requests

try:
    from openai import OpenAI
    _HAS_OPENAI_SDK = True
except ImportError:
    _HAS_OPENAI_SDK = False

# 导入语言检测功能
try:
    sys.path.append(str(Path(__file__).parent.parent / "src"))
    from pdf_language_detector import (
        load_configuration,
        render_page_to_jpeg_base64,
        build_vlm_request_message,
        call_vlm_via_openai_sdk,
        call_vlm_via_http_requests,
        normalize_language_label
    )
    _HAS_VLM_DETECT = True
except ImportError:
    _HAS_VLM_DETECT = False

# 导入中文字符检测
import re
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# ======== 配置管理 ========
def load_configuration() -> Dict[str, Any]:
    """从配置文件加载设置参数"""
    config_path = Path(__file__).parent.parent / "configs" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"读取配置文件失败：{e}")


def get_config_value(config: Dict[str, Any], config_key: str, env_var: str, default: Optional[str] = None) -> str:
    """
    优先从配置文件读取配置值，如果配置值为空字符串则从环境变量读取
    
    Args:
        config: 配置字典
        config_key: 配置文件中的键名
        env_var: 环境变量名
        default: 默认值（可选）
    
    Returns:
        配置值
    """
    # 优先从配置文件读取
    config_value = config.get(config_key, "")
    
    # 如果配置值为空字符串，则从环境变量读取
    if config_value == "":
        config_value = os.getenv(env_var, default or "")
    
    return config_value


# ======== 配置参数 ========
CONFIG = load_configuration()

# 默认模型
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# VLM配置 - 优先从配置文件读取，如果为空则从环境变量读取
VLM_API_KEY = get_config_value(CONFIG, "vlm_api_key", "SILICONFLOW_API_KEY")
VLM_MODEL = CONFIG["vlm_model"]
VLM_BASE = CONFIG["vlm_base"]
VLM_K_PAGES = CONFIG["vlm_k_pages"]
VLM_DPI = CONFIG["vlm_dpi"]
VLM_DETAIL = CONFIG["vlm_detail"]
VLM_PER_PAGE_TIMEOUT = CONFIG["vlm_per_page_timeout"]

# ========== 跳过规则配置 (硬编码) ==========
SKIP_FILENAME_CONTAINS_CHINESE = True      # 跳过文件名含中文的PDF
SKIP_FILENAME_FORMAT_CHECK = True         # 跳过不符合作者-年份-标题格式的PDF
SKIP_MAX_FILE_SIZE = True                # 跳过超过最大文件大小的PDF
SKIP_MAX_PAGES = True                     # 跳过超过最大页数的PDF
SKIP_CONTAINS_SKIP_KEYWORDS = True        # 跳过包含跳过关键词的PDF

# ========== 处理参数配置 (硬编码) ==========
MAX_SIZE_BYTES = 104857600                # 最大文件大小（100MB）
MAX_PAGES = 500                          # 最大页数

# ========== 排除关键词 (硬编码) ==========
SKIP_KEYWORDS = [
    "clear",
    "clean", 
    "supplement",
    "pdf2zh-updated",
    "pdf2zh-merged"
]

# ======== 工具函数 ========

def iso_utc_now() -> str:
    """获取当前UTC时间的ISO格式字符串"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_page_sizes(pdf_path: Path) -> List[Dict[str, float]]:
    """获取PDF每页的尺寸信息（单位：pt）"""
    sizes = []
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                rect = page.rect
                sizes.append({"w": round(rect.width, 2), "h": round(rect.height, 2)})
    except Exception as e:
        print(f"  警告：获取PDF页面尺寸失败：{e}")
    return sizes

def has_metadata_attachment(pdf_path: Path) -> bool:
    """检查PDF是否已有元数据附件"""
    try:
        with fitz.open(pdf_path) as doc:
            return "pdf2zh.meta.json" in doc.embfile_names()
    except Exception:
        return False

def create_metadata(status: str, model: str = DEFAULT_MODEL, 
                   page_sizes: List[Dict[str, float]] = None) -> Dict[str, Any]:
    """创建元数据字典"""
    metadata = {
        "pdf2zh": {
            "status": status,
            "run_time_utc": iso_utc_now(),
            "model": model
        }
    }
    
    if page_sizes:
        metadata["pdf2zh"]["page_sizes_pt"] = page_sizes
    
    return metadata

def embed_metadata_attachment(pdf_path: Path, metadata: Dict[str, Any]) -> Tuple[bool, str]:
    """为PDF嵌入元数据附件"""
    try:
        with fitz.open(pdf_path) as doc:
            # 如果已有同名附件则跳过
            if "pdf2zh.meta.json" in doc.embfile_names():
                return True, "already_exists"
            
            # 创建附件内容
            payload = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
            
            # 添加附件
            doc.embfile_add("pdf2zh.meta.json", payload, desc="PDF2ZH metadata")
            
            # 设置AF关系（Associated Files）
            # 注意：'af' 键在某些PDF版本或PyMuPDF版本中可能不支持
            try:
                doc.set_metadata({"af": ["pdf2zh.meta.json"]})
            except Exception as af_error:
                # AF关系设置失败不影响主要功能，仅记录警告
                pass
            
            # 保存修改
            doc.saveIncr()
            
        return True, "success"
        
    except Exception as e:
        return False, str(e)

def split_image_horizontally(image: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """将图像水平分成左右两半"""
    width, height = image.size
    left_img = image.crop((0, 0, width // 2, height))
    right_img = image.crop((width // 2, 0, width, height))
    return left_img, right_img

def detect_translation_status_via_vlm(pdf_path: str, 
                                     model: str = "THUDM/GLM-4.1V-9B-Thinking",
                                     k_pages: int = 3,
                                     dpi: int = 150) -> Tuple[bool, str]:
    """
    使用VLM检测PDF是否为翻译版本
    
    判据：将页面分成左右两半，判断哪一侧更多为中文
    - 如果右侧中文数 >= 左侧中文数 且 左侧非中文数 > 右侧非中文数，则为翻译版
    - 否则为未翻译版
    
    返回: (是否为翻译版, 检测结果说明)
    """
    if not _HAS_VLM_DETECT:
        return False, "vlm_module_not_available"
    
    try:
        call_vlm = call_vlm_via_openai_sdk if _HAS_OPENAI_SDK else call_vlm_via_http_requests
        
        with fitz.open(pdf_path) as doc:
            n = doc.page_count
            if n == 0:
                return False, "empty_pdf"
            
            # 随机选择页面
            k = min(k_pages, n)
            indices = random.sample(range(n), k)
            
            left_chinese_count = 0
            right_chinese_count = 0
            left_non_chinese_count = 0
            right_non_chinese_count = 0
            
            for idx in indices:
                # 渲染页面为图像
                b64 = render_page_to_jpeg_base64(doc, idx, dpi=dpi, jpeg_quality=85)
                
                # 解码为PIL图像
                image_data = base64.b64decode(b64)
                image = Image.open(io.BytesIO(image_data))
                
                # 分割图像
                left_img, right_img = split_image_horizontally(image)
                
                # 处理左侧图像
                left_buf = io.BytesIO()
                left_img.save(left_buf, format="JPEG", quality=85)
                left_b64 = base64.b64encode(left_buf.getvalue()).decode("utf-8")
                
                left_result = call_vlm(
                    left_b64, 
                    api_key=VLM_API_KEY, 
                    base_url=VLM_BASE,
                    model=model,
                    detail=VLM_DETAIL,
                    timeout=VLM_PER_PAGE_TIMEOUT
                )
                left_label = normalize_language_label(left_result)
                
                if left_label == "中文":
                    left_chinese_count += 1
                else:
                    left_non_chinese_count += 1
                
                # 处理右侧图像
                right_buf = io.BytesIO()
                right_img.save(right_buf, format="JPEG", quality=85)
                right_b64 = base64.b64encode(right_buf.getvalue()).decode("utf-8")
                
                right_result = call_vlm(
                    right_b64, 
                    api_key=VLM_API_KEY, 
                    base_url=VLM_BASE,
                    model=model,
                    detail=VLM_DETAIL,
                    timeout=VLM_PER_PAGE_TIMEOUT
                )
                right_label = normalize_language_label(right_result)
                
                if right_label == "中文":
                    right_chinese_count += 1
                else:
                    right_non_chinese_count += 1
            
            # 判断是否为翻译版
            is_translated = (right_chinese_count >= left_chinese_count and 
                           left_non_chinese_count > right_non_chinese_count)
            
            result_info = (f"left_zh={left_chinese_count}, left_non_zh={left_non_chinese_count}, "
                          f"right_zh={right_chinese_count}, right_non_zh={right_non_chinese_count}")
            
            return is_translated, result_info
            
    except Exception as e:
        return False, f"detection_failed: {e}"

def contains_chinese_characters(text: str) -> bool:
    """检查文本是否包含中文字符"""
    return bool(CJK_PATTERN.search(text))


def is_normalized_name(stem: str) -> bool:
    """检查文件名是否符合 Author-YYYY-Title 格式"""
    if contains_chinese_characters(stem):
        return False
    parts = stem.split("-")
    if len(parts) < 3:
        return False
    author, year, title_rest = parts[0], parts[1], "-".join(parts[2:])
    if not (year.isdigit() and 1900 <= int(year) <= 2099 and len(year) == 4):
        return False
    if any(ch.isdigit() for ch in author):
        return False
    if not any(ch.isalpha() for ch in author):
        return False
    if not any(ch.isalpha() for ch in title_rest):
        return False
    return True


def get_page_count(pdf_path: Path) -> Optional[int]:
    """获取PDF页数"""
    try:
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    except Exception:
        try:
            from PyPDF2 import PdfReader
            with open(pdf_path, "rb") as f:
                reader = PdfReader(f)
                return len(reader.pages)
        except Exception:
            return None


def should_process_pdf(pdf_path: Path, exclusion_keywords: List[str] = None) -> Tuple[bool, str]:
    """
    检查是否应该处理此PDF文件
    返回: (是否处理, 排除原因)
    """
    if exclusion_keywords is None:
        exclusion_keywords = []
    
    stem = pdf_path.stem
    size = pdf_path.stat().st_size
    
    # 规则1：检查是否已有元数据
    if has_metadata_attachment(pdf_path):
        return False, "has_metadata"
    
    # 规则2：检查是否为备份文件
    if pdf_path.name.lower().endswith("_original.pdf"):
        return False, "is_backup"
    
    # 规则3：检查是否为生成的文件
    if pdf_path.name.lower().endswith((".mono.pdf", ".dual.pdf")):
        return False, "is_generated"
    
    # 规则4：检查是否有对应的原始文件
    original_path = pdf_path.with_name(f"{pdf_path.stem}_original.pdf")
    if original_path.exists():
        return False, "has_original_pair"
    
    # 规则5：检查文件名是否包含中文
    if SKIP_FILENAME_CONTAINS_CHINESE and contains_chinese_characters(pdf_path.name):
        return False, "filename_contains_chinese"
    
    # 规则6：检查文件名格式
    if SKIP_FILENAME_FORMAT_CHECK and not is_normalized_name(stem):
        return False, "bad_name_pattern"
    
    # 规则7：检查页数
    pages = get_page_count(pdf_path)
    if pages is None:
        return False, "page_count_failed"
    if SKIP_MAX_PAGES and pages > MAX_PAGES:
        return False, f"pages_gt_{MAX_PAGES}"
    
    # 规则8：检查文件大小
    if SKIP_MAX_FILE_SIZE and size >= MAX_SIZE_BYTES:
        return False, f"size_gt_{MAX_SIZE_BYTES}"
    
    # 规则9：检查排除关键词
    if SKIP_CONTAINS_SKIP_KEYWORDS and exclusion_keywords:
        filename_lower = pdf_path.name.lower()
        for keyword in exclusion_keywords:
            if keyword in filename_lower:
                return False, f"contains_keyword: {keyword}"
    
    return True, ""

def process_single_pdf(pdf_path: Path, model: str = DEFAULT_MODEL, 
                      vlm_model: str = "THUDM/GLM-4.1V-9B-Thinking",
                      dry_run: bool = False) -> Tuple[bool, str]:
    """
    处理单个PDF文件
    
    返回: (是否成功, 结果说明)
    """
    print(f"→ 处理：{pdf_path.name}")
    
    if dry_run:
        print("   （干运行模式）")
        return True, "dry_run"
    
    try:
        # 获取页面尺寸
        page_sizes = get_page_sizes(pdf_path)
        
        # 使用VLM检测翻译状态
        is_translated, detection_result = detect_translation_status_via_vlm(
            str(pdf_path), model=vlm_model
        )
        
        status = "translated" if is_translated else "untranslated"
        print(f"   检测结果：{status} ({detection_result})")
        
        # 创建元数据
        metadata = create_metadata(status, model, page_sizes)
        
        # 嵌入元数据
        success, result = embed_metadata_attachment(pdf_path, metadata)
        
        if success:
            print(f"   完成：已嵌入元数据 ({result})")
            return True, result
        else:
            print(f"   失败：{result}")
            return False, result
            
    except Exception as e:
        print(f"   错误：{e}")
        return False, str(e)

def scan_and_process_pdfs(root_dir: Path, model: str = DEFAULT_MODEL,
                          vlm_model: str = "THUDM/GLM-4.1V-9B-Thinking",
                          dry_run: bool = False) -> Dict[str, int]:
    """
    扫描并处理目录下的PDF文件
    
    返回: 统计信息字典
    """
    stats = {
        "total": 0,
        "processed": 0,
        "skipped": 0,
        "failed": 0
    }
    
    print(f"扫描目录：{root_dir}")
    if SKIP_KEYWORDS:
        print(f"排除关键词：{', '.join(SKIP_KEYWORDS)}")
    
    # 收集所有PDF文件
    pdf_files = []
    for root, _, files in os.walk(root_dir):
        for name in files:
            if name.lower().endswith(".pdf"):
                pdf_files.append(Path(root) / name)
    
    stats["total"] = len(pdf_files)
    print(f"发现 {len(pdf_files)} 个PDF文件")
    
    # 处理每个PDF文件
    for pdf_path in pdf_files:
        should_process, reason = should_process_pdf(pdf_path, SKIP_KEYWORDS)
        
        if not should_process:
            stats["skipped"] += 1
            print(f"跳过：{pdf_path.name} ({reason})")
            continue
        
        # 处理PDF
        success, result = process_single_pdf(pdf_path, model, vlm_model, dry_run)
        
        if success:
            stats["processed"] += 1
        else:
            stats["failed"] += 1
        
        # 添加短暂延迟避免API限制
        time.sleep(0.5)
    
    return stats

def scan_orphan_pdfs_for_metadata(root_path=None, model_name=None, vlm_model=None, dry_run=False):
    """
    扫描并处理未配对的PDF文件，为其添加元数据
    
    参数：
        root_path: 要处理的根目录路径，默认为EndNote PDF库目录
        model_name: 翻译模型名称，默认使用配置中的模型
        vlm_model: VLM模型名称，默认使用GLM-4.1V-9B-Thinking
        dry_run: 干运行模式，不实际修改文件
        
    返回：
        处理统计信息字典
    """
    # 设置默认参数
    if root_path is None:
        root_path = r"D:\Downloads\新建文件夹 (71)"
    if model_name is None:
        model_name = DEFAULT_MODEL
    if vlm_model is None:
        vlm_model = "THUDM/GLM-4.1V-9B-Thinking"
    
    # 检查目录是否存在
    root_path = Path(root_path).resolve()
    if not root_path.exists():
        print(f"错误：目录不存在：{root_path}")
        return None
    
    # 检查VLM模块
    if not _HAS_VLM_DETECT:
        print("错误：无法导入VLM检测模块")
        return None
    
    print("PDF元数据补全工具 - 孤儿文件处理")
    print("=" * 50)
    print(f"处理目录：{root_path}")
    print(f"翻译模型：{model_name}")
    print(f"VLM模型：{vlm_model}")
    print(f"干运行模式：{'是' if dry_run else '否'}")
    print("=" * 50)
    
    # 扫描和处理
    stats = scan_and_process_pdfs(
        root_path, 
        model=model_name,
        vlm_model=vlm_model,
        dry_run=dry_run
    )
    
    # 输出统计信息
    print("\n" + "=" * 50)
    print("处理完成：")
    print(f"  总文件数：{stats['total']}")
    print(f"  已处理：{stats['processed']}")
    print(f"  已跳过：{stats['skipped']}")
    print(f"  失败：{stats['failed']}")
    print("=" * 50)
    
    return stats

def main():
    """
    主函数：执行PDF孤儿文件元数据补全处理
    
    使用默认参数处理指定目录下的PDF文件
    """
    scan_orphan_pdfs_for_metadata()

if __name__ == "__main__":
    main()