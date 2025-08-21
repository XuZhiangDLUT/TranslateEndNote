# -*- coding: utf-8 -*-
"""
PDF批处理翻译工具

功能：
- 批量扫描指定目录下的PDF文件
- 调用pdf2zh进行翻译处理
- 支持多级跳过规则和失败重试机制
- 自动备份原始文件并嵌入元数据
- 支持OCR回退和错误处理

依赖：
- PyMuPDF (fitz): PDF文件处理
- pdf2zh: PDF翻译工具
"""

import os
import re
import csv
import time
import shutil
import subprocess
import tempfile
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
from dataclasses import dataclass

import sys

# 导入PDF语言检测功能
try:
    from pdf_language_detector import detect_pdf_language_via_vlm

    _HAS_VLM_DETECT = True
except ImportError:
    _HAS_VLM_DETECT = False
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============ 配置文件加载 ============

def load_configuration() -> Dict[str, Any]:
    """加载系统配置文件"""
    config_path = Path(__file__).parent.parent / "configs" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"读取配置文件失败：{e}")


# 加载配置
CONFIG = load_configuration()


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

# ========== 跳过规则配置 ==========
SKIP_TRANSLATED_BY_METADATA = CONFIG["skip_translated_by_metadata"]
SKIP_MAX_FILE_SIZE = CONFIG["skip_max_file_size"]
SKIP_MAX_PAGES = CONFIG["skip_max_pages"]
SKIP_FILENAME_FORMAT_CHECK = CONFIG["skip_filename_format_check"]
SKIP_FILENAME_CONTAINS_CHINESE = CONFIG["skip_filename_contains_chinese"]
SKIP_CONTAINS_SKIP_KEYWORDS = CONFIG["skip_contains_skip_keywords"]
SKIP_CHINESE_PDF_VLM = CONFIG["skip_chinese_pdf_vlm"]

# ========== 后处理配置 ==========
DELETE_MONO_PDF = CONFIG["delete_mono_pdf"]
DELETE_ALL_EXCEPT_FINAL = CONFIG["delete_all_except_final"]
SUPPRESS_SKIPPED_OUTPUT = CONFIG["suppress_skipped_output"]

# ========== 文件路径配置 ==========
PDF_ROOT = Path(CONFIG["pdf_root"])
PDF2ZH_EXE = Path(CONFIG["pdf2zh_exe"])
LOG_DIR: Optional[Path] = Path(CONFIG["log_dir"]) if CONFIG["log_dir"] else None

# ========== 翻译配置 ==========
LANG_IN = CONFIG["lang_in"]
LANG_OUT = CONFIG["lang_out"]
TRANSLATION_SERVICE = CONFIG["translation_service"]

# 硅基流动配置 - 优先从配置文件读取，如果为空则从环境变量读取
SILICONFLOW_API_KEY = get_config_value(CONFIG, "siliconflow_api_key", "SILICONFLOW_API_KEY")
SILICONFLOW_MODEL = CONFIG["siliconflow_model"]
SILICONFLOW_BASE = CONFIG["siliconflow_base"]

# ========== 处理参数配置 ==========
QPS_LIMIT = CONFIG["qps_limit"]
GAP = CONFIG["gap"]
MAX_SIZE_BYTES = CONFIG["max_size_bytes"]
MAX_PAGES = CONFIG["max_pages"]
MAX_TIME = CONFIG["max_time"]

# ========== VLM配置 - 优先从配置文件读取，如果为空则从环境变量读取 ==========
VLM_API_KEY = get_config_value(CONFIG, "vlm_api_key", "SILICONFLOW_API_KEY")
VLM_MODEL = CONFIG["vlm_model"]
VLM_BASE = CONFIG["vlm_base"]
VLM_K_PAGES = CONFIG["vlm_k_pages"]
VLM_DPI = CONFIG["vlm_dpi"]
VLM_DETAIL = CONFIG["vlm_detail"]
VLM_PER_PAGE_TIMEOUT = CONFIG["vlm_per_page_timeout"]

# =================================

LOG_PATH = (LOG_DIR or PDF_ROOT) / "batch_translate_log.csv"
# ======== 文件名/规则 ========
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def contains_chinese_characters(text: str) -> bool:
    """检查文本是否包含中文字符"""
    return bool(CJK_PATTERN.search(text))


