# TranslateEndNote

> 🚀 批量 **PDF→中英双语** 翻译与合成工具  
> 以 [`PDFMathTranslate-next` 的 `pdf2zh` CLI](https://github.com/PDFMathTranslate/PDFMathTranslate-next) 为翻译引擎，
> 在 **不破坏原版注释/链接** 的前提下，把**原文（左）+ 译文（右）**并排合成，覆盖输出为原文件名，并写入可溯源的元数据与附件。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PDF](https://img.shields.io/badge/Format-PDF-red.svg)](https://www.adobe.com/pdf/)

---

## ✨ 功能概览

### 🎯 核心功能
- **批量处理**：递归扫描目标目录，自动识别并处理 PDF 文件
- **双语合成**：调用 `pdf2zh` 生成中文 mono 版本，与原稿左右合并为双语版本
- **智能备份**：自动备份原稿（`*_original.pdf`），最终覆盖保存为原文件名
- **批注保留**：保留左侧原稿的批注与链接，第 1 页自动加入"打开原始 PDF"可点击标签
- **溯源嵌入**：在最终 PDF 内嵌入运行元数据和原始 PDF 附件

### 🔧 高级特性
- **智能跳过**：多级跳过规则，避免重复处理和无效文件
- **容错机制**：失败重试与熔断（同一文件失败 ≥3 次将跳过）
- **OCR 回退**：首次失败时自动加 `--ocr-workaround` 再试
- **资源管理**：可选清理中间文件，完整的 CSV 批处理日志
- **性能优化**：支持 QPS 限速、文件大小和页数限制

---

## 📦 目录结构

```
TranslateEndNote/
├── .gitignore                   # Git 忽略文件
├── README.md                    # 项目说明文档
├── configs/
│   └── config.json              # 📋 主配置文件（目录、限额、服务开关、VLM 判定等）
├── dependencies/
│   └── requirements.txt         # 📦 Python 依赖清单
├── src/
│   ├── translateEndNote.py      # ⭐ 主程序入口（批处理、合成、元数据与附件）
│   └── determinePdfChinese.py   # 🔍 VLM 中文检测模块
└── utils/
    ├── backfill_pdf2zh_metadata.py  # 🔄 元数据补齐工具
    └── cleanup_sidecar_files.py     # 🧹 临时文件清理工具
```

---

## 🚀 快速开始

### 📋 前置要求
- **Python 3.10+**
- **pdf2zh CLI 工具**（外部依赖）
- **硅基流动 API Key**（可选，支持免费通道）

### 🔧 步骤一：安装 `pdf2zh`

本项目依赖 [`PDFMathTranslate-next`](https://github.com/PDFMathTranslate/PDFMathTranslate-next) 提供的 `pdf2zh` CLI。

1. **下载安装**：
   ```bash
   # 访问官方 releases 页面下载对应平台的二进制文件
   # https://github.com/Byaidu/PDFMathTranslate/releases
   ```

2. **验证安装**：
   ```bash
   # 确保 pdf2zh 在 PATH 中，或记录完整路径
   pdf2zh --version
   ```

### 📦 步骤二：安装 Python 依赖

```bash
# 在项目根目录运行
pip install -r dependencies/requirements.txt
```

**主要依赖库**：
- `PyMuPDF` (fitz)：PDF 读取/合并/附件/批注操作
- `Pillow`：图像处理（VLM 取样判定时使用）
- `openai`：OpenAI 兼容接口客户端
- `requests`：HTTP 请求库

### 🔑 步骤三：配置 API 密钥

**推荐使用环境变量**：

```bash
# macOS / Linux
export SILICONFLOW_API_KEY="your_api_key_here"

# Windows PowerShell
setx SILICONFLOW_API_KEY "your_api_key_here"
```

**或在配置文件中设置**：
```json
{
  "siliconflow_api_key": "your_api_key_here"
}
```

> 💡 **免费通道**：本项目也支持 `pdf2zh` 的免费翻译通道

### ⚙️ 步骤四：配置文件设置

编辑 `configs/config.json`，至少设置：

```json
{
  "pdf_root": "/path/to/your/pdfs",
  "pdf2zh_exe": "/path/to/pdf2zh.exe"
}
```

**重要配置项**：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `max_size_bytes` | 100MB | 文件大小限制 |
| `max_pages` | 500 | 页数限制 |
| `qps_limit` | 20 | 请求限速 |
| `translation_service` | `siliconflow_free` | 翻译服务类型 |
| `lang_in` | `en` | 源语言 |
| `lang_out` | `zh-CN` | 目标语言 |

### 🚀 步骤五：运行程序

```bash
# 启动批量翻译
python src/translateEndNote.py
```

**输出信息**：
- 控制台实时显示处理状态
- `batch_translate_log.csv` 记录详细日志
- 支持 `--help` 查看更多选项

---

## 🔧 `translateEndNote.py` 详解（最重要）

### 整体流程

1. **扫描** `pdf_root` 下的所有 `.pdf`。  
2. **跳过判定**（见下文“会被翻译的 PDF 条件”）。  
3. **备份原稿**为 `*_original.pdf`，并向原稿**内嵌最小元数据**（`pdf2zh.meta.json`，标记 `untranslated`）。  
4. **调用 `pdf2zh` 生成中文 mono**：  
   - 仅生成 **mono**，不生成官方 `dual`（由本脚本自定义合成）。  
   - 显式指定 `--lang-in en --lang-out zh-CN`。  
   - 去水印：`--watermark-output-mode NoWaterMark`（也兼容旧拼写 `no_watermark`）。  
   - 限速：`--qps <qps_limit>`；关闭自动术语抽取：`--no-auto-extract-glossary`。  
   - 根据 `translation_service` 自动添加：  
     - `siliconflow_free` → `--siliconflowfree`  
     - `siliconflow_pro` → `--siliconflow --siliconflow-model <model> [--siliconflow-api-key ...] [--siliconflow-base ...]`  
   - **失败回退**：若首次失败，再次以 `--ocr-workaround` 运行。  
   - **非 ASCII 文件名兼容**：先复制到临时 ASCII 名，再把生成的 mono **重命名**回规范文件名。  
   - 期望的 mono 命名：`{原名}.no_watermark.{lang_out}.mono.pdf`。  
5. **左右合并并覆盖**：  
   - **左**为原稿（含批注/链接），**右**为 mono 中文页；支持 `gap` 间距。  
   - 若页数不一致则报错；合并后**覆盖保存**为**原文件名**。  
   - 目标文件被占用时，降级保存为**旁路文件**：`{原名}.pdf2zh-merged.pdf`。  
6. **写入元数据与附件**：  
   - 在最终 PDF 内嵌 `pdf2zh.meta.json`：  
     - `pdf2zh.status`: `"translated"`  
     - `pdf2zh.run_time_utc`、`pdf2zh.model`（`siliconflow_free` 默认记录为 `Qwen/Qwen2.5-7B-Instruct`；`siliconflow_pro` 记录为配置中的 `siliconflow_model`）、  
       `pdf2zh.source_page_sizes_pt`、`pdf2zh.result_page_sizes_pt`、`pdf2zh.gap_pt` 等。  
   - **嵌入原始 PDF** 为附件，并在第 1 页左上角加入“打开原始 PDF（文件名）”**可点击标签**（点击即可打开附件）。  
7. **清理**：删除当次生成的 CSV；按配置删除 mono，或在 `DELETE_ALL_EXCEPT_FINAL` 为真时**连备份也删除**。  
8. **失败计数**：每次失败会写 `fail_log.txt`；同一文件累计失败≥3 次将**永久跳过**。

### 产物与命名约定

- **最终输出**：覆盖原文件名 `.pdf`。  
- **备份原稿**：`*_original.pdf`。  
- **中间文件**：`*.no_watermark.{lang_out}.mono.pdf`（可配置是否删除）。  
- **旁路文件**：`*.pdf2zh-merged.pdf`（当目标被占用时落盘）。  
- **内嵌附件**：  
  - `pdf2zh.meta.json`（运行元数据）  
  - 原始 PDF（可点击打开）  

### `pdf2zh` 调用参数（由脚本拼装）

```
--no-dual
--lang-in <LANG_IN>        # 默认 en
--lang-out <LANG_OUT>      # 默认 zh-CN
--watermark-output-mode NoWaterMark | no_watermark
--qps <QPS_LIMIT>          # 默认 20
--no-auto-extract-glossary
[--ocr-workaround]         # 失败回退时添加
--output <输出目录>
<输入PDF>
# 视 translation_service 自动附加：
--siliconflowfree
# 或
--siliconflow --siliconflow-model <MODEL> [--siliconflow-api-key ...] [--siliconflow-base ...]
```

### 会被“翻译”的 PDF 需要满足哪些条件？

同时开启的“跳过规则”为 **OR** 关系；**命中任一**即跳过。未命中的才会进入翻译流程。常见规则包括：

- **已翻译标记**：PDF 内嵌 `pdf2zh.meta.json` 且 `status=translated` → 跳过。  
- **失败熔断**：同一文件历史失败 ≥3 次 → 跳过。  
- **旁路/备份/产物自过滤**：`*_original.pdf`、`*.mono.pdf`、`*.dual.pdf` 等 → 跳过。  
- **文件名规则**：  
  - `skip_filename_contains_chinese` 为真且**文件名含中文** → 跳过；  
  - `skip_filename_format_check` 为真且文件名 **不符合** `Author-YYYY-Title`（作者-年份-标题，以 `-` 分隔；作者不含数字；年份为 1900–2099 的四位数字） → 跳过。  
- **体积/页数阈值**：  
  - `skip_max_file_size` 且 `size > max_size_bytes`（默认 100MB） → 跳过；  
  - `skip_max_pages` 且 `pages > max_pages`（默认 500） → 跳过；  
- **关键词过滤**：`skip_contains_skip_keywords` 且**文件名包含**任一 `skip_keywords`（大小写不敏感） → 跳过。  
- **VLM 中文判定**：`skip_chinese_pdf_vlm` 为真且**判定为中文 PDF**（抽样页"中文"计数 ≥ "非中文"计数） → 跳过。  
- **无法读取页数** / 其它异常 → 跳过并记录原因。

---

## 🧠 VLM 中文检测模块

### 🔍 `determinePdfChinese.py`

使用视觉语言模型(VLM)智能检测PDF文件的主要语言。

**工作原理**：
- 随机抽取 `k_pages`（默认5页）进行采样
- 按 `vlm_dpi`（默认150）渲染为JPEG图像
- 调用硅基流动的OpenAI兼容接口进行语言判定
- 基于多数投票原则确定整体语言

**支持的VLM模型**：
- `deepseek-ai/deepseek-vl2`
- `THUDM/GLM-4.1V-9B-Thinking`
- `Qwen/Qwen2.5-VL-32B-Instruct`

**配置参数**：
```json
{
  "vlm_model": "deepseek-ai/deepseek-vl2",
  "vlm_k_pages": 5,
  "vlm_dpi": 150,
  "vlm_detail": "low",
  "vlm_per_page_timeout": 600
}
```

---

## 🛠️ 实用工具脚本

### 🔄 `backfill_pdf2zh_metadata.py`

**用途**：为已翻译但缺少元数据的PDF补齐溯源信息

**功能**：
- 内嵌 `pdf2zh.meta.json` 元数据
- 将原始PDF作为附件嵌入
- 在第1页添加可点击的"打开原始PDF"标签

**使用方法**：
```bash
python utils/backfill_pdf2zh_metadata.py --root /path/to/pdfs --model "Qwen/Qwen3-8B"
```

### 🧹 `cleanup_sidecar_files.py`

**用途**：清理临时和旁路文件，释放存储空间

**清理模式**：
- `*.pdf2zh-updated.pdf`
- `*.pdf2zh-merged.pdf`
- 其他临时文件

**使用方法**：
```bash
python utils/cleanup_sidecar_files.py /path/to/pdfs
```

---

## 📊 性能优化

### ⚡ 处理优化
- **QPS限速**：避免API请求过于频繁
- **文件大小限制**：防止处理超大文件
- **页数限制**：控制单次处理复杂度
- **并发控制**：智能调度处理任务

### 💾 存储优化
- **可选清理**：自动删除中间文件
- **智能备份**：保留原始文件便于恢复
- **压缩存储**：优化附件大小

### 🔄 错误处理
- **失败重试**：自动重试失败任务
- **OCR回退**：尝试不同处理策略
- **熔断机制**：避免重复失败
- **详细日志**：完整的处理记录

---

## 🔗 相关项目

### 📚 PDFMathTranslate-next
本项目依赖 [`PDFMathTranslate-next`](https://github.com/PDFMathTranslate/PDFMathTranslate-next) 提供的 `pdf2zh` CLI 工具。

**主要特性**：
- 支持多种翻译后端
- 提供CLI和GUI界面
- 支持Docker部署
- 活跃的社区维护

### 🌐 硅基流动
推荐使用 [硅基流动](https://docs.siliconflow.cn/cn/userguide/quickstart) 作为翻译服务提供商。

**优势**：
- 高质量的翻译模型
- 合理的定价策略
- 稳定的服务保障
- 免费额度支持

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- [PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next) - 核心翻译引擎
- [硅基流动](https://siliconflow.cn/) - 翻译服务支持
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF) - PDF处理库

---

## ❓ 常见问题

### 🚫 安装和配置问题

**Q: `pdf2zh(.exe) not found` 错误？**
A: 请检查 `configs/config.json` 中的 `pdf2zh_exe` 路径是否正确指向可执行文件。

**Q: 如何获取硅基流动 API Key？**
A: 访问 [硅基流动官网](https://siliconflow.cn/) 注册账号，在控制台获取 API Key。

**Q: 支持哪些翻译模型？**
A: 支持硅基流动提供的所有模型，推荐使用：
- `Qwen/Qwen3-8B`
- `Qwen/Qwen2.5-7B-Instruct`
- `deepseek-ai/deepseek-vl2` (VLM)

### 🔧 使用问题

**Q: 翻译后批注和链接丢失了？**
A: 合成时会保留左侧原稿的批注和链接，如果仍有问题请检查原文件。

**Q: 文件名包含中文无法处理？**
A: 启用 `skip_filename_contains_chinese` 选项可跳过中文文件名，或使用英文文件名。

**Q: 处理大文件时失败？**
A: 调整 `max_size_bytes` 和 `max_pages` 参数，或检查系统资源。

### 📊 性能问题

**Q: 处理速度太慢？**
A: 调整 `qps_limit` 参数，或考虑升级到付费的 `siliconflow_pro` 服务。

**Q: API 调用频繁被限制？**
A: 降低 `qps_limit` 值，避免请求过于频繁。

### 🗂️ 文件管理问题

**Q: 如何恢复原始文件？**
A: 检查 `*_original.pdf` 备份文件，或使用内嵌的原始PDF附件。

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

---

**Happy translating! 🎉**
