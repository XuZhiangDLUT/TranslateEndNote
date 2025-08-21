#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF批处理工具 - 清理旁路文件

功能：
- 扫描指定目录下的旁路文件
- 删除 .pdf2zh-updated.pdf 和 .pdf2zh-merged.pdf 文件
- 删除 pdf_batch_translator.py 生成的临时输入文件 (__temp_input_*.pdf)
- 统计删除的文件数量和释放的存储空间
"""

import os
from pathlib import Path

def cleanup_sidecar_files(root_path=None):
    """
    清理PDF翻译过程中产生的旁路文件
    
    参数：
        root_path: 要扫描的根目录路径，默认为EndNote PDF库目录
        
    返回：
        删除的文件数量
    """
    if root_path is None:
        root_path = r"D:\User_Files\My EndNote Library.Data\PDF"
    
    root_path = Path(root_path)
    count = 0
    size_freed = 0
    
    print(f"正在扫描 {root_path}...")
    
    # 定义要删除的文件模式
    patterns = [
        "*.pdf2zh-updated.pdf", 
        "*.pdf2zh-merged.pdf",
        "__temp_input_*.pdf"
    ]
    
    for pattern in patterns:
        for file_path in root_path.rglob(pattern):
            try:
                file_size = file_path.stat().st_size
                size_freed += file_size
                file_path.unlink()
                print(f"已删除: {file_path.relative_to(root_path)} ({file_size} bytes)")
                count += 1
            except Exception as e:
                print(f"删除失败 {file_path.relative_to(root_path)}: {e}")
    
    print(f"\n清理完成：删除 {count} 个文件，释放 {size_freed:,} 字节")
    return count

if __name__ == "__main__":
    import sys
    root_path = sys.argv[1] if len(sys.argv) > 1 else None
    cleanup_sidecar_files(root_path)