def load_exclusion_keywords() -> List[str]:
    """从配置文件加载排除关键词列表"""
    return CONFIG.get("skip_keywords", [])


def contains_exclusion_keywords(filename: str, keywords: List[str]) -> bool:
    """检查文件名是否包含排除关键词"""
    if not keywords:
        return False

    filename_lower = filename.lower()
    for keyword in keywords:
        if keyword in filename_lower:
            return True
    return False


def check_translation_metadata_status(pdf_path: Path) -> Tuple[bool, str]:
    """
    检查PDF内嵌元数据中的翻译状态
    返回: (是否已翻译, 检查结果说明)
    """
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            # 获取嵌入文件列表
            embfiles = doc.embfile_names()

            # 查找 pdf2zh.meta.json 文件
            if "pdf2zh.meta.json" not in embfiles:
                return False, "no_metadata_found"

            # 读取元数据JSON内容
            meta_content = doc.embfile_get("pdf2zh.meta.json")
            if not meta_content:
                return False, "metadata_empty"

            # 解析JSON
            try:
                metadata = json.loads(meta_content.decode('utf-8'))
                status = metadata.get("pdf2zh.status", "")

                if status == "translated":
                    return True, "already_translated"
                elif status == "untranslated":
                    return False, "marked_untranslated"
                else:
                    return False, f"unknown_status:{status}"

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return False, f"metadata_parse_error:{e}"

    except Exception as e:
        # 如果检查元数据失败，不跳过文件，继续用其他规则判断
        return False, f"metadata_check_failed:{e}"


def detect_chinese_content_via_vlm(pdf_path: Path) -> Tuple[bool, str]:
    """
    使用视觉语言模型检测PDF是否为中文内容
    返回: (是否为中文PDF, 检测结果说明)
    """
    if not _HAS_VLM_DETECT:
        return False, "vlm_module_not_available"

    if not SKIP_CHINESE_PDF_VLM:
        return False, "vlm_detection_disabled"

    try:
        result = detect_pdf_language_via_vlm(
            pdf_path=str(pdf_path),
            k_pages=VLM_K_PAGES,
            dpi=VLM_DPI,
            seed=42,
            detail=VLM_DETAIL
        )

        chinese_count = result["counts"]["中文"]
        non_chinese_count = result["counts"]["非中文"]

        # 当中文页数 >= 非中文页数时，认为该PDF为中文
        is_chinese = chinese_count >= non_chinese_count

        return is_chinese, f"vlm_detected: zh={chinese_count}, non_zh={non_chinese_count}, total={result['total_pages']}"

    except Exception as e:
        # 检测失败时，不跳过文件，继续处理
        return False, f"vlm_detection_failed: {e}"


def should_exclude_from_processing(pdf_path: Path, exclusion_keywords: List[str], failure_counts: dict) -> Tuple[bool, str]:
    """
    检查是否应该排除此PDF文件不进行处理
    返回: (是否排除, 排除原因)
    """
    stem = pdf_path.stem
    size = pdf_path.stat().st_size

    # 检查累计失败次数
    if failure_counts.get(str(pdf_path), 0) >= 3:
        return True, "too_many_failures"

    backup_path = pdf_path.with_name(f"{stem}_original.pdf")
    lower_name = pdf_path.name.lower()

    # 先过滤：备份/生成文件自身不参与翻译
    if lower_name.endswith("_original.pdf"):
        return True, "is_backup_original"
    if lower_name.endswith(".mono.pdf") or lower_name.endswith(".dual.pdf"):
        return True, "is_generated_output"

    # 优先级最高：检查元数据中的翻译状态
    if SKIP_TRANSLATED_BY_METADATA:
        is_translated, metadata_info = check_translation_metadata_status(pdf_path)
        if is_translated:
            return True, f"already_translated_by_metadata:{metadata_info}"

    # 检查排除关键词
    if SKIP_CONTAINS_SKIP_KEYWORDS and contains_exclusion_keywords(pdf_path.name, exclusion_keywords):
        return True, "contains_exclusion_keywords"

    # 检查是否已存在备份
    if backup_path.exists():
        return True, "backup_exists"

    # 检查文件名是否包含中文
    if SKIP_FILENAME_CONTAINS_CHINESE and contains_chinese_characters(pdf_path.name):
        return True, "filename_contains_chinese"

    # 检查文件名格式
    if SKIP_FILENAME_FORMAT_CHECK and not is_normalized_name(stem):
        return True, "bad_name_pattern"

    # 检查页数
    pages = get_page_count(pdf_path)
    if pages is None:
        return True, "page_count_failed"
    if SKIP_MAX_PAGES and pages > MAX_PAGES:
        return True, f"pages_gt_{MAX_PAGES}"

    # 检查文件大小
    if SKIP_MAX_FILE_SIZE and size >= MAX_SIZE_BYTES:
        return True, f"size_gt_{MAX_SIZE_BYTES}"

    # 检查是否为中文PDF（使用大模型检测）- 放在最后，仅在其他规则都不排除时才运行
    if SKIP_CHINESE_PDF_VLM:
        is_chinese, detection_result = detect_chinese_content_via_vlm(pdf_path)
        if is_chinese:
            return True, f"chinese_pdf_vlm:{detection_result}"

    return False, ""


