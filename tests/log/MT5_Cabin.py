import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime
import html


APP_TITLE = "MT5 Cabin 0.1"


class CabinError(Exception):
    pass


def read_text_auto(path: Path) -> str:
    """Read MQL5 files with BOM/encoding detection."""
    raw = path.read_bytes()

    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16")


def atomic_write_json(path: Path, data: dict):
    """Write compact JSON atomically without touching Gateway temp files."""
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_name(path.name + ".cabin.tmp")
    content = json.dumps(
        data,
        ensure_ascii=True,
        separators=(",", ":")
    )

    with open(temp_path, "w", encoding="ascii", newline="") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())

    os.replace(temp_path, path)


def load_env():
    env_path = Path(__file__).resolve().parent / ".env"

    if not env_path.is_file():
        raise CabinError(f".env file not found:\n{env_path}")

    values = {}

    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        values[key] = value

    root_value = values.get("MT5_GATEWAY_ROOT", "").strip()

    if not root_value:
        raise CabinError("MT5_GATEWAY_ROOT is missing in .env")

    root = Path(root_value).expanduser()

    if not root.is_absolute():
        raise CabinError("MT5_GATEWAY_ROOT must be an absolute path.")

    return root.resolve()


class MT5Cabin:

    def __init__(self, root: Path):
        self.root = root

        self.feed_file = root / "mt5_feed.json"
        self.gateway_dir = root / "Gateway"

        self.commands_file = (
            self.gateway_dir / "commands" / "commands.json"
        )

        self.control_file = (
            self.gateway_dir / "control" / "control.json"
        )

        self.temp_dir = self.gateway_dir / "temp"
        self.state_file = self.temp_dir / "current_state.txt"
        self.request_file = self.temp_dir / "current_request.json"

        self.received_dir = self.gateway_dir / "received"

        self.root_validated = False

        self.window = tk.Tk()
        self.window.title(APP_TITLE)
        self.window.geometry("1050x760")
        self.window.minsize(800, 600)

        self.build_ui()
        self.validate_root()
        self.refresh()
        

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def build_ui(self):

        
        self.main_frame = ttk.Frame(self.window, padding=12)
        main = self.main_frame
        self.viewer_maximized = False
        self.editor_maximized = False
        
        self.normal_layout = None
        
        main.pack(fill="both", expand=True)

        ttk.Label(
            main,
            text=APP_TITLE,
            font=("Arial", 17, "bold")
        ).pack(anchor="w")

        ttk.Label(
            main,
            text=f"Gateway Root: {self.root}",
            wraplength=950
        ).pack(anchor="w", pady=(8, 12))

        status_frame = ttk.LabelFrame(
            main,
            text="Gateway Status",
            padding=10
        )
        status_frame.pack(fill="x", pady=5)

        self.state_var = tk.StringVar(value="UNKNOWN")
        self.request_var = tk.StringVar(value="None")
        self.status_var = tk.StringVar(value="Checking...")

        ttk.Label(
            status_frame,
            text="State:"
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            status_frame,
            textvariable=self.state_var,
            font=("Arial", 11, "bold")
        ).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(
            status_frame,
            text="Request ID:"
        ).grid(row=1, column=0, sticky="w")

        ttk.Label(
            status_frame,
            textvariable=self.request_var
        ).grid(row=1, column=1, sticky="w", padx=8)

        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            wraplength=900
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 0)
        )

        self.editor_frame = ttk.LabelFrame(
            main,
            text="Command JSON Editor",
            padding=8
        )
        self.editor_frame.pack(fill="both", expand=True, pady=8)

        editor_toolbar = ttk.Frame(self.editor_frame)
        editor_toolbar.pack(fill="x", pady=(0, 6))

        self.editor_toggle_button = ttk.Button(
            editor_toolbar,
            text="Maximize",
            command=self.toggle_editor
        )
        self.editor_toggle_button.pack(side="right", padx=3)
        
        self.editor = tk.Text(
            self.editor_frame,
            height=9,
            font=("Consolas", 10),
            wrap="none"
        )
        self.editor.pack(fill="both", expand=True)

        self.editor.insert(
            "1.0",
            json.dumps(
                {
                    "commands": [
                        {
                            "command": "LIST-TABL",
                            "status": ""
                        }
                    ]
                },
                indent=4
            )
        )

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=5)

        

        ttk.Button(
            buttons,
            text="SEND COMMAND",
            command=self.send_command
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="CANCEL",
            command=self.cancel_request
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Refresh",
            command=lambda: self.refresh(show_message=True)
        ).pack(side="right", padx=3)

        self.viewer_frame = ttk.LabelFrame(
            main,
            text="JSON Viewer",
            padding=8
        )
        
        self.viewer_frame.pack(fill="both", expand=True, pady=8)

        viewer_toolbar = ttk.Frame(self.viewer_frame)
        viewer_toolbar.pack(fill="x", pady=(0, 6))

        self.viewer_path_var = tk.StringVar(value="")
        self.viewer_is_latest = True
        self.viewer_mode = "json"
        self.viewer_current_data = None

        self.viewer_path_entry = ttk.Entry(
            viewer_toolbar,
            textvariable=self.viewer_path_var,
            state="readonly"
        )
        self.viewer_path_entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 5)
        )

        ttk.Button(
            viewer_toolbar,
            text="Browse",
            command=self.browse_json_file
        ).pack(side="left", padx=3)

        ttk.Button(
            viewer_toolbar,
            text="Open",
            command=self.open_json_file
        ).pack(side="left", padx=3)
        
        self.viewer_json_button = ttk.Button(
            viewer_toolbar,
            text="JSON",
            command=self.show_json_view
        )
        self.viewer_json_button.pack(side="left", padx=3)

        self.viewer_answer_button = ttk.Button(
            viewer_toolbar,
            text="Answer",
            command=self.show_answer_view,
            state="disabled"
        )
        self.viewer_answer_button.pack(side="left", padx=3)
        
        self.viewer_toggle_button = ttk.Button(
            viewer_toolbar,
            text="Maximize",
            command=self.toggle_viewer
        )
        self.viewer_toggle_button.pack(side="right", padx=3)
        
        viewer_text_frame = ttk.Frame(self.viewer_frame)
        viewer_text_frame.pack(fill="both", expand=True)

        self.response = tk.Text(
            viewer_text_frame,
            height=12,
            font=("Consolas", 9),
            wrap="none",
            cursor="xterm",
            state="disabled"
        )
        
        self.response.bind(
            "<Control-a>",
            self.select_all_response
        )
        self.response.bind(
            "<Control-A>",
            self.select_all_response
        )
        response_scrollbar = ttk.Scrollbar(
            viewer_text_frame,
            orient="vertical",
            command=self.response.yview
        )
        self.response.configure(
            yscrollcommand=response_scrollbar.set
        )

        self.response.pack(side="left", fill="both", expand=True)
        response_scrollbar.pack(side="right", fill="y")

        self.set_viewer_text("Waiting for received response...")

    # --------------------------------------------------
    # Validation
    # --------------------------------------------------

    def validate_root(self):

        if not self.feed_file.is_file():
            raise CabinError(
                f"mt5_feed.json not found:\n{self.feed_file}"
            )

        required_dirs = [
            self.gateway_dir,
            self.commands_file.parent,
            self.control_file.parent,
            self.temp_dir,
            self.received_dir
        ]

        missing = [
            str(path)
            for path in required_dirs
            if not path.is_dir()
        ]

        if missing:
            raise CabinError(
                "Required Gateway directories are missing:\n\n"
                + "\n".join(missing)
            )

        self.root_validated = True

    def validate_command(self):

        try:
            raw = self.editor.get("1.0", "end-1c")
            data = json.loads(raw)

            if not isinstance(data, dict):
                raise CabinError("Root JSON must be an object.")

            commands = data.get("commands")

            if not isinstance(commands, list) or not commands:
                raise CabinError("'commands' must be a non-empty array.")

            for command in commands:

                if not isinstance(command, dict):
                    raise CabinError("Each command must be an object.")

                if not isinstance(command.get("status"), str):
                    raise CabinError(
                        "Each command must have a string status."
                    )

            return data

        except json.JSONDecodeError as exc:
            raise CabinError(
                f"Invalid JSON:\n{exc}"
            ) from exc

    # --------------------------------------------------
    # Gateway state
    # --------------------------------------------------

    def get_state(self):

        if not self.state_file.exists():
            return "UNKNOWN"

        return self.state_file.read_text(
            encoding="utf-8",
            errors="replace"
        ).strip()

    def get_current_request(self):

        if not self.request_file.is_file():
            return None

        try:
            data = json.loads(read_text_auto(self.request_file))
            return data.get("request_id")
        except Exception:
            return "UNREADABLE"

    def get_pending_command(self):

        if not self.commands_file.is_file():
            return False

        try:
            data = json.loads(
                read_text_auto(self.commands_file)
            )

            commands = data.get("commands", [])

            for command in commands:
                if command.get("status") == "":
                    return True

        except Exception as exc:
            raise CabinError(
                f"Cannot read existing commands.json:\n{exc}"
            ) from exc

        return False

    # --------------------------------------------------
    # Send command
    # --------------------------------------------------

    def send_command(self):

        try:
            data = self.validate_command()
            for command in data["commands"]:
                command.pop("result", None)

            state = self.get_state()
            request_id = self.get_current_request()

            if state != "IDLE":
                raise CabinError(
                    f"Gateway is not IDLE. Current state: {state}"
                )

            if request_id:
                raise CabinError(
                    "A current request already exists. "
                    "New command is blocked."
                )
            if self.get_pending_command():
                raise CabinError(
                    "commands.json already contains an unprocessed command."
                )


            atomic_write_json(self.commands_file, data)

            messagebox.showinfo(
                "MT5 Cabin",
                "فرمان ارسال شد."
            )

            self.refresh()

        except Exception as exc:
            messagebox.showerror("Command Error", str(exc))

    # --------------------------------------------------
    # Cancel
    # --------------------------------------------------

    def cancel_request(self):

        try:
            request_id = self.get_current_request()

            if not request_id:
                raise CabinError(
                    "There is no current request to cancel."
                )

            if request_id == "UNREADABLE":
                raise CabinError(
                    "current_request.json cannot be read."
                )



            atomic_write_json(
                self.control_file,
                {
                    "commands": [
                        {
                            "command": "CANCEL",
                            "status": ""
                        }
                    ]
                }
            )

            messagebox.showinfo(
                "MT5 Cabin",
                "درخواست لغو ارسال شد."
            )

            self.refresh()

        except Exception as exc:
            messagebox.showerror("Cancel Error", str(exc))

    # --------------------------------------------------
    # Received responses
    # --------------------------------------------------

    def get_latest_response(self):

        if not self.received_dir.is_dir():
            return None

        files = list(self.received_dir.glob("*.json"))

        if not files:
            return None

        latest = max(
            files,
            key=lambda path: path.stat().st_mtime
        )

        try:
            content = read_text_auto(latest)
            data = json.loads(content)

            return {
                "file": latest.name,
                "modified": datetime.fromtimestamp(
                    latest.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "data": data
            }

        except Exception as exc:
            return {
                "file": latest.name,
                "error": str(exc)
            }
            
    def toggle_viewer(self):
        
        if self.editor_maximized:
            return
        
        if not self.viewer_maximized:

            self.normal_layout = [
                (widget, widget.pack_info())
                for widget in self.main_frame.winfo_children()
            ]

            for widget in self.main_frame.winfo_children():
                widget.pack_forget()

            self.viewer_frame.pack(fill="both", expand=True)

            self.viewer_toggle_button.configure(
                text="Restore"
            )

            self.viewer_maximized = True

        else:

            self.viewer_frame.pack_forget()

            for widget, pack_options in self.normal_layout:
                widget.pack(**pack_options)

            self.normal_layout = None

            self.viewer_toggle_button.configure(
                text="Maximize"
            )

            self.viewer_maximized = False
            
    def toggle_editor(self):

        if not self.editor_maximized:

            if self.viewer_maximized:
                return

            self.normal_layout = [
                (widget, widget.pack_info())
                for widget in self.main_frame.winfo_children()
            ]

            for widget in self.main_frame.winfo_children():
                widget.pack_forget()

            self.editor_frame.pack(fill="both", expand=True)

            self.editor_toggle_button.configure(
                text="Restore"
            )

            self.editor_maximized = True

        else:

            self.editor_frame.pack_forget()

            for widget, pack_options in self.normal_layout:
                widget.pack(**pack_options)

            self.normal_layout = None

            self.editor_toggle_button.configure(
                text="Maximize"
            )

            self.editor_maximized = False

    
            
    def select_all_response(self, event=None):

        self.response.tag_add("sel", "1.0", "end-1c")
        return "break"

    def set_viewer_text(self, text):

        self.response.configure(state="normal")
        self.response.delete("1.0", "end")
        self.response.insert("1.0", text)
        self.response.configure(state="disabled")
        
    def show_json_view(self):

        self.viewer_mode = "json"

        self.response.configure(wrap="none")

        if hasattr(self, "viewer_json_text"):
            self.set_viewer_text(self.viewer_json_text)


    def show_answer_view(self):

        if not self.viewer_answer_text:
            return

        self.viewer_mode = "answer"

        self.response.configure(wrap="word")

        self.set_viewer_text(self.viewer_answer_text)
        

    def display_json_file(self, path: Path):

        if not path.is_file():
            raise CabinError(f"JSON file not found:\n{path}")

        content = read_text_auto(path)
        data = json.loads(content)
        self.viewer_current_data = data

        modified = datetime.fromtimestamp(
            path.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M:%S")

        display = (
            f"File: {path.name}\n"
            f"Modified: {modified}\n\n"
            + json.dumps(
                data,
                ensure_ascii=False,
                indent=4
            )
        )

        payload = data.get("payload", {})
        answer = payload.get("answer") if isinstance(payload, dict) else None

        self.viewer_json_text = display
        self.viewer_answer_text = (
            html.unescape(answer)
            if isinstance(answer, str)
            else None
        )

        self.viewer_path_var.set(str(path))

        self.viewer_answer_button.configure(
            state="normal" if self.viewer_answer_text else "disabled"
        )

        if self.viewer_mode == "answer" and self.viewer_answer_text:
            self.show_answer_view()
        else:
            self.show_json_view()




    def browse_json_file(self):

        selected = filedialog.askopenfilename(
            title="Select JSON File",
            initialdir=str(self.received_dir),
            filetypes=[
                ("JSON files", "*.json"),
                ("All files", "*.*")
            ]
        )

        if selected:
            self.viewer_path_var.set(selected)
            self.viewer_is_latest = False


    def open_json_file(self):

        selected = self.viewer_path_var.get().strip()

        if not selected:
            messagebox.showwarning(
                "JSON Viewer",
                "Please select a JSON file first."
            )
            return

        try:
            self.display_json_file(Path(selected))

        except Exception as exc:
            messagebox.showerror(
                "JSON Viewer Error",
                str(exc)
            )


    def refresh_viewer(self):

        if self.viewer_is_latest:
            latest = self.get_latest_response()

            if not latest:
                self.viewer_path_var.set("")
                self.set_viewer_text(
                    "Waiting for received response..."
                )
                return

            path = self.received_dir / latest["file"]

            if "error" in latest:
                self.viewer_path_var.set(str(path))
                self.set_viewer_text(
                    f"File: {latest['file']}\n"
                    f"Error: {latest['error']}"
                )
                return

            self.display_json_file(path)

        else:
            selected = self.viewer_path_var.get().strip()

            if selected:
                self.display_json_file(Path(selected))
    # --------------------------------------------------
    # Refresh
    # --------------------------------------------------

    def refresh(self, show_message=False):

        if not self.root_validated:
            return

        try:
            state = self.get_state()
            request_id = self.get_current_request()

            self.state_var.set(state)
            self.request_var.set(
                str(request_id) if request_id else "None"
            )

            if state == "IDLE":
                self.status_var.set(
                    "Gateway is IDLE. A new command may be submitted "
                    "if no pending command exists."
                )
            else:
                self.status_var.set(
                    "Gateway is busy or in a non-IDLE state. "
                    "New commands are blocked."
                )

            self.refresh_viewer()
                
            if show_message:
                messagebox.showinfo("MT5 Cabin", "رفرش شد.")
        
        except Exception as exc:
            self.status_var.set(f"Refresh error: {exc}")



    def run(self):
        self.window.mainloop()


def main():

    try:
        root = load_env()
        app = MT5Cabin(root)
        app.run()

    except Exception as exc:
        error_window = tk.Tk()
        error_window.withdraw()

        messagebox.showerror(
            APP_TITLE,
            str(exc)
        )

        error_window.destroy()


if __name__ == "__main__":
    main()
