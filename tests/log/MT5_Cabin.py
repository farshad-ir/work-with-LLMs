import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime


APP_TITLE = "MT5 Cabin 0.1"
REFRESH_INTERVAL = 1000


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

        self.window.after(REFRESH_INTERVAL, self.auto_refresh)

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def build_ui(self):

        main = ttk.Frame(self.window, padding=12)
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

        editor_frame = ttk.LabelFrame(
            main,
            text="Command JSON Editor",
            padding=8
        )
        editor_frame.pack(fill="both", expand=True, pady=8)

        self.editor = tk.Text(
            editor_frame,
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
                            "id": "list-tables-001",
                            "command": "LIST-TABL",
                            "status": "PENDING"
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
            text="Validate JSON",
            command=self.validate_command
        ).pack(side="left", padx=3)

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
            command=self.refresh
        ).pack(side="right", padx=3)

        response_frame = ttk.LabelFrame(
            main,
            text="Latest Received Response",
            padding=8
        )
        response_frame.pack(fill="both", expand=True, pady=8)

        self.response = tk.Text(
            response_frame,
            height=12,
            font=("Consolas", 9),
            wrap="none"
        )
        self.response.pack(fill="both", expand=True)

        self.response.insert("1.0", "Waiting for received response...")
        self.response.configure(state="disabled")

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

            if not isinstance(commands, list):
                raise CabinError("'commands' must be an array.")

            if len(commands) != 1:
                raise CabinError(
                    "Version 0.1 supports exactly one command."
                )

            command = commands[0]

            if not isinstance(command, dict):
                raise CabinError("Command entry must be an object.")

            required = ("id", "command", "status")

            for key in required:
                if key not in command:
                    raise CabinError(f"Missing field: {key}")

            if not isinstance(command["id"], str) or not command["id"].strip():
                raise CabinError("Command id must be a non-empty string.")

            if command["command"] != "LIST-TABL":
                raise CabinError(
                    "MT5 Gateway v0.1 currently supports LIST-TABL only."
                )

            if command["status"] != "PENDING":
                raise CabinError("Command status must be PENDING.")

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
                if command.get("status") == "PENDING":
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
                    "commands.json already contains a PENDING command."
                )

            if not messagebox.askyesno(
                "Confirm Command",
                "Write this command to commands.json?"
            ):
                return

            atomic_write_json(self.commands_file, data)

            messagebox.showinfo(
                "MT5 Cabin",
                "Command written successfully.\n\n"
                "The EA must execute OnInit/RunCommands "
                "to read this command."
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

            if not messagebox.askyesno(
                "Confirm CANCEL",
                "Write CANCEL request?\n\n"
                "Important:\n"
                "This only submits a cancellation request. "
                "It does NOT confirm that the remote operation stopped.\n\n"
                "The current EA implementation processes control "
                "during OnInit, so cancellation is not guaranteed "
                "to be immediate."
            ):
                return

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
                "CANCEL request written to control.json.\n\n"
                "The EA must execute ProcessControl() "
                "to read it."
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

    # --------------------------------------------------
    # Refresh
    # --------------------------------------------------

    def refresh(self):

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

            latest = self.get_latest_response()

            if latest:
                if "error" in latest:
                    display = (
                        f"File: {latest['file']}\n"
                        f"Error: {latest['error']}"
                    )
                else:
                    display = (
                        f"File: {latest['file']}\n"
                        f"Modified: {latest['modified']}\n\n"
                        + json.dumps(
                            latest["data"],
                            ensure_ascii=False,
                            indent=4
                        )
                    )

                self.response.configure(state="normal")
                self.response.delete("1.0", "end")
                self.response.insert("1.0", display)
                self.response.configure(state="disabled")

        except Exception as exc:
            self.status_var.set(f"Refresh error: {exc}")

    def auto_refresh(self):
        self.refresh()
        self.window.after(
            REFRESH_INTERVAL,
            self.auto_refresh
        )

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