def is_normalized_name(stem: str) -> bool:
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


def ensure_csv_header(path: Path):
    header = ["time", "status", "pdf", "reason", "pages", "size_bytes", "duration_sec"]
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)


def log_row(status: str, pdf: Path, reason: str = "", pages=None, size=None, duration=None):
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            time.strftime("%Y/%m/%d %H:%M"),
            status,
            str(pdf),
            reason,
            pages if pages is not None else "",
            size if size is not None else "",
            f"{duration:.2f}" if duration is not None else "",
        ])


def get_page_count(pdf_path: Path) -> Optional[int]:
    try:
        import fitz  # PyMuPDF
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


# =================================

# ======== 失败日志（跨运行） ========
FAIL_LOG_PATH = PDF2ZH_EXE.parent / "fail_log.txt"


def read_failure_counts(path: Path) -> dict[str, int]:
    counts = {}
    if not path.exists():
        return counts
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().rsplit(",", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    pdf_path_str, count_str = parts
                    counts[pdf_path_str] = int(count_str)
    except Exception:
        pass
    return counts


def increment_and_write_failure(pdf_path: Path, counts: dict[str, int], log_file: Path):
    key = str(pdf_path)
    counts[key] = counts.get(key, 0) + 1
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            for p, c in sorted(counts.items()):
                f.write(f"{p},{c}\n")
    except Exception as e:
        print(f"  警告：无法写入失败日志 {log_file}: {e}", flush=True)


# =================================

# ======== 服务配置 ========
def _apply_service_flags(cmd: List[str]) -> List[str]:
    """
    根据配置的服务类型为pdf2zh添加对应的CLI参数
    
    参数：
        cmd: 基础命令列表
        
    返回：
        添加服务参数后的命令列表
        
    服务类型：
        - siliconflow_free: 使用免费服务
        - siliconflow_pro: 使用付费服务
        - auto: 自动选择服务
    """
    svc = (TRANSLATION_SERVICE or "").lower().strip()
    if svc == "siliconflow_free":
        cmd.append("--siliconflowfree")
    elif svc == "siliconflow_pro":
        cmd.extend(["--siliconflow", "--siliconflow-model", str(SILICONFLOW_MODEL)])
        if SILICONFLOW_API_KEY:
            cmd.extend(["--siliconflow-api-key", str(SILICONFLOW_API_KEY)])
        if SILICONFLOW_BASE:
            cmd.extend(["--siliconflow-base", str(SILICONFLOW_BASE)])
    return cmd


def _build_cmd_base(input_pdf: Path, output_dir: Path, watermark_mode: str, enable_ocr: bool = False) -> List[str]:
    # 仅产出 mono（不生成官方 dual），明确英->中，去水印，限速 QPS，关闭术语抽取
    cmd = [
        str(PDF2ZH_EXE),
        "--no-dual",
        "--lang-in", LANG_IN,
        "--lang-out", LANG_OUT,
        "--watermark-output-mode", watermark_mode,  # NoWaterMark / no_watermark
        "--qps", str(QPS_LIMIT),
        "--no-auto-extract-glossary",
        "--output", str(output_dir),
        str(input_pdf)
    ]
    if enable_ocr:
        cmd.append("--ocr-workaround")
    # 注入“硅基流动”相关参数（按开关）
    cmd = _apply_service_flags(cmd)
    return cmd


def execute_pdf2zh_translation(input_pdf: Path, output_dir: Path, enable_ocr: bool = False) -> Tuple[bool, str]:
    """
    执行PDF翻译任务，静默模式运行不显示日志输出
    成功返回 (True, 'OK')；失败返回 (False, 'exit=<code>' 或异常说明)。
    同时兼容水印参数大小写差异。支持 enable_ocr=True 时附加 --ocr-workaround。
    """
    pdf_to_process = input_pdf
    temp_input = None
    if input_pdf.name.encode("ascii", "ignore").decode("ascii") != input_pdf.name:
        temp_input = output_dir / f"__temp_input_{int(time.time())}.pdf"
        try:
            shutil.copy2(input_pdf, temp_input)
            pdf_to_process = temp_input
        except Exception as e:
            return False, f"TempCopyFail: {e}"

    attempts = []
    for wm in ["NoWaterMark", "no_watermark"]:
        attempts.append(_build_cmd_base(pdf_to_process, output_dir, wm, enable_ocr=enable_ocr))

    ok = False
    last_reason = ""
    for cmd in attempts:
        try:
            proc = subprocess.run(
                cmd, cwd=str(output_dir),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=MAX_TIME
            )
            if proc.returncode == 0:
                ok, last_reason = True, "OK"
                break
            last_reason = f"exit={proc.returncode}"
        except subprocess.TimeoutExpired as e:
            last_reason = f"TIMEOUT: {e}";
            break
        except FileNotFoundError:
            last_reason = "pdf2zh(.exe) not found";
            break
        except Exception as e:
            last_reason = f"EXCEPTION: {e}"

    if temp_input:
        if ok:
            temp_output = find_most_recent_matching_file(str(output_dir / f"{temp_input.stem}*mono.pdf"))
            if temp_output and temp_output.exists():
                final_output = expected_mono_path(input_pdf)
                try:
                    temp_output.rename(final_output)
                except Exception as e:
                    ok, last_reason = False, f"TempRenameFail: {e}"
            else:
                ok, last_reason = False, "TempOutputNotFound"
        temp_input.unlink(missing_ok=True)

    return ok, last_reason


# =========================================================

# ============== CSV 清理：删除本次新生成的 csv ==============
def cleanup_new_csvs(folder: Path, t_start: float):
    removed = 0
    for p in folder.glob("*.csv"):
        try:
            if p.stat().st_mtime >= t_start - 1:
                p.unlink(missing_ok=True)
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"  已清理 exe 生成的 CSV：{removed} 个", flush=True)


