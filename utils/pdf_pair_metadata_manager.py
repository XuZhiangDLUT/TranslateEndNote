# -*- coding: utf-8 -*-
"""
PDF元数据补全工具

功能：
- 为已翻译的PDF文件添加元数据附件
- 嵌入原始PDF文件作为附件
- 在PDF首页添加可点击的原始文件链接
- 支持批量处理和干运行模式

参数：
    --root PATH: 指定处理的根目录
    --model NAME: 指定翻译模型名称
    --margin N: 设置标签边距
    --tagw N: 设置标签宽度
    --tagh N: 设置标签高度
    --dry-run: 预览模式，不实际修改文件

文件命名约定：
- 翻译后的PDF: X.pdf
- 原始PDF: X_original.pdf
- 默认模型: Qwen/Qwen2.5-7B-Instruct
"""

import os, sys, json, argparse, statistics, tempfile, shutil, time, uuid
from pathlib import Path
from datetime import datetime, timezone

import fitz  # PyMuPDF

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def page_sizes_pt(pdf_path: Path):
    sizes = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            r = page.rect
            sizes.append({"w": round(r.width, 2), "h": round(r.height, 2)})
    return sizes

def infer_gap_pt(source_sizes, result_sizes):
    """
    根据合并规则计算页面间距
    
    参数：
        source_sizes: 原始PDF页面尺寸列表
        result_sizes: 合并后PDF页面尺寸列表
        
    返回：
        计算得到的页面间距（中位数）
    """
    gaps = []
    n = min(len(source_sizes), len(result_sizes))
    for i in range(n):
        lw = source_sizes[i]["w"]
        rw = lw  # 合并时右侧宽与左侧相同（你的合并逻辑）
        nw = result_sizes[i]["w"]
        cand = round(nw - (lw + rw), 2)
        # 允许少量浮点误差
        if cand >= -0.5:  # 容忍极小负差
            gaps.append(max(0.0, round(cand, 2)))
    if not gaps:
        return 0.0
    try:
        return float(round(statistics.median(gaps), 2))
    except statistics.StatisticsError:
        return float(round(sum(gaps) / len(gaps), 2))

def ensure_meta_on_original(original_pdf: Path, dry=False):
    """
    为原始PDF文件添加最小元数据
    
    参数：
        original_pdf: 原始PDF文件路径
        dry: 干运行模式，不实际修改文件
    """
    if dry:
        return
    with fitz.open(original_pdf) as doc:
        # 若已有同名嵌入则跳过
        if _has_embfile(doc, "pdf2zh.meta.json"):
            return
        meta = {
            "pdf2zh": {
                "status": "untranslated",
                "run_time_utc": iso_utc_now()
            }
        }
        payload = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
        # 文档级嵌入（微型 JSON）
        doc.embfile_add("pdf2zh.meta.json", payload, desc="PDF2ZH metadata")
        # （尽力而为）声明 AF 关系
        try:
            doc.set_metadata({"af": ["pdf2zh.meta.json"]})
        except Exception:
            pass
        _safe_save_in_place(doc, original_pdf)

def _has_embfile(doc: fitz.Document, name: str) -> bool:
    """
    检查PDF是否包含指定名称的嵌入文件
    
    参数：
        doc: PDF文档对象
        name: 要查找的文件名
        
    返回：
        是否包含该嵌入文件
    """
    try:
        n = doc.embfile_count()
        for i in range(n):
            info = doc.embfile_info(i)
            nm = info.get("name") or info.get("ufilename") or info.get("filename")
            if nm == name:
                return True
    except Exception:
        pass
    return False

def _has_file_annot_for_original(page: fitz.Page, original_name: str) -> bool:
    """
    检查页面是否已包含指向原始文件的附件注释
    
    参数：
        page: PDF页面对象
        original_name: 原始文件名
        
    返回：
        是否已存在相关附件注释
    """
    try:
        ann = page.first_annot
        while ann:
            t = (ann.type[1] or "").lower()
            if "file" in t:  # 'FileAttachment'
                info = ann.info or {}
                # 标题或内容里提到 original 名称，就视为已有
                if original_name in (info.get("title","") + info.get("content","")):
                    return True
            ann = ann.next
    except Exception:
        pass
    return False

def _read_original_file(original_path: Path):
    """
    读取原始PDF文件内容
    
    参数：
        original_path: 原始文件路径
        
    返回：
        文件二进制内容
    """
    with open(original_path, "rb") as f:
        data = f.read()
    return data

def _add_clickable_tag(page: fitz.Page, original_bytes: bytes, original_name: str,
                       margin=8, tagw=140, tagh=26):
    """
    在PDF页面左上角添加可点击的原始文件链接
    
    参数：
        page: PDF页面对象
        original_bytes: 原始文件内容
        original_name: 原始文件名
        margin: 边距
        tagw: 标签宽度
        tagh: 标签高度
    """
    # 设置图钉位置
    pin_point = fitz.Point(margin + 8, margin + 8)
    annot = page.add_file_annot(
        pin_point,
        original_bytes,
        original_name,
        desc=f"点击打开原始PDF：{original_name}",
        icon="PushPin"
    )
    try:
        annot.set_info(title="原始PDF", content=f"打开原稿（{original_name}）")
        annot.update()
    except Exception:
        pass

  # 添加文字说明标签
    label_rect = fitz.Rect(margin, margin, margin + tagw, margin + tagh)
    text = f"打开原始PDF（{original_name}）"
    try:
        page.insert_textbox(label_rect, text, fontsize=9, fontname="helv", align=0)
    except Exception:
        # 字体名不一定可用，退回默认
        try:
            page.insert_textbox(label_rect, text, fontsize=9, align=0)
        except Exception:
            pass

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

