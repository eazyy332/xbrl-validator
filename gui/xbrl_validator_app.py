from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Optional
import sys

# Ensure project root on sys.path for 'src' imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import from correct paths
from src.validation.arelle_runner import run_validation
from src.pipeline import ingest_jsonl
from src.validation.eba_rules import apply_eba_rules
try:
    from xbrl_validator.dpm import list_templates, list_tables_for_template  # type: ignore
    from xbrl_validator.taxonomy_package import list_entry_points, to_zip_entry_syntax  # type: ignore
    from xbrl_validator.config import get_dpm_sqlite_path, get_samples_dir  # type: ignore
except Exception:
    # Fallbacks when optional xbrl_validator package isn't available
    def get_dpm_sqlite_path() -> str:
        return str(Path("assets/dpm.sqlite"))
    def get_samples_dir() -> str:
        return str(Path("samples"))
    def list_templates(_db: str, schema_prefix: str = "dpm35_10", like: str | None = None):  # type: ignore
        return []
    def list_tables_for_template(_db: str, templateid: str, schema_prefix: str = "dpm35_10"):  # type: ignore
        return []
    def list_entry_points(_pkg_zip: str):  # type: ignore
        return []
    def to_zip_entry_syntax(pkg_zip: str, entry_uri: str) -> str:  # type: ignore
        return f"{pkg_zip}#{entry_uri}"


class XbrlValidatorGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        try:
            from xbrl_validator.license import licensed_to_text
            lic = licensed_to_text()
        except Exception:
            lic = ""
        self.title(f"XBRL Validator{(' - ' + lic) if lic else ''}")
        self.geometry("800x600")
        self.instance_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.export_buttons_visible = False

        self._build_widgets()

    def _build_widgets(self) -> None:
        # Use ttk theming for better look
        from tkinter import ttk
        style = ttk.Style()
        style.theme_use('clam')  # Modern theme
        style.configure("TButton", padding=6, relief="flat", background="#ccc")
        style.configure("TLabel", padding=4)
        style.configure("TProgressbar", troughcolor='white', background='#4caf50')

        # Main frame with padding
        main_frame = ttk.Frame(self, padding="20 20 20 20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title label
        title_txt = "XBRL Validator"
        ttk.Label(main_frame, text=title_txt, font=("Arial", 24, "bold")).pack(pady=20)
        self.wm_label = ttk.Label(main_frame, text="", font=("Arial", 10, "italic"), foreground="#C00000")
        self.wm_label.pack(pady=2)

        # License buttons row
        from tkinter import ttk as _ttk
        lic_row = _ttk.Frame(main_frame)
        lic_row.pack(fill=tk.X)
        _ttk.Button(lic_row, text="License…", command=self._open_license_dialog).pack(side=tk.LEFT)
        self.license_status_label = _ttk.Label(lic_row, text="")
        self.license_status_label.pack(side=tk.LEFT, padx=8)

        # Upload button
        upload_btn = ttk.Button(main_frame, text="Upload XBRL File", command=self._upload_and_validate)
        upload_btn.pack(pady=10)

        # Detection label
        self.detected_label_var = tk.StringVar(value="Detected: —")
        ttk.Label(main_frame, textvariable=self.detected_label_var, font=("Arial", 12)).pack(pady=10)

        # Status label
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=self.status_var, font=("Arial", 12, "italic")).pack(pady=10)

        # Progress bar
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100, mode='determinate')
        self.progress.pack(fill=tk.X, pady=10)

        # Results summary frame (hidden initially)
        self.results_frame = ttk.Frame(main_frame)
        self.results_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        ttk.Label(self.results_frame, text="Validation Results", font=("Arial", 16)).pack()
        self.summary_var = tk.StringVar(value="")
        ttk.Label(self.results_frame, textvariable=self.summary_var, font=("Arial", 12)).pack(pady=10)

        # Filters
        filters = ttk.Frame(self.results_frame)
        filters.pack(fill=tk.X, padx=4)
        ttk.Label(filters, text="Severity:").pack(side=tk.LEFT)
        self.filter_sev = tk.StringVar(value="ALL")
        ttk.Combobox(filters, values=["ALL", "ERROR", "WARNING", "INFO", "FATAL"], textvariable=self.filter_sev, width=10).pack(side=tk.LEFT, padx=6)
        ttk.Label(filters, text="Code:").pack(side=tk.LEFT)
        self.filter_code = tk.StringVar(value="")
        ttk.Entry(filters, textvariable=self.filter_code, width=16).pack(side=tk.LEFT, padx=6)
        ttk.Label(filters, text="Contains:").pack(side=tk.LEFT)
        self.filter_q = tk.StringVar(value="")
        ttk.Entry(filters, textvariable=self.filter_q, width=30).pack(side=tk.LEFT, padx=6)
        ttk.Button(filters, text="Apply", command=self._apply_filters).pack(side=tk.LEFT, padx=6)

        # Split pane: left (group tree), right (messages)
        content = ttk.Frame(self.results_frame)
        content.pack(fill=tk.BOTH, expand=True)
        left_panel = ttk.Frame(content)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=4)
        right_panel = ttk.Frame(content)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Left: group tree (Table -> Severity)
        self.group_tree = ttk.Treeview(left_panel, columns=("count",), show="tree headings", height=18)
        self.group_tree.heading("count", text="#")
        self.group_tree.column("count", width=48, anchor="e")
        self.group_tree.pack(fill=tk.Y, expand=False)
        self.group_tree.bind("<<TreeviewSelect>>", self._on_group_select)

        # Right: Messages list
        cols = ("level", "code", "message", "table", "cell")
        self.msg_tree = ttk.Treeview(right_panel, columns=cols, show="headings")
        self.msg_tree.heading("level", text="Level")
        self.msg_tree.heading("code", text="Code")
        self.msg_tree.heading("message", text="Message")
        self.msg_tree.heading("table", text="Table")
        self.msg_tree.heading("cell", text="Cell")
        self.msg_tree.column("level", width=80, anchor="w")
        self.msg_tree.column("code", width=200, anchor="w")
        self.msg_tree.column("message", width=500, anchor="w")
        self.msg_tree.column("table", width=160, anchor="w")
        self.msg_tree.column("cell", width=120, anchor="w")
        self.msg_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=8)
        self.msg_tree.bind("<Double-1>", self._on_msg_open)

        # Per-table grouping panel
        grp = ttk.Frame(right_panel)
        grp.pack(fill=tk.X, padx=4, pady=6)
        ttk.Label(grp, text="Per-table counts:").pack(side=tk.LEFT)
        self.table_counts_var = tk.StringVar(value="")
        self.table_counts_lbl = ttk.Label(grp, textvariable=self.table_counts_var, font=("Arial", 10))
        self.table_counts_lbl.pack(side=tk.LEFT, padx=10)

        # Download buttons frame (hidden initially)
        self.download_frame = ttk.Frame(right_panel)
        self.download_frame.pack(pady=10)
        self.btn_csv = ttk.Button(self.download_frame, text="Download CSV", command=self._download_csv)
        self.btn_csv.pack(side=tk.LEFT, padx=5)
        self.btn_json = ttk.Button(self.download_frame, text="Download JSON", command=self._download_json)
        self.btn_json.pack(side=tk.LEFT, padx=5)
        self.btn_excel = ttk.Button(self.download_frame, text="Download Excel", command=self._download_excel)
        self.btn_excel.pack(side=tk.LEFT, padx=5)
        self.btn_pdf = ttk.Button(self.download_frame, text="Download PDF", command=self._download_pdf)
        self.btn_pdf.pack(side=tk.LEFT, padx=5)
        self.btn_bundle = ttk.Button(self.download_frame, text="Export Bundle (.zip)", command=self._export_bundle)
        self.btn_bundle.pack(side=tk.LEFT, padx=5)
        self.results_frame.pack_forget()
        self.download_frame.pack_forget()

        self._msgs: list[dict] = []  # normalized messages from JSONL ingest
        self._filter_table: str | None = None
        self._refresh_license_ui()

    def _upload_and_validate(self) -> None:
        path = filedialog.askopenfilename(title="Select XBRL File", filetypes=[("XBRL Files", "*.xbrl *.xml")])
        if not path:
            return
        self.instance_var.set(path)
        self.status_var.set("Detecting...")
        self.progress_var.set(0)
        threading.Thread(target=self._validate_worker, args=(path,), daemon=True).start()

    def _validate_worker(self, path: str) -> None:
        try:
            from app.validate import _detect_eba_from_instance
            ver, fw = _detect_eba_from_instance(path)
            label = f"Detected: {(fw or '?').upper()} {ver or ''}".strip() if (ver or fw) else "Detected: —"
            self.detected_label_var.set(label)
            
            # Step 1: Prime cache first to ensure EBA formulas work
            self.status_var.set("Priming cache...")
            self.progress_var.set(10)
            
            from pathlib import Path as _P
            import subprocess, sys

            # Prefer project venv311 interpreter if available for Arelle compatibility
            _venv_py = (Path(__file__).resolve().parent.parent / ".venv311/bin/python")
            _py = str(_venv_py) if _venv_py.exists() else sys.executable
            
            # Prime cache if helper is available (optional)
            try:
                cache_cmd = [_py, "-m", "scripts.cache_prime"]
                cache_result = subprocess.run(cache_cmd, capture_output=True, text=True, check=False)
                if cache_result.returncode != 0:
                    print(f"[warn] cache priming failed: {cache_result.stderr}")
            except Exception:
                pass
            
            self.progress_var.set(20)
            self.status_var.set("Validating...")
            
            # Step 2: Run validation with offline mode (now cache is primed)
            logp = _P("assets/logs/gui_run.jsonl")
            exp_dir = "exports"
            cmd = [
                _py, "-m", "app.validate",
                "--file", path,
                "--ebaVersion", ver or "3.5",
                "--out", str(logp),
                "--plugins", "formula",
                "--offline",
                "--cacheDir", "assets/cache",
                "--exports", exp_dir
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.progress_var.set(60)
            if result.returncode != 0:
                # Fallback: run in-process validation to avoid dependency on app.validate
                try:
                    # Resolve taxonomy packages from config if available
                    tax_paths: list[str] = []
                    try:
                        import json as _json
                        cfgp = Path("config/taxonomy.json")
                        if cfgp.exists() and (ver or ""):
                            data = _json.loads(cfgp.read_text(encoding="utf-8"))
                            key = "eba_3_4" if str(ver) == "3.4" else "eba_3_5"
                            tax_paths = [str(p) for p in (data.get("stacks", {}).get(key, []) or [])]
                    except Exception:
                        tax_paths = []
                    summary = run_validation(
                        input_path=path,
                        taxonomy_paths=tax_paths,
                        plugins=["formula"],
                        log_jsonl_path=str(logp),
                        validate=True,
                        offline=False,
                        cache_dir=str(Path("assets/cache")),
                        extra_args=["--calcDecimals"],
                        use_subprocess=False,
                    )
                    if int(summary.get("returnCode", 0)) != 0:
                        self.status_var.set("Validation failed")
                        messagebox.showerror("Error", f"Validation returned {summary.get('returnCode')}")
                        return
                except Exception as _e:
                    self.status_var.set("Validation failed")
                    messagebox.showerror("Error", f"Validation failed: {_e}")
                    return

            # Ingest results
            from src.pipeline import ingest_jsonl
            msgs, _, _ = ingest_jsonl(str(logp), dpm_sqlite=get_dpm_sqlite_path(), dpm_schema="dpm35_10", model_xbrl_path=path)
            self.progress_var.set(80)

            # Summary
            errors = sum(1 for m in msgs if (m.get("level") or "").upper() in ("ERROR", "FATAL"))
            warnings = sum(1 for m in msgs if (m.get("level") or "").upper() == "WARNING")
            summary = f"Validation complete: {errors} errors, {warnings} warnings, {len(msgs)} total messages"
            self.summary_var.set(summary)

            # Populate messages list
            self._msgs = msgs
            self._refresh_msgs()

            self.progress_var.set(100)
            self.status_var.set("Complete")
            self.results_frame.pack(fill=tk.BOTH, expand=True)
            self.download_frame.pack()
            self.export_buttons_visible = True
        except Exception as e:
            self.status_var.set("Error")
            messagebox.showerror("Error", str(e))

    def _download_csv(self) -> None:
        self._download_report("exports/validation_messages.csv", "CSV")

    def _download_json(self) -> None:
        self._download_report("exports/results_by_file.json", "JSON")

    def _download_excel(self) -> None:
        self._download_report("exports/validation_report.xlsx", "Excel")

    def _download_pdf(self) -> None:
        self._download_report("exports/validation_report.pdf", "PDF")

    def _download_report(self, default_path: str, filetype: str) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(title=f"Save {filetype}", defaultextension=f".{filetype.lower()}", filetypes=[(filetype, f"*.{filetype.lower()}")])
        if not path:
            return
        import shutil
        try:
            shutil.copy(default_path, path)
            messagebox.showinfo("Download", f"{filetype} saved to {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def _export_bundle(self) -> None:
        # Zip export artifacts in exports/ for the last run
        from tkinter import filedialog
        exp_dir = Path("exports")
        if not exp_dir.exists():
            messagebox.showerror("Export", "No exports directory found")
            return
        out = filedialog.asksaveasfilename(title="Save bundle", defaultextension=".zip", filetypes=[("ZIP", "*.zip")])
        if not out:
            return
        try:
            import zipfile
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for p in exp_dir.rglob("*"):
                    if p.is_file():
                        zf.write(p, p.relative_to(exp_dir))
            messagebox.showinfo("Export", f"Bundle saved to {out}")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def _apply_filters(self) -> None:
        self._refresh_msgs()

    def _refresh_msgs(self) -> None:
        # Clear
        for i in self.msg_tree.get_children():
            self.msg_tree.delete(i)
        sev = (self.filter_sev.get() or "ALL").upper()
        q = (self.filter_q.get() or "").strip().lower()
        per_table: dict[str, dict[str, int]] = {}
        for idx, m in enumerate(self._msgs):
            lvl = (m.get("level") or "").upper()
            if sev != "ALL" and lvl != sev:
                continue
            # Code filter (exact match or substring)
            codef = (self.filter_code.get() or "").strip().lower()
            codev = (m.get('code') or '').strip().lower()
            if codef and codef not in codev:
                continue
            blob = f"{m.get('code','')} {m.get('message','')}".lower()
            if q and q not in blob:
                continue
            mc = m.get("mappedCell") or {}
            table = mc.get("table_id") or (m.get("dpm_table") or "")
            if self._filter_table and table and self._filter_table != table:
                continue
            cell = mc.get("cell_id") or (m.get("dpm_cell") or "")
            msg_short = (m.get("message") or "").replace("\n", " ")
            if len(msg_short) > 160:
                msg_short = msg_short[:157] + "..."
            self.msg_tree.insert("", "end", iid=str(idx), values=(lvl, m.get("code") or "", msg_short, table, cell))
            # accumulate per-table counts
            if table:
                d = per_table.setdefault(table, {"ERROR": 0, "WARNING": 0, "INFO": 0, "FATAL": 0})
                d[lvl] = d.get(lvl, 0) + 1

        # Update per-table summary string (top 8 tables by ERROR then WARNING)
        def sort_key(item: tuple[str, dict[str, int]]):
            k, v = item
            return (-(v.get("ERROR", 0) + v.get("FATAL", 0)), -v.get("WARNING", 0), k)
        items = sorted(per_table.items(), key=sort_key)[:8]
        parts: list[str] = []
        for t, v in items:
            parts.append(f"{t}: E{v.get('ERROR',0)+v.get('FATAL',0)}/W{v.get('WARNING',0)}")
        self.table_counts_var.set("  |  ".join(parts))

        # Rebuild group tree
        for i in self.group_tree.get_children():
            self.group_tree.delete(i)
        for t, v in sorted(per_table.items(), key=lambda kv: -(kv[1].get("ERROR", 0) + kv[1].get("FATAL", 0))):
            parent = self.group_tree.insert("", "end", iid=f"table:{t}", text=t, values=(sum(v.values()),))
            for lvl in ("ERROR", "WARNING", "INFO", "FATAL"):
                cnt = v.get(lvl, 0)
                if cnt:
                    self.group_tree.insert(parent, "end", iid=f"sev:{t}:{lvl}", text=lvl, values=(cnt,))

    def _on_msg_open(self, _evt=None) -> None:
        sel = self.msg_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except Exception:
            return
        if idx < 0 or idx >= len(self._msgs):
            return
        m = self._msgs[idx]
        self._open_msg_details(m)

    def _on_group_select(self, _evt=None) -> None:
        sel = self.group_tree.selection()
        if not sel:
            return
        node = sel[0]
        if node.startswith("sev:"):
            _p, table, lvl = node.split(":", 2)
            self._filter_table = table
            self.filter_sev.set(lvl)
        elif node.startswith("table:"):
            _p, table = node.split(":", 1)
            self._filter_table = table
            self.filter_sev.set("ALL")
        self._refresh_msgs()

    def _open_msg_details(self, m: dict) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(m.get("code") or "Message")
        dlg.geometry("900x500")
        from tkinter import ttk
        top = ttk.Frame(dlg)
        top.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        txt = tk.Text(top, wrap="word")
        details = []
        details.append(f"Level: {(m.get('level') or '').upper()}")
        details.append(f"Code: {m.get('code') or ''}")
        details.append(f"File: {m.get('docUri') or ''}")
        details.append(f"Line: {m.get('line') or ''} Col: {m.get('col') or ''}")
        details.append("")
        details.append(m.get("message") or "")
        details.append("")
        mc = m.get("mappedCell") or {}
        if mc:
            details.append(f"Table: {mc.get('table_id') or ''}")
            details.append(f"Cell: {mc.get('cell_id') or ''}")
            details.append(f"Template: {mc.get('template_id') or ''}")
            axes = mc.get("axes") or {}
            if axes:
                details.append("Axes:")
                for ax, mem in axes.items():
                    details.append(f"  {ax} = {mem}")
        txt.insert("1.0", "\n".join(details))
        txt.configure(state="disabled")
        txt.pack(fill=tk.BOTH, expand=True)
        # Buttons row
        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=8, pady=4)
        def do_copy():
            try:
                self.clipboard_clear()
                self.clipboard_append("\n".join(details))
            except Exception:
                pass
        def do_open():
            import webbrowser
            uri = m.get("docUri") or ""
            if uri:
                try:
                    webbrowser.open(uri)
                except Exception:
                    messagebox.showerror("Open", f"Failed to open: {uri}")
        ttk.Button(btns, text="Copy", command=do_copy).pack(side=tk.LEFT)
        ttk.Button(btns, text="Open docUri", command=do_open).pack(side=tk.LEFT, padx=6)

    def _open_license_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("License")
        dlg.geometry("560x280")
        from tkinter import ttk as _ttk
        frm = _ttk.Frame(dlg, padding="12 12 12 12")
        frm.pack(fill=tk.BOTH, expand=True)
        # Current status
        try:
            from xbrl_validator.license import get_license_status, set_license_path
            st = get_license_status()
            status = f"State: {st.state}  Edition: {st.edition or ''}  Expires: {st.expires or ''}"
        except Exception as e:
            status = f"Error reading license: {e}"
            set_license_path = None  # type: ignore
        _ttk.Label(frm, text=status).pack(anchor=tk.W)
        # Picker
        path_var = tk.StringVar()
        def browse():
            p = filedialog.askopenfilename(title="Select license.json", filetypes=[("JSON", "*.json")])
            if not p:
                return
            path_var.set(p)
        row = _ttk.Frame(frm)
        row.pack(fill=tk.X, pady=8)
        _ttk.Entry(row, textvariable=path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        _ttk.Button(row, text="Browse", command=browse).pack(side=tk.LEFT, padx=6)
        def apply():
            p = path_var.get().strip()
            if not p:
                return
            try:
                if set_license_path:
                    set_license_path(p)
                self._refresh_license_ui()
                messagebox.showinfo("License", "License path saved and applied.")
            except Exception as e:
                messagebox.showerror("License", str(e))
        btns = _ttk.Frame(frm)
        btns.pack(fill=tk.X)
        _ttk.Button(btns, text="Apply", command=apply).pack(side=tk.RIGHT)

    def _refresh_license_ui(self) -> None:
        try:
            from xbrl_validator.license import licensed_to_text, watermark_text, feature_enabled
            lic = licensed_to_text()
            wm = watermark_text()
        except Exception:
            lic = ""
            wm = None
            def feature_enabled(_n: str) -> bool:
                return True
        # Title and watermark
        self.title(f"XBRL Validator{(' - ' + lic) if lic else ''}")
        self.wm_label.configure(text=(wm or ""))
        # Feature gating for reports
        try:
            if hasattr(self, 'btn_excel'):
                self.btn_excel.state(["!disabled"] if feature_enabled("reports-excel") else ["disabled"])
            if hasattr(self, 'btn_pdf'):
                self.btn_pdf.state(["!disabled"] if feature_enabled("reports-pdf") else ["disabled"])
        except Exception:
            pass
        # Status text
        try:
            if hasattr(self, 'license_status_label'):
                self.license_status_label.configure(text=lic)
        except Exception:
            pass

    # Retain DPM Browser as optional
    def _open_dpm_browser(self) -> None:
        # Simple DPM browser: search templates, list tables
        dlg = tk.Toplevel(self)
        dlg.title("DPM Browser")
        dlg.geometry("900x600")
        from tkinter import ttk
        top = tk.Frame(dlg)
        top.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(top, text="Search template:").pack(side=tk.LEFT)
        q = tk.StringVar()
        tk.Entry(top, textvariable=q, width=40).pack(side=tk.LEFT, padx=6)
        schema = tk.StringVar(value="dpm35_10")
        tk.Label(top, text="Schema:").pack(side=tk.LEFT, padx=6)
        ttk.Combobox(top, values=["dpm35_10", "dpm35_20"], textvariable=schema, width=10).pack(side=tk.LEFT)
        out = tk.Frame(dlg)
        out.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        left = tk.Frame(out)
        right = tk.Frame(out)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tmpl_tree = ttk.Treeview(left, columns=("id", "code", "label"), show="headings")
        for c in ("id", "code", "label"):
            tmpl_tree.heading(c, text=c.title())
            tmpl_tree.column(c, width=200 if c != "label" else 300, anchor="w")
        tmpl_tree.pack(fill=tk.BOTH, expand=True)
        tbl_tree = ttk.Treeview(right, columns=("id", "code", "label"), show="headings")
        for c in ("id", "code", "label"):
            tbl_tree.heading(c, text=c.title())
            tbl_tree.column(c, width=200 if c != "label" else 300, anchor="w")
        tbl_tree.pack(fill=tk.BOTH, expand=True)

        def do_search() -> None:
            for i in tmpl_tree.get_children():
                tmpl_tree.delete(i)
            try:
                templates = list_templates("/Users/omarfrix/Desktop/untitled folder 12/assets/dpm.sqlite", schema_prefix=schema.get(), like=q.get().strip() or None)
            except Exception as e:
                messagebox.showerror("DPM", f"Query failed: {e}")
                return
            for t in templates:
                tmpl_tree.insert("", "end", iid=t.templateid, values=(t.templateid, t.templatecode, t.templatelabel))

        def on_template_select(_evt=None) -> None:
            sel = tmpl_tree.selection()
            if not sel:
                return
            templateid = sel[0]
            for i in tbl_tree.get_children():
                tbl_tree.delete(i)
            try:
                tables = list_tables_for_template("/Users/omarfrix/Desktop/untitled folder 12/assets/dpm.sqlite", templateid=templateid, schema_prefix=schema.get())
            except Exception as e:
                messagebox.showerror("DPM", f"Query failed: {e}")
                return
            for t in tables:
                tbl_tree.insert("", "end", iid=t.tableid, values=(t.tableid, t.originaltablecode, t.originaltablelabel))

        def on_use_template() -> None:
            # Pre-fill packages with discovered entry using taxonomy package and template code heuristic
            sel = tmpl_tree.selection()
            if not sel:
                messagebox.showerror("DPM", "Select a template first")
                return
            tcode = tmpl_tree.set(sel[0], column="code")
            # Try entry discovery and simple heuristic mapping
            pkg = self.packages_var.get().strip()
            if not pkg or "#" in pkg:
                messagebox.showinfo("DPM", "Provide a taxonomy package zip (not zip#entry) in Packages, then try again.")
                return
            eps = list_entry_points(pkg)
            if not eps:
                messagebox.showerror("DPM", "No entry points found in taxonomyPackage.xml.")
                return
            # Simple match by containing template code
            from xbrl_validator.dpm import find_entry_for_template_in_package
            match = find_entry_for_template_in_package(pkg, tcode, eps)
            if not match:
                messagebox.showinfo("DPM", "No matching entry found for this template code. You can still discover and choose manually.")
                return
            label, entry_uri = match
            resolved = to_zip_entry_syntax(pkg, entry_uri)
            self.packages_var.set(resolved)
            messagebox.showinfo("DPM", f"Entry selected\n{label}\n{resolved}")

        btns = tk.Frame(dlg)
        btns.pack(fill=tk.X, padx=8, pady=4)
        tk.Button(btns, text="Search", command=do_search).pack(side=tk.LEFT)
        tk.Button(btns, text="Use template", command=on_use_template).pack(side=tk.LEFT, padx=6)
        tmpl_tree.bind("<<TreeviewSelect>>", on_template_select)


if __name__ == "__main__":
    app = XbrlValidatorGui()
    app.mainloop()