# =========================================================

# ================= 横向拼接并覆盖原名 =================
import fitz  # PyMuPDF


def _set_all_page_boxes(page: fitz.Page, rect: fitz.Rect):
    for setter in ("set_mediabox", "set_cropbox", "set_trimbox", "set_bleedbox"):
        if hasattr(page, setter):
            try:
                getattr(page, setter)(rect)
            except Exception:
                pass


def extract_page_dimensions(pdf_path: Path) -> List[Dict[str, float]]:
    """提取PDF每页的尺寸信息（单位：pt）"""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            sizes = []
            for page in doc:
                rect = page.rect
                sizes.append({"w": round(rect.width, 2), "h": round(rect.height, 2)})
            return sizes
    except Exception as e:
        print(f"  警告：获取PDF页面尺寸失败：{e}", flush=True)
        return []


def create_translation_metadata(status: str, source_sizes: List[Dict[str, float]],
                                result_sizes: List[Dict[str, float]] = None,
                                gap_pt: float = 0.0) -> Dict[str, Any]:
    """创建翻译元数据JSON"""
    metadata = {
        "pdf2zh.status": status,
        "pdf2zh.run_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

    if status == "translated":
        # 确定使用的模型
        if TRANSLATION_SERVICE == "siliconflow_free":
            metadata["pdf2zh.model"] = "Qwen/Qwen2.5-7B-Instruct"
        elif TRANSLATION_SERVICE == "siliconflow_pro":
            metadata["pdf2zh.model"] = SILICONFLOW_MODEL

        metadata["pdf2zh.source_page_sizes_pt"] = source_sizes
        metadata["pdf2zh.gap_pt"] = gap_pt
        if result_sizes:
            metadata["pdf2zh.result_page_sizes_pt"] = result_sizes

    return metadata


def embed_minimal_metadata(pdf_path: Path):
    """为原始PDF嵌入最小元数据（仅包含运行时间和状态）"""
    try:
        import fitz

        # 创建最小元数据（仅状态和时间）
        metadata = create_translation_metadata("untranslated", [])  # source_sizes为空数组

        with fitz.open(pdf_path) as doc:
            # 添加元数据JSON附件
            meta_name = "pdf2zh.meta.json"
            meta_content = json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8')
            doc.embfile_add(meta_name, meta_content, desc="PDF2ZH metadata")

            # 设置AF关系（Associated Files）
            try:
                doc.set_metadata({"af": [meta_name]})
            except Exception:
                pass

            # 保存修改
            doc.saveIncr()

        return True, ""

    except Exception as e:
        return False, str(e)


def embed_original_file_attachment(pdf_path: Path, original_pdf: Path, metadata: Dict[str, Any]):
    """为PDF嵌入原始文件附件和可点击标签"""
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            # 1. 添加元数据JSON附件
            meta_name = "pdf2zh.meta.json"
            meta_content = json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8')
            doc.embfile_add(meta_name, meta_content, desc="PDF2ZH metadata")

            # 2. 在第1页添加可点击标签
            if doc.page_count > 0:
                page = doc[0]

                # 标签位置和尺寸（左上角，留边距）
                margin = 8  # pt
                tag_width = 140  # pt
                tag_height = 26  # pt

                tag_rect = fitz.Rect(margin, margin, margin + tag_width, margin + tag_height)

                # 读取原始PDF内容用于标签
                original_name = original_pdf.name
                with open(original_pdf, 'rb') as f:
                    original_content = f.read()

                # 创建文件附件注释（图钉样式）
                annot = page.add_file_annot(
                    tag_rect.tl,  # 位置点
                    original_content,  # 文件内容
                    original_name,  # 文件名
                    desc=f"点击打开原始PDF：{original_name}",
                    icon="PushPin"  # 图钉图标
                )

                # 设置注释属性
                annot.set_info(title="原始PDF", content=f"打开原稿（{original_name}）")
                annot.update()

            # 3. 设置AF关系（Associated Files）
            # 只为元数据附件设置关联文件关系
            af_list = [meta_name]
            try:
                doc.set_metadata({"af": af_list})
            except Exception:
                pass

            # 保存修改
            doc.saveIncr()

        return True, ""

    except Exception as e:
        return False, str(e)


def _atomic_replace_with_retry(src: Path, dst: Path, max_retries=10, initial_delay=0.1):
    """带重试的原子替换，处理Windows文件锁定问题"""
    for attempt in range(max_retries):
        try:
            os.replace(str(src), str(dst))
            return True
        except PermissionError:
            if attempt == max_retries - 1:
                return False
            delay = initial_delay * (2 ** attempt)  # 指数退避
            time.sleep(delay)
    return False


def _retry_unlink(path: Path, max_retries=5, initial_delay=0.05):
    """带重试的文件删除"""
    for attempt in range(max_retries):
        try:
            path.unlink()
            return True
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                return False
            delay = initial_delay * (2 ** attempt)
            time.sleep(delay)
    return False


def merge_pdfs_preserve_annotations(pdf_left: Path, pdf_right: Path, output_path: Path,
                                        gap: float = 0.0):
    left_doc = fitz.open(pdf_left)
    right_doc = fitz.open(pdf_right)
    out = fitz.open()
    try:
        if len(left_doc) != len(right_doc):
            raise ValueError(f"两个 PDF 页数不同：左 {len(left_doc)} 页，右 {len(right_doc)} 页。")

        # 复制左侧整册（保留批注 / 链接）
        out.insert_pdf(left_doc)

        total = len(left_doc)
        for i in range(total):
            page = out[i]
            lw, lh = page.rect.width, page.rect.height
            new_w = 2 * lw + gap
            new_rect = fitz.Rect(0, 0, new_w, lh)
            _set_all_page_boxes(page, new_rect)

            right_target = fitz.Rect(lw + gap, 0, 2 * lw + gap, lh)
            page.show_pdf_page(right_target, right_doc, i)

        # 鲁棒的临时文件处理
        temp_uuid = uuid.uuid4().hex[:8]
        tmp_path = overwrite_path.parent / f"{overwrite_path.stem}_tmp_{temp_uuid}.pdf"
        out.save(str(tmp_path), garbage=4, deflate=True)
    finally:
        # 确保所有文档句柄关闭
        try:
            out.close()
        except Exception:
            pass
        try:
            left_doc.close()
        except Exception:
            pass
        try:
            right_doc.close()
        except Exception:
            pass

    # 原子替换（带重试）
    if not _atomic_replace_with_retry(tmp_path, overwrite_path):
        # 替换失败，退避到旁路文件
        sidecar_path = overwrite_path.parent / f"{overwrite_path.stem}.pdf2zh-merged.pdf"
        print(f"  警告：目标文件被占用，已保存到旁路文件：{sidecar_path.name}", flush=True)
        _atomic_replace_with_retry(tmp_path, sidecar_path)

    # 清理临时文件（带重试）
    if tmp_path.exists():
        _retry_unlink(tmp_path)


# =========================================================

def get_expected_mono_output_path(src_pdf: Path) -> Path:
    # Paper.pdf -> Paper.no_watermark.zh-CN.mono.pdf
    return src_pdf.parent / f"{src_pdf.stem}.no_watermark.{LANG_OUT}.mono.pdf"


def find_most_recent_matching_file(glob_pattern: str) -> Optional[Path]:
    candidates = sorted(Path(glob_pattern).parent.glob(Path(glob_pattern).name),
                       key=lambda p: p.stat().st_mtime if p.exists() else 0,
                       reverse=True)
    return candidates[0] if candidates else None


def main():
    if not PDF2ZH_EXE.exists():
        raise FileNotFoundError(f"找不到可执行文件：{PDF2ZH_EXE}")

    failure_counts = read_failure_counts(FAIL_LOG_PATH)
    skip_keywords = load_exclusion_keywords()  # 加载排除关键词

    if skip_keywords:
        print(f"已加载 {len(skip_keywords)} 个排除关键词：{', '.join(skip_keywords)}", flush=True)

    pdf_files = []
    for root, _, files in os.walk(PDF_ROOT):
        for name in files:
            if name.lower().endswith(".pdf"):
                pdf_files.append(Path(root) / name)

    ensure_csv_header(LOG_PATH)
    done = skipped = failed = 0
    total_files = len(pdf_files)
    print(f"发现 PDF 共 {total_files} 个，开始处理……", flush=True)

    for idx, pdf_path in enumerate(pdf_files, start=1):
        stem = pdf_path.stem
        size = pdf_path.stat().st_size

        # 使用新的统一排除检查函数
        should_exclude, exclude_reason = should_exclude_from_processing(pdf_path, skip_keywords, failure_counts)
        if should_exclude:
            skipped += 1
            # 获取页数信息用于日志记录
            pages = get_page_count(pdf_path) if exclude_reason.startswith("pages_gt_") else None
            log_row("skipped", pdf_path, reason=exclude_reason, size=size, pages=pages)

            if not SUPPRESS_SKIPPED_OUTPUT:
                print(f"\n[{idx}/{total_files}] 处理：{pdf_path.name}", flush=True)
                if exclude_reason == "too_many_failures":
                    print(f"  排除：该文件已累计失败 {failure_counts.get(str(pdf_path), 0)} 次，不再尝试。", flush=True)
                elif exclude_reason == "is_backup_original":
                    print("  排除：备份文件 *_original.pdf", flush=True)
                elif exclude_reason == "is_generated_output":
                    print("  排除：已生成的 mono/dual 文件", flush=True)
                elif exclude_reason.startswith("already_translated_by_metadata:"):
                    print("  排除：元数据显示已翻译", flush=True)
                elif exclude_reason == "contains_exclusion_keywords":
                    print("  排除：文件名包含排除关键词", flush=True)
                elif exclude_reason == "backup_exists":
                    print("  排除：已存在 *_original 备份", flush=True)
                elif exclude_reason == "filename_contains_chinese":
                    print("  排除：文件名包含中文", flush=True)
                elif exclude_reason == "bad_name_pattern":
                    print("  排除：文件名不符合 Author-YYYY-Title 规范", flush=True)
                elif exclude_reason == "page_count_failed":
                    print("  排除：无法读取页数", flush=True)
                elif exclude_reason.startswith("pages_gt_"):
                    print(f"  排除：页数 {pages} 超过 {MAX_PAGES}", flush=True)
                elif exclude_reason.startswith("size_gt_"):
                    print("  排除：大小超过阈值", flush=True)
                elif exclude_reason.startswith("chinese_pdf_vlm:"):
                    print("  排除：大模型检测为中文PDF", flush=True)
            continue

        # 只有在确定不跳过时才显示处理信息
        print(f"\n[{idx}/{total_files}] 处理：{pdf_path.name}", flush=True)

        backup_path = pdf_path.with_name(f"{stem}_original.pdf")
        mono_path = get_expected_mono_output_path(pdf_path)
        final_path = pdf_path  # 覆盖回原名
        pages = get_page_count(pdf_path)  # 重新获取页数信息

        # —— 调用 pdf2zh：仅产中文 mono；不提取 exe 日志 ——
        used_ocr = False
        t0 = time.time()
        ok, reason = execute_pdf2zh_translation(pdf_path, pdf_path.parent, enable_ocr=False)
        duration = time.time() - t0
        if not ok:
            # 首次失败：尝试启用 OCR 回退
            print(f"  首次翻译失败（{reason}），尝试启用 OCR 回退……", flush=True)
            cleanup_new_csvs(pdf_path.parent, t0)
            t1 = time.time()
            ok, reason = execute_pdf2zh_translation(pdf_path, pdf_path.parent, enable_ocr=True)
            duration = time.time() - t1
            if not ok:
                increment_and_write_failure(pdf_path, failure_counts, FAIL_LOG_PATH)
                failed += 1
                log_row("failed", pdf_path, reason=f"pdf2zh_failed:{reason}", pages=pages, size=size, duration=duration)
                print(f"  失败：OCR 回退仍失败（{reason}）", flush=True)
                cleanup_new_csvs(pdf_path.parent, t1)
                continue
            used_ocr = True
            cleanup_new_csvs(pdf_path.parent, t1)

        # —— 找到 mono 输出 ——
        if not mono_path.exists():
            fallback = find_most_recent_matching_file(str(pdf_path.parent / f"{stem}*mono.pdf"))
            if fallback:
                mono_path = fallback
            else:
                # 未发现 mono，若尚未启用 OCR，则再尝试一次 OCR 回退
                if not used_ocr:
                    print("  未找到 mono 输出，尝试启用 OCR 回退再生成……", flush=True)
                    t2 = time.time()
                    ok2, reason2 = execute_pdf2zh_translation(pdf_path, pdf_path.parent, enable_ocr=True)
                    cleanup_new_csvs(pdf_path.parent, t2)
                    if not ok2:
                        increment_and_write_failure(pdf_path, failure_counts, FAIL_LOG_PATH)
                        failed += 1
                        log_row("failed", pdf_path, reason=f"mono_pdf_not_found_and_ocr_failed:{reason2}", pages=pages,
                                size=size)
                        print("  失败：OCR 回退仍未生成 mono", flush=True)
                        continue
                    # 再次定位 mono
                    if not mono_path.exists():
                        fb2 = find_most_recent_matching_file(str(pdf_path.parent / f"{stem}*mono.pdf"))
                        if fb2:
                            mono_path = fb2
                        else:
                            increment_and_write_failure(pdf_path, failure_counts, FAIL_LOG_PATH)
                            failed += 1
                            log_row("failed", pdf_path, reason="mono_pdf_not_found_after_ocr", pages=pages, size=size)
                            print("  失败：启用 OCR 后仍未找到 mono", flush=True)
                            continue
                    used_ocr = True
                else:
                    increment_and_write_failure(pdf_path, failure_counts, FAIL_LOG_PATH)
                    failed += 1
                    log_row("failed", pdf_path, reason="mono_pdf_not_found", pages=pages, size=size)
                    print("  失败：未找到 mono 输出", flush=True)
                    continue

        # —— 备份原 PDF ——
        try:
            shutil.copy2(pdf_path, backup_path)

            # 为原始PDF备份添加最小元数据
            original_meta_ok, original_meta_error = embed_minimal_metadata(backup_path)
            if not original_meta_ok:
                print(f"  警告：为原始PDF添加元数据失败：{original_meta_error}", flush=True)
                # 记录元数据失败到日志
                log_row("metadata_failed", pdf_path, reason=f"original_metadata_error:{original_meta_error}",
                        pages=pages, size=size, duration=duration)

        except Exception as e:
            increment_and_write_failure(pdf_path, failure_counts, FAIL_LOG_PATH)
            failed += 1
            log_row("failed", pdf_path, reason=f"backup_failed:{e}", pages=pages, size=size, duration=duration)
            print("  失败：备份原文件出错", flush=True)
            cleanup_new_csvs(pdf_path.parent, t0)
            continue

        # —— 合并并覆盖原名 ——
        try:
            # 获取原始PDF页面尺寸
            source_sizes = extract_page_dimensions(pdf_path)
            if not source_sizes:
                print(f"  警告：无法获取原始PDF页面尺寸", flush=True)
                source_sizes = []

            merge_pdfs_preserve_annotations(pdf_path, mono_path, final_path, gap=GAP)

            # 获取合并后PDF页面尺寸
            result_sizes = extract_page_dimensions(final_path)
            if not result_sizes:
                print(f"  警告：无法获取合并后PDF页面尺寸", flush=True)
                result_sizes = []

            # 创建元数据
            metadata = create_translation_metadata("translated", source_sizes, result_sizes, GAP)

            # 添加附件和点击标签
            attach_ok, attach_error = embed_original_file_attachment(final_path, backup_path, metadata)
            if not attach_ok:
                print(f"  警告：添加附件失败：{attach_error}", flush=True)
                # 记录附件失败到日志
                log_row("attachment_failed", pdf_path, reason=f"attachment_error:{attach_error}", pages=pages,
                        size=size, duration=duration)

        except Exception as e:
            increment_and_write_failure(pdf_path, failure_counts, FAIL_LOG_PATH)
            failed += 1
            log_row("failed", pdf_path, reason=f"merge_failed:{e}", pages=pages, size=size, duration=duration)
            print("  失败：拼接/覆盖出错", flush=True)
            cleanup_new_csvs(pdf_path.parent, t0)
            continue

        # —— 清理 mono ——（成功后）
        if DELETE_MONO_PDF or DELETE_ALL_EXCEPT_FINAL:
            try:
                mono_path.unlink()
                print(f"  已删除中间文件：{mono_path.name}", flush=True)
            except Exception as e:
                print(f"  警告：删除 mono 失败：{e}", flush=True)

        # —— 清理 original 备份 ——（成功后）
        if DELETE_ALL_EXCEPT_FINAL:
            try:
                backup_path.unlink()
                print(f"  已删除备份文件：{backup_path.name}", flush=True)
            except Exception as e:
                print(f"  警告：删除 original 备份失败：{e}", flush=True)

        # —— 清理 exe 生成的 CSV ——（成功后）
        cleanup_new_csvs(pdf_path.parent, t0)

        done += 1
        if used_ocr:
            log_row("dual_made_overwrite_ocr", pdf_path, reason="ok_ocr", pages=pages, size=size, duration=duration)
            print(f"  完成（OCR 回退）：已覆盖保存为 {final_path.name}（备份：{backup_path.name}；用时 {duration:.1f}s）",
                  flush=True)
        else:
            log_row("dual_made_overwrite", pdf_path, reason="ok", pages=pages, size=size, duration=duration)
            print(f"  完成：已覆盖保存为 {final_path.name}（备份：{backup_path.name}；用时 {duration:.1f}s）", flush=True)

    print(f"\n处理完成：生成 {done} 个，跳过 {skipped} 个，失败 {failed} 个。日志：{LOG_PATH}", flush=True)


if __name__ == "__main__":
    main()