def _cleanup_temp_files(directory: Path):
    """清理遗留的临时文件"""
    try:
        for temp_file in directory.glob("*_tmp_*.pdf"):
            _retry_unlink(temp_file)
    except Exception:
        pass

def _safe_save_in_place(doc: fitz.Document, path: Path):
    """鲁棒的保存：完整保存到临时文件，原子替换，失败时退避到旁路文件"""
    # 优先增量保存
    try:
        doc.saveIncr()
        return
    except Exception:
        pass
    
    # 回退：完整保存到临时文件
    temp_uuid = uuid.uuid4().hex[:8]
    tmp_path = path.parent / f"{path.stem}_tmp_{temp_uuid}.pdf"
    
    try:
        # 完整保存到临时文件
        doc.save(str(tmp_path), garbage=4, deflate=True)
        doc.close()  # 确保所有句柄关闭
        
        # 原子替换（带重试）
        if _atomic_replace_with_retry(tmp_path, path):
            return
        
        # 替换失败，退避到旁路文件
        sidecar_path = path.parent / f"{path.stem}.pdf2zh-updated.pdf"
        print(f"   警告：目标文件被占用，已保存到旁路文件：{sidecar_path.name}")
        _atomic_replace_with_retry(tmp_path, sidecar_path)
        
    finally:
        # 清理临时文件（带重试）
        if tmp_path.exists():
            _retry_unlink(tmp_path)

def build_translated_meta(source_sizes, result_sizes, model_name, gap_pt):
    return {
        "pdf2zh": {
            "status": "translated",
            "run_time_utc": iso_utc_now(),
            "model": model_name,
            "gap_pt": float(gap_pt),
            "source_page_sizes_pt": source_sizes,
            "result_page_sizes_pt": result_sizes
        }
    }

def process_pair(final_pdf: Path, original_pdf: Path, model_name: str, margin: int, tagw: int, tagh: int, dry=False):
    print(f"→ 处理：{final_pdf.name}")
    # 1) 给独立的 *_original.pdf 写最小 JSON
    ensure_meta_on_original(original_pdf, dry=dry)

    # 2) 采集尺寸+gap
    source_sizes = page_sizes_pt(original_pdf)
    result_sizes = page_sizes_pt(final_pdf)
    gap_pt = infer_gap_pt(source_sizes, result_sizes)

    # 3) 构建 translated 的 JSON
    meta = build_translated_meta(source_sizes, result_sizes, model_name, gap_pt)
    payload = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")

    if dry:
        print(f"   （dry-run）gap_pt≈{gap_pt}, src_pages={len(source_sizes)}, out_pages={len(result_sizes)}")
        return

    # 4) 打开成品，嵌入 JSON，放置点击标签
    with fitz.open(final_pdf) as doc:
        # 4.1 JSON 附件（若不存在才写）
        if not _has_embfile(doc, "pdf2zh.meta.json"):
            doc.embfile_add("pdf2zh.meta.json", payload, desc="PDF2ZH metadata")

        # 4.2 在第 1 页放点击标签（若未放过）
        if doc.page_count > 0:
            page0 = doc[0]
            if not _has_file_annot_for_original(page0, original_pdf.name):
                # 读取原稿内容用于标签
                original_bytes = _read_original_file(original_pdf)
                _add_clickable_tag(page0, original_bytes, original_pdf.name,
                                   margin=margin, tagw=tagw, tagh=tagh)

        _safe_save_in_place(doc, final_pdf)

    print(f"   完成：写入 meta.json、添加标签；gap_pt≈{gap_pt}")

def scan_and_run(root: Path, model_name: str, margin: int, tagw: int, tagh: int, dry=False):
    # 启动时清理遗留的临时文件
    _cleanup_temp_files(root)
    
    pairs = []
    for p in root.rglob("*.pdf"):
        if p.name.lower().endswith("_original.pdf"):
            continue
        # 成品对应的原稿
        orig = p.with_name(f"{p.stem}_original.pdf")
        if orig.exists():
            pairs.append((p, orig))

    if not pairs:
        print("未找到任何（成品PDF + *_original.pdf）配对。")
        return

    print(f"发现 {len(pairs)} 个配对，开始处理……")
    for final_pdf, original_pdf in pairs:
        try:
            process_pair(final_pdf, original_pdf, model_name, margin, tagw, tagh, dry=dry)
        except Exception as e:
            print(f"   警告：处理 {final_pdf.name} 失败：{e}")

def main():
    """
    主函数：执行PDF元数据补全处理
    
    使用当前配置的参数处理指定目录下的PDF文件
    """
    # 配置处理参数
    root_path = r"D:\User_Files\My EndNote Library.Data\PDF"
    model_name = DEFAULT_MODEL
    margin = 8
    tagw = 140
    tagh = 26
    dry_run = False

    root = Path(root_path).resolve()
    if not root.exists():
        print(f"路径不存在：{root}")
        sys.exit(1)

    scan_and_run(root, model_name, margin, tagw, tagh, dry=dry_run)

if __name__ == "__main__":
    main()
