# -*- coding: utf-8 -*-
"""
Configuration Web UI for TranslateEndNote (refactored, aligned save row)

修改点：
- 让「保存配置」按钮与「就绪/保存状态」输入框在同一行水平对齐。
- 通过 Row + CSS（.save-row）实现垂直居中对齐；隐藏 Textbox 标签，保持单行显示。
- 其余结构与上一版一致。
"""

import json
import time
import subprocess
import sys
import atexit
from pathlib import Path
from typing import Dict, Any

import gradio as gr

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    PSUTIL_AVAILABLE = False


class ConfigWebUI:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or self._get_default_config_path()
        self.config = self._load_config()
        self.server = None
        self.port = None
        self.last_activity_time = time.time()
        self.inactivity_timer = None
        self.inactivity_timeout = 3600

        self.backend_process = None
        self.current_logs = []
        self.max_log_lines = 1000
        self.log_monitoring = False
        self.auto_refresh_enabled = True
        self.auto_refresh_interval = 2.0

        atexit.register(self._cleanup)

    def _get_default_config_path(self) -> str:
        webui_config_path = str(Path(__file__).parent / "config.json")
        for path in [
            webui_config_path,
            "configs/config.json",
            "config.json",
            str(Path(__file__).parent / "configs" / "config.json"),
        ]:
            if Path(path).exists():
                return path
        Path(webui_config_path).parent.mkdir(parents=True, exist_ok=True)
        return webui_config_path

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            cfg = self._get_default_config()
            self._save_config(cfg)
            return cfg
        except Exception:
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "skip_translated_by_metadata": True,
            "skip_max_file_size": True,
            "skip_max_pages": True,
            "skip_filename_format_check": True,
            "skip_filename_contains_chinese": True,
            "skip_contains_skip_keywords": True,
            "skip_chinese_pdf_vlm": False,

            "delete_mono_pdf": True,
            "delete_all_except_final": False,
            "suppress_skipped_output": True,

            "pdf_root": "D:\\User_Files\\My EndNote Library.Data\\PDF",
            "pdf2zh_exe": "D:\\Python_Projects\\TranslateEndNote\\pdf2zh\\pdf2zh.exe",
            "log_dir": "D:\\Downloads",

            "lang_in": "en",
            "lang_out": "zh-CN",
            "translation_service": "siliconflow_free",

            "siliconflow_api_key": "",
            "siliconflow_model": "Qwen/Qwen3-8B",
            "siliconflow_base": "https://api.siliconflow.cn/v1",

            "qps_limit": 20,
            "gap": 0.0,
            "max_size_bytes": 104857600,
            "max_pages": 500,
            "max_time": 7200,

            "vlm_api_key": "",
            "vlm_model": "deepseek-ai/deepseek-vl2",
            "vlm_base": "https://api.siliconflow.cn/v1",
            "vlm_k_pages": 5,
            "vlm_dpi": 150,
            "vlm_detail": "low",
            "vlm_per_page_timeout": 600,

            "skip_keywords": [
                "clear",
                "clean",
                "supplement",
                "pdf2zh-updated",
                "pdf2zh-merged",
            ],
        }

    def _save_config(self, config: Dict[str, Any]) -> bool:
        try:
            Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def _update_activity(self):
        self.last_activity_time = time.time()

    def _is_backend_running(self) -> bool:
        if self.backend_process and self.backend_process.poll() is None:
            return True
        if not PSUTIL_AVAILABLE:
            return False
        try:
            for proc in psutil.process_iter(["cmdline"]):
                cmd = proc.info.get("cmdline") or []
                if any("pdf_batch_translator.py" in x for x in cmd):
                    return True
        except Exception:
            pass
        return False

    def _start_backend(self) -> str:
        if self._is_backend_running():
            return "后端已在运行中"
        try:
            backend_path = Path(__file__).parent.parent / "src" / "pdf_batch_translator.py"
            if not backend_path.exists():
                return f"后端脚本不存在: {backend_path}"
            self.backend_process = subprocess.Popen(
                [sys.executable, str(backend_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True,
            )
            self._start_log_monitor()
            return "后端启动成功"
        except Exception as e:
            return f"启动后端失败: {e}"

    def _stop_backend(self) -> str:
        try:
            if self.backend_process and self.backend_process.poll() is None:
                self.backend_process.terminate()
                self.backend_process.wait(timeout=5)
        except Exception:
            try:
                if self.backend_process:
                    self.backend_process.kill()
            except Exception:
                pass
        finally:
            self.backend_process = None
            self.log_monitoring = False
        return "后端已停止"

    def _start_log_monitor(self):
        if self.log_monitoring or not self.backend_process:
            return
        self.log_monitoring = True

        def _loop():
            while self.log_monitoring and self.backend_process:
                line = self.backend_process.stdout.readline()
                if line:
                    ts = time.strftime("%H:%M:%S")
                    self.current_logs.append(f"[{ts}] {line.strip()}")
                    if len(self.current_logs) > self.max_log_lines:
                        self.current_logs = self.current_logs[-self.max_log_lines:]
                else:
                    if self.backend_process.poll() is not None:
                        break
                    time.sleep(0.05)
            self.log_monitoring = False

        import threading
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def _get_logs_text(self) -> str:
        return "\n".join(self.current_logs[-200:])
    
    def _auto_refresh_logs(self) -> str:
        """自动刷新日志内容"""
        if self.auto_refresh_enabled and self._is_backend_running():
            return self._get_logs_text()
        return self._get_logs_text()
    
    def _toggle_auto_refresh(self, enabled: bool) -> str:
        """切换自动刷新状态"""
        self.auto_refresh_enabled = enabled
        status = "已启用" if enabled else "已禁用"
        return f"自动刷新{status}"
    
    
    def _status_html(self) -> str:
        if self._is_backend_running():
            return '<div class="status-indicator" style="background:#28a745;color:#fff;">🟢 运行中</div>'
        return '<div class="status-indicator" style="background:#dc3545;color:#fff;">🔴 已停止</div>'

    def _cleanup(self):
        self.log_monitoring = False
        try:
            self._stop_backend()
        except Exception:
            pass

    def save_config_handler(self, *args) -> str:
        self._update_activity()
        (
            skip_translated_by_metadata, skip_max_file_size, skip_max_pages,
            skip_filename_format_check, skip_filename_contains_chinese,
            skip_contains_skip_keywords, skip_chinese_pdf_vlm,
            delete_mono_pdf, delete_all_except_final, suppress_skipped_output,
            pdf_root, pdf2zh_exe, log_dir,
            lang_in, lang_out, translation_service,
            siliconflow_api_key, siliconflow_model, siliconflow_base,
            qps_limit, gap, max_size_bytes, max_pages, max_time,
            vlm_api_key, vlm_model, vlm_base, vlm_k_pages, vlm_dpi,
            vlm_detail, vlm_per_page_timeout, skip_keywords_text,
        ) = args

        skip_keywords = [k.strip() for k in (skip_keywords_text or "").split("\n") if k.strip()]
        new_cfg = {
            "skip_translated_by_metadata": skip_translated_by_metadata,
            "skip_max_file_size": skip_max_file_size,
            "skip_max_pages": skip_max_pages,
            "skip_filename_format_check": skip_filename_format_check,
            "skip_filename_contains_chinese": skip_filename_contains_chinese,
            "skip_contains_skip_keywords": skip_contains_skip_keywords,
            "skip_chinese_pdf_vlm": skip_chinese_pdf_vlm,
            "delete_mono_pdf": delete_mono_pdf,
            "delete_all_except_final": delete_all_except_final,
            "suppress_skipped_output": suppress_skipped_output,
            "pdf_root": pdf_root,
            "pdf2zh_exe": pdf2zh_exe,
            "log_dir": log_dir,
            "lang_in": lang_in,
            "lang_out": lang_out,
            "translation_service": translation_service,
            "siliconflow_api_key": siliconflow_api_key,
            "siliconflow_model": siliconflow_model,
            "siliconflow_base": siliconflow_base,
            "qps_limit": qps_limit,
            "gap": gap,
            "max_size_bytes": max_size_bytes,
            "max_pages": max_pages,
            "max_time": max_time,
            "vlm_api_key": vlm_api_key,
            "vlm_model": vlm_model,
            "vlm_base": vlm_base,
            "vlm_k_pages": vlm_k_pages,
            "vlm_dpi": vlm_dpi,
            "vlm_detail": vlm_detail,
            "vlm_per_page_timeout": vlm_per_page_timeout,
            "skip_keywords": skip_keywords,
        }
        if self._save_config(new_cfg):
            self.config = new_cfg
            return "配置已保存"
        return "配置保存失败"

    def create_ui(self):
        with gr.Blocks(
            title="TranslateEndNote 配置管理",
            theme=gr.themes.Soft(),
            css="""
            .main-container{max-width:1400px;margin:0 auto}
            .config-panel,.control-panel{background:#f8f9fa;border:1px solid #e9ecef;border-radius:8px;padding:20px}
            .save-section{background:#fff;border:1px solid #dee2e6;border-radius:6px;padding:12px;margin-bottom:15px}
            .save-row{display:flex;align-items:center;gap:12px}
            .save-row .gr-textbox, .save-row .gr-button{margin:0}
            .log-display{font-family:Consolas,Monaco,'Courier New',monospace;font-size:.85em;background:#f8f9fa;color:#495057;padding:15px;border-radius:6px;height:350px;overflow-y:auto;border:1px solid #dee2e6}
            .section-title{color:#495057;border-bottom:2px solid #e9ecef;padding-bottom:8px;margin-bottom:15px}
            .status-indicator{padding:6px 12px;border-radius:4px;font-weight:500;text-align:center;font-size:.9em}
            """,
        ) as demo:
            with gr.Column(elem_classes="main-container"):
                gr.Markdown("# 🛠️ TranslateEndNote 配置管理")
                gr.Markdown(f"**配置文件路径：** `{self.config_path}`")

                # 顶部：保存 + 参数Tabs
                with gr.Column(elem_classes="config-panel"):
                    # —— 对齐：状态框 + 保存按钮同一行 ——
                    with gr.Row(elem_classes="save-section save-row"):
                        save_status = gr.Textbox(
                            value="就绪", interactive=False, show_label=False,
                            lines=1, max_lines=1, scale=5
                        )
                        save_button = gr.Button("💾 保存配置", variant="primary", scale=1)

                    with gr.Tabs():
                        with gr.TabItem("跳过规则"):
                            gr.Markdown('<div class="section-title">🚫 <strong>文件处理跳过规则配置</strong></div>')
                            with gr.Row():
                                skip_translated_by_metadata = gr.Checkbox(label="跳过已翻译文件（元数据检查）", value=self.config.get("skip_translated_by_metadata", True))
                                skip_max_file_size = gr.Checkbox(label="跳过大文件", value=self.config.get("skip_max_file_size", True))
                                skip_max_pages = gr.Checkbox(label="跳过多页文件", value=self.config.get("skip_max_pages", True))
                            with gr.Row():
                                skip_filename_format_check = gr.Checkbox(label="跳过格式不符文件", value=self.config.get("skip_filename_format_check", True))
                                skip_filename_contains_chinese = gr.Checkbox(label="跳过中文文件名", value=self.config.get("skip_filename_contains_chinese", True))
                                skip_contains_skip_keywords = gr.Checkbox(label="跳过关键词文件", value=self.config.get("skip_contains_skip_keywords", True))
                                skip_chinese_pdf_vlm = gr.Checkbox(label="跳过中文PDF（VLM检测）", value=self.config.get("skip_chinese_pdf_vlm", False))
                            gr.Markdown('<div class="section-title">📝 <strong>跳过关键词配置</strong></div>')
                            skip_keywords_text = gr.Textbox(label="跳过关键词（每行一个）", value="\n".join(self.config.get("skip_keywords", [])), lines=6)

                        with gr.TabItem("处理参数"):
                            gr.Markdown('<div class="section-title">⚙️ <strong>处理参数配置</strong></div>')
                            with gr.Row():
                                qps_limit = gr.Number(label="QPS限速", value=self.config.get("qps_limit", 20))
                                gap = gr.Number(label="中缝间距", value=self.config.get("gap", 0.0))
                                max_size_bytes = gr.Number(label="最大文件大小", value=self.config.get("max_size_bytes", 104857600))
                            with gr.Row():
                                max_pages = gr.Number(label="最大页数", value=self.config.get("max_pages", 500))
                                max_time = gr.Number(label="最大处理时间", value=self.config.get("max_time", 7200))
                                vlm_k_pages = gr.Number(label="VLM检测页数", value=self.config.get("vlm_k_pages", 5))
                            with gr.Row():
                                vlm_dpi = gr.Number(label="VLM渲染DPI", value=self.config.get("vlm_dpi", 150))
                                vlm_detail = gr.Dropdown(label="VLM图像细节", choices=["low", "high", "auto"], value=self.config.get("vlm_detail", "low"))
                                vlm_per_page_timeout = gr.Number(label="VLM单页超时", value=self.config.get("vlm_per_page_timeout", 600))

                        with gr.TabItem("后处理"):
                            gr.Markdown('<div class="section-title">🧹 <strong>文件处理后的清理配置</strong></div>')
                            with gr.Row():
                                delete_mono_pdf = gr.Checkbox(label="删除翻译版本PDF", value=self.config.get("delete_mono_pdf", True))
                                delete_all_except_final = gr.Checkbox(label="只保留最终文件", value=self.config.get("delete_all_except_final", False))
                                suppress_skipped_output = gr.Checkbox(label="抑制跳过状态输出", value=self.config.get("suppress_skipped_output", True))

                        with gr.TabItem("文件路径"):
                            gr.Markdown('<div class="section-title">📁 <strong>系统文件路径配置</strong></div>')
                            pdf_root = gr.Textbox(label="PDF根目录", value=self.config.get("pdf_root", ""))
                            pdf2zh_exe = gr.Textbox(label="pdf2zh可执行文件路径", value=self.config.get("pdf2zh_exe", ""))
                            log_dir = gr.Textbox(label="日志目录", value=self.config.get("log_dir", ""))

                        with gr.TabItem("翻译设置"):
                            gr.Markdown('<div class="section-title">🌐 <strong>翻译服务配置</strong></div>')
                            with gr.Row():
                                lang_in = gr.Dropdown(label="源语言", choices=["en", "zh-CN", "ja", "ko", "fr", "de", "es", "ru"], value=self.config.get("lang_in", "en"))
                                lang_out = gr.Dropdown(label="目标语言", choices=["zh-CN", "en", "ja", "ko", "fr", "de", "es", "ru"], value=self.config.get("lang_out", "zh-CN"))
                                translation_service = gr.Dropdown(label="翻译服务", choices=["siliconflow_free", "siliconflow_pro", "auto"], value=self.config.get("translation_service", "siliconflow_free"))

                        with gr.TabItem("API密钥"):
                            gr.Markdown('<div class="section-title">🔑 <strong>API密钥配置</strong></div>')
                            siliconflow_api_key = gr.Textbox(label="SiliconFlow API密钥", value=self.config.get("siliconflow_api_key", ""), type="password")
                            vlm_api_key = gr.Textbox(label="VLM API密钥", value=self.config.get("vlm_api_key", ""), type="password")

                        with gr.TabItem("模型设置"):
                            gr.Markdown('<div class="section-title">🤖 <strong>AI模型配置</strong></div>')
                            with gr.Row():
                                siliconflow_model = gr.Textbox(label="翻译模型", value=self.config.get("siliconflow_model", "Qwen/Qwen3-8B"))
                                siliconflow_base = gr.Textbox(label="翻译API地址", value=self.config.get("siliconflow_base", "https://api.siliconflow.cn/v1"))
                            with gr.Row():
                                vlm_model = gr.Textbox(label="视觉语言模型", value=self.config.get("vlm_model", "deepseek-ai/deepseek-vl2"))
                                vlm_base = gr.Textbox(label="VLM API地址", value=self.config.get("vlm_base", "https://api.siliconflow.cn/v1"))

                # 底部：运行监控
                with gr.Column(elem_classes="control-panel"):
                    gr.Markdown('<div class="section-title">🔧 <strong>后端控制</strong></div>')
                    with gr.Row():
                        backend_status = gr.HTML(value=self._status_html(), label="后端状态")
                        start_button = gr.Button("▶️ 启动后端")
                        stop_button = gr.Button("⏹️ 停止后端")
                        refresh_button = gr.Button("🔄 刷新状态")
                    gr.Markdown('<div class="section-title">📋 <strong>后端日志</strong></div>')
                    with gr.Row():
                        auto_refresh_checkbox = gr.Checkbox(label="自动刷新", value=self.auto_refresh_enabled)
                        refresh_interval = gr.Number(label="刷新间隔(秒)", value=self.auto_refresh_interval, minimum=0.5, maximum=10.0, step=0.5)
                        clear_logs_button = gr.Button("🗑️ 清空日志")
                    log_display = gr.Textbox(label="实时日志", value="等待启动后端...", lines=15, max_lines=30, interactive=False, elem_classes="log-display")

                # 事件绑定
                save_button.click(
                    fn=self.save_config_handler,
                    inputs=[
                        skip_translated_by_metadata, skip_max_file_size, skip_max_pages,
                        skip_filename_format_check, skip_filename_contains_chinese,
                        skip_contains_skip_keywords, skip_chinese_pdf_vlm,
                        delete_mono_pdf, delete_all_except_final, suppress_skipped_output,
                        pdf_root, pdf2zh_exe, log_dir,
                        lang_in, lang_out, translation_service,
                        siliconflow_api_key, siliconflow_model, siliconflow_base,
                        qps_limit, gap, max_size_bytes, max_pages, max_time,
                        vlm_api_key, vlm_model, vlm_base, vlm_k_pages, vlm_dpi,
                        vlm_detail, vlm_per_page_timeout, skip_keywords_text,
                    ],
                    outputs=[save_status],
                )

                start_button.click(fn=self._start_backend, outputs=[save_status])
                stop_button.click(fn=self._stop_backend, outputs=[save_status])

                def _refresh():
                    return self._status_html(), self._get_logs_text(), "界面已刷新"

                refresh_button.click(fn=_refresh, outputs=[backend_status, log_display, save_status])
                clear_logs_button.click(fn=lambda: ("", "日志已清空"), outputs=[log_display, save_status])
                
                # 自动刷新控制
                auto_refresh_checkbox.change(
                    fn=self._toggle_auto_refresh,
                    inputs=[auto_refresh_checkbox],
                    outputs=[save_status]
                )
                
                refresh_interval.change(
                    fn=lambda x: setattr(self, 'auto_refresh_interval', x) or f"刷新间隔已设置为 {x} 秒",
                    inputs=[refresh_interval],
                    outputs=[save_status]
                )
                
                # 自动刷新定时器
                auto_refresh_timer = gr.Timer(value=self.auto_refresh_interval)
                auto_refresh_timer.tick(
                    fn=self._auto_refresh_logs,
                    outputs=[log_display]
                )
                
                # 根据自动刷新状态控制定时器
                def control_timer(enabled):
                    if enabled:
                        auto_refresh_timer.tick()
                        return f"自动刷新已启用"
                    else:
                        auto_refresh_timer.stop()
                        return f"自动刷新已禁用"
                
                auto_refresh_checkbox.change(
                    fn=control_timer,
                    inputs=[auto_refresh_checkbox],
                    outputs=[save_status]
                )
                
                refresh_interval.change(
                    fn=lambda interval: setattr(auto_refresh_timer, 'value', interval) or f"刷新间隔已设置为 {interval} 秒",
                    inputs=[refresh_interval],
                    outputs=[save_status]
                )

        return demo

    def launch(self, server_name="0.0.0.0", port=7861, share=False):
        demo = self.create_ui()
        self.port = port
        print("Starting configuration management Web UI...")
        demo.launch(server_name=server_name, server_port=port, share=share, prevent_thread_lock=True)


if __name__ == "__main__":
    ui = ConfigWebUI()
    ui.launch()
