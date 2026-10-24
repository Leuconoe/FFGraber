"""Korean desktop UI. Only the Tk main thread ever touches widgets."""

import asyncio
from collections import Counter
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .engine import ExtractionEngine, Options
from .links import parse_input, url_key
from .models import Record, direct_download_links, export_records, output_links
from .reference import validate_ff_urls

STATUS = {"queued": "대기", "running": "추출 중", "waiting": "브라우저 확인",
          "scanned": "목록 확인", "found": "FF 링크 발견", "done": "완료",
          "failed": "실패", "cancelled": "중지", "skipped": "건너뜀"}
KINDS = {"page": "웹 페이지", "paste": "링크 목록", "filecrypt": "Filecrypt",
         "filecrypt-link": "Filecrypt 개별", "ff": "FuckingFast", "direct": "직접 URL"}
BROWSERS = {"자동 선택 (Chrome → Edge)": "auto", "Google Chrome": "chrome",
            "Microsoft Edge": "msedge"}


class App:
    def __init__(self, root, initial_urls=None):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.skip = threading.Event()
        self.records = {}
        self.row_ids = {}
        self.worker = None
        self.closing = False
        self.fatal_error = ""
        root.title(f"FFGraber {__version__} · 브라우저 링크 추출기")
        root.geometry("1120x840")
        root.minsize(880, 680)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        if initial_urls:
            self.input.insert("1.0", "\n".join(initial_urls))
        self.poll_id = root.after(100, self.poll)

    def build(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=28)
        style.configure("Title.TLabel", font=("맑은 고딕", 21, "bold"))
        body = ttk.Frame(self.root, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="FFGraber", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="FuckingFast 파일 링크를 붙여 넣으면 최종 다운로드 주소를 수집합니다.").pack(anchor="w", pady=(2, 12))

        inputs = ttk.LabelFrame(body, text="FuckingFast 파일 URL · 한 줄에 하나씩", padding=10)
        inputs.pack(fill="x")
        self.input = tk.Text(inputs, height=3, wrap="word", font=("Consolas", 10), undo=True)
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", lambda event: self.start())
        controls = ttk.Frame(inputs)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="클립보드 붙여넣기", command=self.paste).pack(side="left")
        self.browser_var = tk.StringVar(value=next(iter(BROWSERS)))
        self.browser = ttk.Combobox(controls, textvariable=self.browser_var, values=list(BROWSERS),
                                    state="readonly", width=37)
        self.browser.pack(side="left", padx=8)
        ttk.Label(controls, text="페이지 대기(초)").pack(side="left")
        self.timeout_var = tk.StringVar(value="180")
        self.timeout = ttk.Spinbox(controls, from_=10, to=900, width=5, textvariable=self.timeout_var)
        self.timeout.pack(side="left", padx=5)
        self.resolve_var = tk.BooleanVar(value=True)
        self.resolve = ttk.Checkbutton(inputs, text="최종 다운로드 URL까지 추출 (끄면 FuckingFast 페이지 링크만 수집)",
                                       variable=self.resolve_var)
        self.resolve.pack(anchor="w", pady=(8, 0))
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=10)
        self.start_button = ttk.Button(actions, text="추출 시작", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="중지", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.skip_button = ttk.Button(actions, text="현재 페이지 건너뛰기", command=self.skip.set, state="disabled")
        self.skip_button.pack(side="left")
        self.retry_button = ttk.Button(actions, text="실패·중지 항목 재시도", command=self.retry)
        self.retry_button.pack(side="right")
        self.status_var = tk.StringVar(value="URL 입력 후 추출 시작을 누르세요. Ctrl+Enter로도 시작할 수 있습니다.")
        ttk.Label(body, textvariable=self.status_var, wraplength=1000).pack(fill="x", pady=(0, 5))
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))

        panes = ttk.Panedwindow(body, orient="vertical")
        panes.pack(fill="both", expand=True)
        results = ttk.LabelFrame(panes, text="추출 결과 · 선택 후 아래에서 상세 내용 확인", padding=6)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(results, columns=("kind", "name", "status", "url"), show="headings", selectmode="extended")
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

        notebook = ttk.Notebook(panes)
        self.output = self.text_tab(notebook, "추출 URL")
        self.details = self.text_tab(notebook, "선택 항목 상세")
        self.logs = self.text_tab(notebook, "진행 로그")
        panes.add(notebook, weight=2)
        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(10, 0))
        for label, command in [("성공 URL 전체 복사", self.copy_direct),
                               ("FF 페이지 링크 복사", self.copy_hosts),
                               ("선택 URL 복사", self.copy_selected),
                               ("TXT / JSON 저장", self.save)]:
            ttk.Button(bottom, text=label, command=command).pack(side="left", padx=(0, 6))
        ttk.Label(body, text="Ctrl+Shift+C: 성공 URL 전체 복사 · 결과표에서 Ctrl+C 또는 우클릭: 선택 URL 복사",
                  foreground="#62676d").pack(anchor="w", pady=(7, 0))
        ttk.Label(body, text="인증·비밀번호는 열린 브라우저에서 처리하세요. 완료되면 자동으로 이어갑니다. 실제 파일은 다운로드하지 않습니다.",
                  foreground="#62676d", wraplength=1000).pack(anchor="w", pady=(9, 0))

    def text_tab(self, notebook, label):
        frame = ttk.Frame(notebook)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, wrap="none", font=("Consolas", 9), height=7, state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        notebook.add(frame, text=label)
        return text

    @staticmethod
    def set_text(widget, text, append=False):
        widget.configure(state="normal")
        if not append:
            widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def paste(self):
        if self.busy():
            return
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.status_var.set("클립보드에 텍스트가 없습니다.")
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self, urls=None, reset=True):
        if self.busy():
            return
        try:
            urls = validate_ff_urls(urls or parse_input(self.input.get("1.0", "end")))
            timeout = float(self.timeout_var.get())
            if not 10 <= timeout <= 900:
                raise ValueError("페이지 대기 시간은 10~900초로 입력하세요.")
            options = Options(backend="reference", browser=BROWSERS[self.browser_var.get()],
                              resolve_direct=self.resolve_var.get(), timeout=timeout)
        except (ValueError, KeyError) as exc:
            messagebox.showerror("입력 확인", str(exc), parent=self.root)
            return
        if reset:
            self.records.clear()
            self.row_ids.clear()
            self.tree.delete(*self.tree.get_children())
            for widget in (self.output, self.logs, self.details):
                self.set_text(widget, "")
        self.cancel.clear()
        self.skip.clear()
        self.fatal_error = ""
        self.set_busy(True)
        self.status_var.set("브라우저를 준비하고 있습니다…")
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
                    values = (KINDS[record.kind], record.name, STATUS[record.status], record.direct_url or record.resolved_url or record.url)
                    if key in self.row_ids:
                        self.tree.item(self.row_ids[key], values=values, tags=(record.status,))
                    else:
                        self.row_ids[key] = self.tree.insert("", "end", values=values, tags=(record.status,))
                    if record.status in {"running", "waiting"}:
                        self.status_var.set(f"{STATUS[record.status]} · {record.name}")
                    changed = True
                elif kind in {"log", "error"}:
                    line = f"[{datetime.now():%H:%M:%S}] {event['message']}\n"
                    self.set_text(self.logs, line, append=True)
                    if kind == "error":
                        self.fatal_error = event["message"]
                elif kind == "finished":
                    self.set_busy(False)
                    counts = Counter(r.status for r in self.records.values())
                    prefix = "중지됨" if self.cancel.is_set() else "작업 종료"
                    self.status_var.set(f"{prefix} · 추출 URL {len(output_links(self.records.values()))}개 · "
                                        f"FF 페이지 {sum(r.kind == 'ff' for r in self.records.values())}개 · "
                                        f"실패 {counts['failed']}개 · 건너뜀 {counts['skipped']}개")
                    if self.fatal_error and not self.closing:
                        messagebox.showerror("추출 오류", self.fatal_error, parent=self.root)
        except queue.Empty:
            pass
        if changed:
            records = list(self.records.values())
            self.progress.configure(maximum=max(len(records), 1), value=sum(r.status not in {"queued", "running", "waiting"} for r in records))
            self.set_text(self.output, "\n".join(output_links(records)))
        if self.closing and not self.busy():
            self.root.destroy()
            return
        self.poll_id = self.root.after(100, self.poll)

    def retry(self):
        urls = [r.url for r in self.records.values() if r.status in {"failed", "cancelled", "skipped"}]
        if urls:
            self.start(urls, reset=False)
        else:
            self.status_var.set("재시도할 실패·중지·건너뜀 항목이 없습니다.")

    def stop(self):
        self.cancel.set()
        self.status_var.set("중지 중… 수집된 결과는 보존됩니다.")
        self.stop_button.configure(state="disabled")

    def selected(self):
        selected = set(self.tree.selection())
        return [self.records[key] for key, row in self.row_ids.items() if row in selected]

    def show_details(self, event=None):
        records = self.selected()
        self.set_text(self.details, "\n\n".join(
            f"이름: {r.name}\n상태: {STATUS[r.status]}\n원본: {r.url}\n발견한 페이지: {r.source}\n"
            f"최종 다운로드 URL: {r.direct_url}\n메시지: {r.error}" for r in records))

    def copy(self, links):
        if not links:
            self.status_var.set("복사할 링크가 없습니다.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(links))
        self.status_var.set(f"{len(links)}개 URL을 복사했습니다.")

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
            self.status_var.set("저장할 결과가 없습니다.")
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".txt", initialfile="results.txt",
                                          filetypes=[("URL 목록", "*.txt"), ("상세 결과와 오류", "*.json")])
        if path:
            try:
                export_records(path, self.records.values(), host_links=not self.resolve_var.get())
                self.status_var.set(f"저장 완료: {path}")
            except OSError as exc:
                messagebox.showerror("저장 실패", str(exc), parent=self.root)

    def close(self):
        if self.busy():
            self.closing = True
            self.stop()
        else:
            self.root.after_cancel(self.poll_id)
            self.root.destroy()


def main(initial_urls=None):
    root = tk.Tk()
    App(root, initial_urls)
    root.mainloop()
