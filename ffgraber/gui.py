"""Localized desktop UI. Only the Tk main thread ever touches widgets."""

import asyncio
from collections import Counter
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .clipboard import paste_content, read_html_clipboard
from .engine import ExtractionEngine, Options
from .i18n import LANGUAGES, load_language, save_language, translate
from .links import parse_input, url_key
from .models import Record, direct_download_links, export_records, output_links
from .reference import validate_ff_urls

STATUS = {"queued": "대기", "running": "추출 중", "waiting": "브라우저 확인",
          "scanned": "목록 확인", "found": "FF 링크 발견", "done": "완료",
          "failed": "실패", "cancelled": "중지됨", "skipped": "건너뜀"}
KINDS = {"page": "웹 페이지", "paste": "링크 목록", "filecrypt": "Filecrypt",
         "filecrypt-link": "Filecrypt 개별", "ff": "FuckingFast", "direct": "직접 URL"}
BROWSERS = {"자동 선택 (Chrome → Edge)": "auto", "Google Chrome": "chrome",
            "Microsoft Edge": "msedge"}


class App:
    def __init__(self, root, initial_urls=None, language=None):
        self.root = root
        self.language = language if language in LANGUAGES else load_language()
        self.localized_widgets = []
        self.tabs = []
        self.status_message = ("URL 입력 후 추출 시작을 누르세요. Ctrl+Enter로도 시작할 수 있습니다.", {})
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.skip = threading.Event()
        self.records = {}
        self.row_ids = {}
        self.worker = None
        self.closing = False
        self.fatal_error = ""
        self.log_entries = []
        root.geometry("1120x840")
        root.minsize(880, 680)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh_language()
        if initial_urls:
            self.input.insert("1.0", "\n".join(initial_urls))
        self.poll_id = root.after(100, self.poll)

    def tr(self, message, **values):
        return translate(message, self.language, **values)

    def ui(self, factory, parent, *, text, **options):
        widget = factory(parent, text=self.tr(text), **options)
        self.localized_widgets.append((widget, text))
        return widget

    def set_status(self, message, **values):
        self.status_message = (message, values)
        localized = {key: self.tr(value) if key in {"status", "prefix"} else value
                     for key, value in values.items()}
        self.status_var.set(self.tr(message, **localized))

    def change_language(self, language=None, persist=True):
        if language is None:
            language = next(code for code, label in LANGUAGES.items() if label == self.language_var.get())
        if language not in LANGUAGES:
            return
        self.language = language
        self.refresh_language()
        if persist:
            try:
                save_language(language)
            except OSError as exc:
                self.set_status("언어를 변경했지만 설정을 저장하지 못했습니다: {error}", error=str(exc))

    def refresh_language(self):
        self.root.title(f"FFGraber {__version__} · {self.tr('브라우저 링크 추출기')}")
        self.language_var.set(LANGUAGES[self.language])
        for widget, text in self.localized_widgets:
            widget.configure(text=self.tr(text))
        index = max(self.browser.current(), 0)
        choices = [self.tr(label) for label in BROWSERS]
        self.browser.configure(values=choices)
        self.browser_var.set(choices[index])
        for column, label in [("kind", "종류"), ("name", "파일 / 항목"), ("status", "상태"), ("url", "다운로드 URL / 원본")]:
            self.tree.heading(column, text=self.tr(label))
        for frame, text in self.tabs:
            self.notebook.tab(frame, text=self.tr(text))
        for index, text in enumerate(("선택한 다운로드 URL 복사", "성공 URL 전체 복사")):
            self.copy_menu.entryconfigure(index, label=self.tr(text))
        for key, record in self.records.items():
            self.tree.item(self.row_ids[key], values=self.row_values(record))
        self.show_details()
        self.set_text(self.logs, "".join(f"[{time}] {self.tr(message)}\n" for time, message in self.log_entries))
        self.refresh_copy_button()
        self.set_status(self.status_message[0], **self.status_message[1])

    def row_values(self, record):
        return (self.tr(KINDS[record.kind]), record.name, self.tr(STATUS[record.status]),
                record.direct_url or record.resolved_url or record.url)

    def refresh_copy_button(self):
        count = len(direct_download_links(self.records.values()))
        self.extracted_copy_button.configure(state="normal" if count else "disabled")
        self.extracted_count_var.set(self.tr("{count}개 추출 링크", count=count))

    def build(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=28)
        style.configure("Title.TLabel", font=("맑은 고딕", 21, "bold"))
        body = ttk.Frame(self.root, padding=18)
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body)
        header.pack(fill="x")
        self.ui(ttk.Label, header, text="FFGraber", style="Title.TLabel").pack(side="left")
        self.language_var = tk.StringVar(value=LANGUAGES[self.language])
        language = ttk.Combobox(header, textvariable=self.language_var, values=list(LANGUAGES.values()),
                               state="readonly", width=12)
        language.pack(side="right")
        language.bind("<<ComboboxSelected>>", lambda event: self.change_language())
        self.ui(ttk.Label, header, text="언어").pack(side="right", padx=8)
        self.ui(ttk.Label, body, text="FuckingFast 파일 링크를 붙여 넣으면 최종 다운로드 주소를 수집합니다.").pack(anchor="w", pady=(2, 12))

        inputs = self.ui(ttk.LabelFrame, body, text="FuckingFast 파일 URL · 한 줄에 하나씩", padding=10)
        inputs.pack(fill="x")
        self.input = tk.Text(inputs, height=3, wrap="word", font=("Consolas", 10), undo=True)
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", lambda event: self.start())
        self.input.bind("<<Paste>>", self.paste)
        controls = ttk.Frame(inputs)
        controls.pack(fill="x", pady=(8, 0))
        self.ui(ttk.Button, controls, text="클립보드 붙여넣기", command=self.paste).pack(side="left")
        self.browser_var = tk.StringVar(value=next(iter(BROWSERS)))
        self.browser = ttk.Combobox(controls, textvariable=self.browser_var, values=list(BROWSERS),
                                    state="readonly", width=37)
        self.browser.pack(side="left", padx=8)
        self.ui(ttk.Label, controls, text="페이지 대기(초)").pack(side="left")
        self.timeout_var = tk.StringVar(value="180")
        self.timeout = ttk.Spinbox(controls, from_=10, to=900, width=5, textvariable=self.timeout_var)
        self.timeout.pack(side="left", padx=5)
        self.resolve_var = tk.BooleanVar(value=True)
        self.resolve = self.ui(ttk.Checkbutton, inputs, text="최종 다운로드 URL까지 추출 (끄면 FuckingFast 페이지 링크만 수집)",
                                       variable=self.resolve_var)
        self.resolve.pack(anchor="w", pady=(8, 0))
        self.ui(ttk.Label, inputs, text="웹페이지에서 복사한 하이퍼링크도 실제 URL로 자동 변환합니다. Ctrl+V로 붙여넣을 수 있습니다.",
                  foreground="#62676d").pack(anchor="w", pady=(6, 0))
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=10)
        self.start_button = self.ui(ttk.Button, actions, text="추출 시작", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = self.ui(ttk.Button, actions, text="중지", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.skip_button = self.ui(ttk.Button, actions, text="현재 페이지 건너뛰기", command=self.skip.set, state="disabled")
        self.skip_button.pack(side="left")
        self.retry_button = self.ui(ttk.Button, actions, text="실패·중지 항목 재시도", command=self.retry)
        self.retry_button.pack(side="right")
        self.status_var = tk.StringVar(value="URL 입력 후 추출 시작을 누르세요. Ctrl+Enter로도 시작할 수 있습니다.")
        ttk.Label(body, textvariable=self.status_var, wraplength=1000).pack(fill="x", pady=(0, 5))
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))

        panes = ttk.Panedwindow(body, orient="vertical")
        results = self.ui(ttk.LabelFrame, panes, text="추출 결과 · 선택 후 아래에서 상세 내용 확인", padding=6)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(results, columns=("kind", "name", "status", "url"),
                                 show="headings", selectmode="extended", height=5)
        for column, label, width in [("kind", "종류", 120), ("name", "파일 / 항목", 280),
                                      ("status", "상태", 110), ("url", "다운로드 URL / 원본", 480)]:
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=70, stretch=column in {"name", "url"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(results, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("failed", foreground="#a82c2c")
        self.tree.tag_configure("done", foreground="#16734b")
        self.tree.tag_configure("waiting", foreground="#9b610a")
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<Control-c>", self.copy_selected)
        self.root.bind("<Control-Shift-C>", self.copy_direct)
        self.copy_menu = tk.Menu(self.root, tearoff=False)
        self.copy_menu.add_command(label="선택한 다운로드 URL 복사", command=self.copy_selected)
        self.copy_menu.add_command(label="성공 URL 전체 복사", command=self.copy_direct)
        self.tree.bind("<Button-3>", self.show_copy_menu)
        panes.add(results, weight=3)

        notebook = self.notebook = ttk.Notebook(panes)
        self.output = self.text_tab(notebook, "추출 URL", copy_button=True)
        self.details = self.text_tab(notebook, "선택 항목 상세")
        self.logs = self.text_tab(notebook, "진행 로그")
        panes.add(notebook, weight=2)
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x")
        bottom = ttk.Frame(footer)
        bottom.pack(fill="x", pady=(10, 0))
        for label, command in [("성공 URL 전체 복사", self.copy_direct),
                               ("FF 페이지 링크 복사", self.copy_hosts),
                               ("선택 URL 복사", self.copy_selected),
                               ("TXT / JSON 저장", self.save)]:
            self.ui(ttk.Button, bottom, text=label, command=command).pack(side="left", padx=(0, 6))
        self.ui(ttk.Label, footer, text="Ctrl+Shift+C: 성공 URL 전체 복사 · 결과표에서 Ctrl+C 또는 우클릭: 선택 URL 복사",
                  foreground="#62676d").pack(anchor="w", pady=(7, 0))
        self.ui(ttk.Label, footer, text="인증·비밀번호는 열린 브라우저에서 처리하세요. 완료되면 자동으로 이어갑니다. 실제 파일은 다운로드하지 않습니다.",
                  foreground="#62676d", wraplength=1000).pack(anchor="w", pady=(9, 0))
        panes.pack(fill="both", expand=True)

    def text_tab(self, notebook, label, copy_button=False):
        frame = ttk.Frame(notebook)
        row = 1 if copy_button else 0
        frame.rowconfigure(row, weight=1)
        frame.columnconfigure(0, weight=1)
        if copy_button:
            toolbar = ttk.Frame(frame, padding=(6, 5))
            toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
            self.extracted_copy_button = self.ui(ttk.Button, toolbar, text="추출한 링크 복사",
                                                command=self.copy_direct, state="disabled")
            self.extracted_copy_button.pack(side="left")
            self.extracted_count_var = tk.StringVar()
            ttk.Label(toolbar, textvariable=self.extracted_count_var).pack(side="left", padx=10)
        text = tk.Text(frame, wrap="none", font=("Consolas", 9), height=7, state="disabled")
        text.grid(row=row, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        vertical.grid(row=row, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        horizontal.grid(row=row + 1, column=0, sticky="ew")
        text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        notebook.add(frame, text=label)
        self.tabs.append((frame, label))
        return text

    @staticmethod
    def set_text(widget, text, append=False):
        widget.configure(state="normal")
        if not append:
            widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def paste(self, event=None):
        if self.busy():
            return "break"
        html = read_html_clipboard()
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        content = paste_content(text, html)
        if not content:
            self.set_status("클립보드에 텍스트나 하이퍼링크가 없습니다.")
            return "break"
        self.input.edit_separator()
        if event is None:
            self.input.replace("1.0", "end-1c", content)
        else:
            if self.input.tag_ranges("sel"):
                self.input.replace("sel.first", "sel.last", content)
                self.input.tag_remove("sel", "1.0", "end")
            else:
                self.input.insert("insert", content)
        self.input.edit_separator()
        self.input.see("insert")
        self.set_status("붙여넣기 완료 · 하이퍼링크는 실제 URL로 변환됩니다.")
        return "break"

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self, urls=None, reset=True):
        if self.busy():
            return
        try:
            urls = validate_ff_urls(urls or parse_input(self.input.get("1.0", "end")))
            timeout = float(self.timeout_var.get())
            if not 10 <= timeout <= 900:
                raise ValueError(self.tr("페이지 대기 시간은 10~900초로 입력하세요."))
            options = Options(backend="reference", browser=list(BROWSERS.values())[self.browser.current()],
                              resolve_direct=self.resolve_var.get(), timeout=timeout, language=self.language)
        except (ValueError, KeyError) as exc:
            messagebox.showerror(self.tr("입력 확인"), self.tr(str(exc)), parent=self.root)
            return
        if reset:
            self.records.clear()
            self.row_ids.clear()
            self.log_entries.clear()
            self.tree.delete(*self.tree.get_children())
            for widget in (self.output, self.logs, self.details):
                self.set_text(widget, "")
            self.refresh_copy_button()
        self.cancel.clear()
        self.skip.clear()
        self.fatal_error = ""
        self.set_busy(True)
        self.set_status("브라우저를 준비하고 있습니다…")
        self.worker = threading.Thread(target=self.run_worker, args=(urls, options), daemon=True)
        self.worker.start()

    def run_worker(self, urls, options):
        try:
            engine = ExtractionEngine(options, self.events.put, self.cancel, self.skip)
            asyncio.run(engine.run(urls))
        except Exception as exc:
            self.events.put({"type": "error", "message": str(exc)})
        finally:
            self.events.put({"type": "finished"})

    def set_busy(self, busy):
        for widget in (self.start_button, self.retry_button, self.resolve, self.timeout):
            widget.configure(state="disabled" if busy else "normal")
        self.browser.configure(state="disabled" if busy else "readonly")
        self.input.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.skip_button.configure(state="normal" if busy else "disabled")

    def poll(self):
        changed = False
        try:
            while True:
                event = self.events.get_nowait()
                kind = event["type"]
                if kind == "record":
                    record = Record(**event["record"])
                    key = url_key(record.url)
                    self.records[key] = record
                    values = self.row_values(record)
                    if key in self.row_ids:
                        self.tree.item(self.row_ids[key], values=values, tags=(record.status,))
                    else:
                        self.row_ids[key] = self.tree.insert("", "end", values=values, tags=(record.status,))
                    if record.status in {"running", "waiting"}:
                        self.set_status("{status} · {name}", status=STATUS[record.status], name=record.name)
                    changed = True
                elif kind in {"log", "error"}:
                    time = datetime.now().strftime("%H:%M:%S")
                    self.log_entries.append((time, event["message"]))
                    line = f"[{time}] {self.tr(event['message'])}\n"
                    self.set_text(self.logs, line, append=True)
                    if kind == "error":
                        self.fatal_error = event["message"]
                elif kind == "finished":
                    self.set_busy(False)
                    counts = Counter(r.status for r in self.records.values())
                    prefix = "중지됨" if self.cancel.is_set() else "작업 종료"
                    self.set_status("{prefix} · 추출 URL {links}개 · FF 페이지 {pages}개 · 실패 {failed}개 · 건너뜀 {skipped}개",
                                    prefix=prefix, links=len(output_links(self.records.values())),
                                    pages=sum(r.kind == 'ff' for r in self.records.values()),
                                    failed=counts['failed'], skipped=counts['skipped'])
                    if self.fatal_error and not self.closing:
                        messagebox.showerror(self.tr("추출 오류"), self.tr(self.fatal_error), parent=self.root)
        except queue.Empty:
            pass
        if changed:
            records = list(self.records.values())
            self.progress.configure(maximum=max(len(records), 1), value=sum(r.status not in {"queued", "running", "waiting"} for r in records))
            self.set_text(self.output, "\n".join(output_links(records)))
            self.refresh_copy_button()
        if self.closing and not self.busy():
            self.root.destroy()
            return
        self.poll_id = self.root.after(100, self.poll)

    def retry(self):
        urls = [r.url for r in self.records.values() if r.status in {"failed", "cancelled", "skipped"}]
        if urls:
            self.start(urls, reset=False)
        else:
            self.set_status("재시도할 실패·중지·건너뜀 항목이 없습니다.")

    def stop(self):
        self.cancel.set()
        self.set_status("중지 중… 수집된 결과는 보존됩니다.")
        self.stop_button.configure(state="disabled")

    def selected(self):
        selected = set(self.tree.selection())
        return [self.records[key] for key, row in self.row_ids.items() if row in selected]

    def show_details(self, event=None):
        records = self.selected()
        self.set_text(self.details, "\n\n".join(
            self.tr("이름: {name}\n상태: {status}\n원본: {url}\n발견한 페이지: {source}\n최종 다운로드 URL: {direct}\n메시지: {error}",
                    name=r.name, status=self.tr(STATUS[r.status]), url=r.url, source=r.source,
                    direct=r.direct_url, error=self.tr(r.error)) for r in records))

    def copy(self, links):
        if not links:
            self.set_status("복사할 링크가 없습니다.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(links))
        self.set_status("{count}개 URL을 복사했습니다.", count=len(links))

    def copy_direct(self, event=None):
        self.copy(direct_download_links(self.records.values()))
        return "break"

    def copy_hosts(self):
        self.copy(output_links((r for r in self.records.values() if r.kind == "ff"), host_links=True))

    def copy_selected(self, event=None):
        self.copy(direct_download_links(self.selected()))
        return "break"

    def show_copy_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        try:
            self.copy_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.copy_menu.grab_release()

    def save(self):
        if not self.records:
            self.set_status("저장할 결과가 없습니다.")
            return
        path = filedialog.asksaveasfilename(parent=self.root, title=self.tr("TXT / JSON 저장"),
                                          defaultextension=".txt", initialfile="results.txt",
                                          filetypes=[(self.tr("URL 목록"), "*.txt"), (self.tr("상세 결과와 오류"), "*.json")])
        if path:
            try:
                export_records(path, self.records.values(), host_links=not self.resolve_var.get())
                self.set_status("저장 완료: {path}", path=path)
            except OSError as exc:
                messagebox.showerror(self.tr("저장 실패"), str(exc), parent=self.root)

    def close(self):
        if self.busy():
            self.closing = True
            self.stop()
        else:
            self.root.after_cancel(self.poll_id)
            self.root.destroy()


def main(initial_urls=None, language=None):
    root = tk.Tk()
    App(root, initial_urls, language)
    root.mainloop()
