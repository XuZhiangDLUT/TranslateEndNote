# TranslateEndNote

🚀 批量 **PDF→中英双语** 翻译与合成工具

- 以 [`PDFMathTranslate-next` 的 `pdf2zh` CLI](https://github.com/PDFMathTranslate/PDFMathTranslate-next) 为翻译引擎，
- 在 **不破坏原版注释/链接** 的前提下，把**原文（左）+ 译文（右)**并排合成，覆盖输出为原文件名，并写入可溯源的元数据与附件。

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
│   ├── pdf_batch_translator.py  # ⭐ 主程序入口（批处理、合成、元数据与附件）
│   └── pdf_language_detector.py  # 🔍 VLM 中文检测模块
├── utils/
│   ├── config_utils.py          # 🔧 配置工具模块
│   ├── pdf_cleanup_tool.py      # 🧹 PDF清理工具
│   ├── pdf_merger.py            # 🔗 PDF合并工具
│   ├── pdf_splitter.py          # ✂️ PDF分割工具
│   ├── pdf_orphan_metadata_manager.py  # 📄 孤儿元数据管理工具
│   └── pdf_pair_metadata_manager.py    # 📋 配对元数据管理工具
└── webui/
    ├── launcher.py              # 🚀 Web UI 启动器
    ├── config_webui.py          # 🌐 Web UI 配置管理界面
    └── config.json              # ⚙️ Web UI 配置文件
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
- `gradio`：Web UI 框架
- `fastapi`：Web 服务器框架
- `uvicorn`：ASGI 服务器

### 🔑 步骤三：配置 API 密钥

**配置优先级**：系统会优先从配置文件读取，如果配置值为空字符串则从环境变量读取。

**推荐使用环境变量**：

```bash
# macOS / Linux
export SILICONFLOW_API_KEY="your_api_key_here"
export VLM_API_KEY="your_vlm_api_key_here"

# Windows PowerShell
setx SILICONFLOW_API_KEY "your_api_key_here"
setx VLM_API_KEY "your_vlm_api_key_here"
```

**或在配置文件中设置**：

```json
{
  "siliconflow_api_key": "your_api_key_here",
  "vlm_api_key": "your_vlm_api_key_here"
}
```

> 💡 **配置说明**：
> - 如果配置文件中的值为空字符串，系统会自动从对应的环境变量读取
> - 支持的环境变量：`SILICONFLOW_API_KEY`、`VLM_API_KEY`
> - **免费通道**：本项目也支持 `pdf2zh` 的免费翻译通道

### ⚙️ 步骤四：配置文件设置

编辑 `configs/config.json`，至少设置：

```json
{
  "pdf_root": "/path/to/your/pdfs",
  "pdf2zh_exe": "/path/to/pdf2zh.exe"
}
```

**重要配置项**：

| 配置项                  | 默认值               | 说明         |
| ----------------------- | -------------------- | ------------ |
| `max_size_bytes`      | 100MB                | 文件大小限制 |
| `max_pages`           | 500                  | 页数限制     |
| `qps_limit`           | 20                   | 请求限速     |
| `translation_service` | `siliconflow_free` | 翻译服务类型 |
| `lang_in`             | `en`               | 源语言       |
| `lang_out`            | `zh-CN`            | 目标语言     |

### 🚀 步骤五：运行程序

```bash
# 启动批量翻译
python src/pdf_batch_translator.py
```

**输出信息**：

- 控制台实时显示处理状态
- `batch_translate_log.csv` 记录详细日志
- 支持 `--help` 查看更多选项

---

## 🌐 Web UI 配置管理

### 🚀 启动 Web UI

本项目提供了一个基于 Gradio 的 Web 配置管理界面，方便用户通过浏览器进行配置管理。

```bash
# 启动 Web UI 配置管理器
python webui/launcher.py
```

### ⚙️ Web UI 功能特性

- **可视化配置管理**：通过浏览器界面管理所有配置参数
- **实时保存**：配置修改后即时保存到配置文件
- **多标签页组织**：配置按功能分类，易于管理
- **参数验证**：自动验证配置参数的有效性
- **中文界面**：完全中文化的用户界面
- **后端控制**：可直接在界面中启动/停止后端服务
- **实时日志**：显示后端服务的运行日志
- **状态监控**：实时显示后端服务运行状态

### 📋 Web UI 配置分类

1. **跳过规则**：配置文件处理跳过条件
   - 已翻译文件跳过（元数据检查）
   - 大文件和多页文件跳过
   - 文件名格式和中文文件名检查
   - 关键词过滤和中文PDF VLM检测

2. **处理参数**：配置处理限制和超时设置
   - QPS限速和中缝间距
   - 文件大小、页数和时间限制
   - VLM检测参数配置

3. **后处理**：配置文件清理和输出选项
   - 删除翻译版本PDF选项
   - 只保留最终文件设置
   - 抑制跳过状态输出

4. **文件路径**：配置系统路径和文件位置
   - PDF根目录设置
   - pdf2zh可执行文件路径
   - 日志目录配置

