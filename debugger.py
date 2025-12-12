import asyncio
import os
import re
from pathlib import Path
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
import tkinter as tk
from tkinter import ttk

OSC_LISTEN_PORT = 9001

param_values: dict[str, float | None] = {}

def print_param_value(address, *args):
    value = args[0] if args else None
    param_values[address] = value

# --- Парсер параметров из лога VRChat ---
def get_local_low() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local).parent / "LocalLow"
    user = os.environ.get("USERNAME")
    return Path(f"C:/Users/{user}/AppData/LocalLow")

def find_latest_log(log_dir: Path) -> Path | None:
    files = list(log_dir.glob("output_log*.txt"))
    if not files:
        print("Файлы не найдены в:", log_dir)
        return None
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0]

def parse_vrchat_params_from_log(log_path: Path) -> dict:
    params = {}
    try:
        with log_path.open("r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Ошибка чтения лога: {e}")
        return params
    # interaction
    found = re.search(r"Avatar interaction level:\s*(.+)", content)
    params["interaction"] = found.group(1).strip() if found else ""
    # self-interaction
    found = re.search(r"Avatar self-interaction:\s*(.+)", content)
    params["self-interaction"] = found.group(1).strip() if found else ""
    # osc
    found = re.search(r"OSC enabled:\s*(.+)", content)
    osc_value = found.group(1).strip() if found else ""
    if "of type OSC on" in content:
        osc_value = "True"
    params["osc"] = osc_value
    return params

def get_main_params() -> dict:
    log_dir = get_local_low() / "VRChat" / "VRChat"
    log_path = find_latest_log(log_dir)
    if not log_path:
        print("Лог-файл не найден.")
        return {
            "osc": "",
            "self-interaction": "",
            "interaction": ""
        }
    print("Используем лог:", log_path)
    params = parse_vrchat_params_from_log(log_path)
    # Заполняем отсутствующие ключи дефолтными значениями
    for key in ["osc", "self-interaction", "interaction"]:
        params.setdefault(key, "")
    return params

# --- GUI ---
class DebuggerWindow:
    def __init__(self, root, main_params):
        self.root = root
        self.root.title("OSC Live Debugger")
        self.root.geometry("600x400")

        # Frame для таблицы и скролла
        frame = tk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True)

        # Treeview
        self.tree = ttk.Treeview(frame, columns=("Parameter", "Value"), show="headings")
        self.tree.heading("Parameter", text="Parameter")
        self.tree.heading("Value", text="Value")

        # Скроллбар
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Установка ширины колонок
        self.set_column_widths()
        self.root.bind("<Configure>", self.on_resize)

        # Блок для отображения параметров снизу
        self.info_label = tk.Label(root, text="", anchor="w", justify="left", font=("Consolas", 11))
        self.info_label.pack(fill=tk.X, padx=8, pady=8)

        self.main_params = main_params
        self.update_table()
        self.update_info()

    def set_column_widths(self):
        total_width = self.root.winfo_width()
        if total_width < 100:
            total_width = 600
        param_width = int(total_width * 2 / 3)
        value_width = total_width - param_width
        self.tree.column("Parameter", width=param_width, anchor="w")
        self.tree.column("Value", width=value_width, anchor="w")

    def on_resize(self, event):
        self.set_column_widths()

    def update_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for param in sorted(param_values.keys()):
            value = param_values[param]
            self.tree.insert("", "end", values=(param, value))
        self.root.after(100, self.update_table)

    def update_info(self):
        # Форматируем строку как osc="..." self-interaction="..." interaction="..."
        info_text = (
            f'osc="{self.main_params.get("osc", "")}" '
            f'self-interaction="{self.main_params.get("self-interaction", "")}" '
            f'interaction="{self.main_params.get("interaction", "")}"'
        )
        self.info_label.config(text=info_text)
        self.root.after(5000, self.update_info)

async def osc_server_loop():
    dispatcher = Dispatcher()
    dispatcher.map("*", print_param_value)
    server = AsyncIOOSCUDPServer(("0.0.0.0", OSC_LISTEN_PORT), dispatcher, asyncio.get_event_loop())
    transport, protocol = await server.create_serve_endpoint()
    print(f"Listening for OSC events on port {OSC_LISTEN_PORT}...")
    try:
        while True:
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass
    transport.close()

def start_tkinter(main_params):
    root = tk.Tk()
    window = DebuggerWindow(root, main_params)
    root.mainloop()

async def main():
    main_params = get_main_params()
    loop = asyncio.get_event_loop()
    osc_task = asyncio.create_task(osc_server_loop())
    await loop.run_in_executor(None, start_tkinter, main_params)
    osc_task.cancel()
    try:
        await osc_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())