5. **翻译设置**：配置翻译服务参数
   - 源语言和目标语言选择
   - 翻译服务类型选择

6. **API密钥**：管理各种服务的API密钥
   - SiliconFlow API密钥
   - VLM API密钥
   - 密码类型输入保护

7. **模型设置**：配置AI模型参数
   - 翻译模型和API地址
   - 视觉语言模型和API地址

8. **跳过关键词**：管理文件名过滤关键词
   - 多行文本输入支持
   - 自定义过滤规则

### 🔧 Web UI 启动选项

```bash
# 基本启动（默认端口 7860）
python webui/launcher.py

# 指定配置文件
python webui/launcher.py --config path/to/config.json

# 指定端口和主机
python webui/launcher.py --port 8080 --host 0.0.0.0

# 启用公网分享（生成外网访问链接）
python webui/launcher.py --share

# 启用调试模式（显示详细错误信息）
python webui/launcher.py --debug
```

### 🌐 访问 Web UI

启动后，在浏览器中访问：`http://localhost:7860`

- **默认端口**：7860
- **默认主机**：127.0.0.1
- **自动打开浏览器**：启动后会自动在默认浏览器中打开界面
- **多浏览器支持**：支持 Chrome、Firefox、Safari、Edge 等主流浏览器

### 🎛️ Web UI 界面布局

```
┌─────────────────────────────────────────────────────────────┐
│                    TranslateEndNote 配置管理                   │
│                  配置文件路径: webui/config.json              │
├─────────────────────────────────────────────────────────────┤
│  [就绪]                    💾 保存配置                       │
├─────────────────────────────────────────────────────────────┤
│  [跳过规则] [处理参数] [后处理] [文件路径] [翻译设置]        │
│  [API密钥]   [模型设置]  [跳过关键词]                       │
├─────────────────────────────────────────────────────────────┤
│                         配置内容区域                          │
├─────────────────────────────────────────────────────────────┤
│                      🔧 后端控制                              │
│  🟢 运行中    [▶️ 启动后端] [⏹️ 停止后端] [🔄 刷新状态]      │
│                      📋 后端日志                              │
│  [实时日志显示区域]                                        │
│  [🗑️ 清空日志]                                            │
└─────────────────────────────────────────────────────────────┘
```

### 💡 Web UI 使用提示

#### 配置管理
- **实时保存**：点击"💾 保存配置"按钮立即保存到配置文件
- **状态显示**：保存状态会显示在顶部的状态框中
- **配置文件路径**：界面顶部显示当前使用的配置文件路径
- **参数验证**：系统会自动验证输入参数的有效性

#### 后端控制
- **状态监控**：实时显示后端服务运行状态（🟢运行中/🔴已停止）
- **一键启动**：点击"▶️ 启动后端"按钮启动翻译服务
- **一键停止**：点击"⏹️ 停止后端"按钮停止翻译服务
- **状态刷新**：点击"🔄 刷新状态"按钮手动刷新状态和日志

#### 日志管理
- **实时日志**：显示后端服务的运行日志，带时间戳
- **日志限制**：最多显示最近200行日志
- **清空日志**：点击"🗑️ 清空日志"按钮清空日志显示

#### 安全特性
- **密码保护**：API密钥字段使用密码类型输入，内容会被遮蔽
- **本地访问**：默认只允许本地访问，确保配置安全
- **配置备份**：修改配置时会自动保存，避免配置丢失

### 🔧 故障排除

#### Web UI 启动问题
- **端口占用**：使用 `--port` 参数指定其他端口
- **依赖缺失**：确保已安装 `gradio>=4.0.0`
- **权限问题**：确保对配置文件有读写权限

#### 配置问题
- **配置不生效**：检查配置文件路径是否正确
- **重置配置**：删除配置文件，重启Web UI会生成默认配置
- **配置同步**：Web UI和命令行工具使用不同的配置文件，需要分别配置

#### 后端连接问题
- **后端启动失败**：检查 `src/pdf_batch_translator.py` 是否存在
- **日志显示异常**：确保后端进程正常启动且输出日志
- **权限问题**：确保对PDF目录有读写权限

---

## 🔧 `pdf_batch_translator.py` 详解（最重要）

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

### 🔍 `pdf_language_detector.py`

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

### 🔧 `config_utils.py`

**用途**：配置工具模块，提供配置读取功能

**功能**：

- 优先从配置文件读取配置值
- 如果配置值为空字符串则从环境变量读取
- 支持多种配置项的环境变量映射

**配置优先级**：

1. 配置文件中的值
2. 环境变量（当配置文件值为空字符串时）
3. 默认值

### 🧹 `pdf_cleanup_tool.py`

**用途**：PDF清理工具，清理临时和旁路文件

**功能**：

- 清理 `*.pdf2zh-updated.pdf` 文件
- 清理 `*.pdf2zh-merged.pdf` 文件
- 清理其他临时文件
- 释放存储空间

**使用方法**：

```bash
python utils/pdf_cleanup_tool.py /path/to/pdfs
```

### 🔗 `pdf_merger.py`

**用途**：PDF合并工具，将多个PDF文件合并为一个

**功能**：

- 支持批量PDF文件合并
- 保持原有页面顺序
- 支持输出到指定目录

**使用方法**：

```bash
python utils/pdf_merger.py
```

### ✂️ `pdf_splitter.py`

**用途**：PDF分割工具，将大PDF文件分割为小文件

**功能**：

- 按页数分割PDF文件
- 保持原有页面质量
- 支持输出到指定目录

**使用方法**：

```bash
python utils/pdf_splitter.py
```

### 📄 `pdf_orphan_metadata_manager.py`

**用途**：为没有 `_original` 配对的独立PDF文件补全元数据

**功能**：

- 使用视觉语言模型(VLM)智能检测PDF是否为翻译版本
- 为检测出的翻译文件添加 `translated` 状态元数据
- 为检测出的未翻译文件添加 `untranslated` 状态元数据
- 支持多种筛选规则避免重复处理

**检测规则**：
仅处理没有对应 `_original.pdf` 的独立PDF文件，使用VLM进行左右页面分析：
- 将PDF页面水平分割为左右两部分
- 统计左右两侧的中文字符数量
- **翻译文件判定条件**：右侧中文数 ≥ 左侧中文数 且 左侧非中文数 > 右侧非中文数
- **未翻译文件判定条件**：不满足上述条件的文件

**跳过规则**：
- 已有元数据附件的文件
- `_original.pdf` 备份文件
- `.mono.pdf`、`.dual.pdf` 等生成文件
- 有对应 `_original.pdf` 的文件
- 文件名包含中文的文件
- 不符合 `Author-YYYY-Title` 格式的文件
- 超过100MB或500页的文件
- 包含排除关键词的文件

**使用方法**：

```bash
python utils/pdf_orphan_metadata_manager.py
```

### 📋 `pdf_pair_metadata_manager.py`

**用途**：为有 `_original` 配对的已翻译PDF文件补全元数据

**功能**：

- 为翻译后的PDF文件添加完整的 `translated` 状态元数据
- 为对应的 `_original.pdf` 文件添加 `untranslated` 状态元数据
- 在翻译PDF首页添加可点击的原始文件链接标签
- 嵌入原始PDF作为附件，支持点击打开
- 自动计算页面间距等合并参数

**处理规则**：
- 寻找配对的 `X.pdf`（翻译文件）和 `X_original.pdf`（原始文件）
- 为翻译文件添加包含合并参数的完整元数据
- 为原始文件添加最小化的未翻译标记
- 在翻译文件首页添加"打开原始PDF"可点击标签
- 嵌入原始PDF文件作为附件

**元数据内容**：
- **翻译文件**：`status: "translated"`、模型名称、运行时间、页面尺寸、间距等
- **原始文件**：`status: "untranslated"`、运行时间

**使用方法**：

```bash
python utils/pdf_pair_metadata_manager.py
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

### 🌐 Web UI 问题

**Q: Web UI 无法启动？**
A: 请检查以下几点：
- 确保已安装 gradio：`pip install gradio>=4.0.0`
- 检查 Python 版本是否为 3.10+
- 确认 webui/launcher.py 文件存在
- 使用 `--debug` 参数查看详细错误信息

**Q: Web UI 端口被占用？**
A: 使用 `--port` 参数指定其他端口：
```bash
python webui/launcher.py --port 8080
```

**Q: 如何在外网访问 Web UI？**
A: 使用 `--share` 参数生成公网分享链接：
```bash
python webui/launcher.py --share
```

**Q: Web UI 配置不生效？**
A: 请检查：
- 配置文件路径是否正确
- 是否有配置文件的写入权限
- 保存后是否显示"配置已保存"状态
- 尝试重启 Web UI 服务

**Q: 如何重置 Web UI 配置？**
A: 删除对应的配置文件，重新启动 Web UI 会生成默认配置：
```bash
# 删除 Web UI 配置文件
rm webui/config.json
# 重新启动 Web UI
python webui/launcher.py
```

**Q: 后端服务启动失败？**
A: 请检查：
- `src/pdf_batch_translator.py` 文件是否存在
- 是否有足够的系统权限
- 检查后端日志显示的错误信息
- 确保相关依赖已正确安装

**Q: Web UI 和命令行工具配置不同步？**
A: Web UI 使用 `webui/config.json`，而命令行工具使用 `configs/config.json`，需要分别配置或复制配置文件。

**Q: 如何在 Web UI 中查看实时日志？**
A: 启动后端服务后，日志会自动显示在界面底部的日志区域，支持实时更新。

**Q: Web UI 界面显示异常？**
A: 尝试以下方法：
- 清除浏览器缓存
- 尝试使用不同的浏览器
- 检查网络连接是否正常
- 使用 `--debug` 模式启动查看错误信息

**Q: 如何保护 Web UI 的安全访问？**
A: 建议以下安全措施：
- 使用默认的本地访问（127.0.0.1）
- 不要在公网环境启用 `--share` 功能
- 定期更换 API 密钥
- 使用防火墙限制访问权限

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

---

**Happy translating! 🎉**
