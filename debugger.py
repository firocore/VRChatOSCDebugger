import asyncio
import os
import re
from pathlib import Path
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
import tkinter as tk
from tkinter import ttk, messagebox

OSC_LISTEN_PORT = 9001
IGNORED_PARAMS_FILE = "ignored_params.txt"

param_values: dict[str, float | None] = {}

def print_param_value(address, *args):
    value = args[0] if args else None
    param_values[address] = value

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
    found = re.search(r"Avatar interaction level:\s*(.+)", content)
    params["interaction"] = found.group(1).strip() if found else ""
    found = re.search(r"Avatar self-interaction:\s*(.+)", content)
    params["self-interaction"] = found.group(1).strip() if found else ""
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
    for key in ["osc", "self-interaction", "interaction"]:
        params.setdefault(key, "")
    return params

def load_ignored_params() -> set[str]:
    if not os.path.exists(IGNORED_PARAMS_FILE):
        return set()
    with open(IGNORED_PARAMS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_ignored_params(ignored: set[str]):
    with open(IGNORED_PARAMS_FILE, "w", encoding="utf-8") as f:
        for param in sorted(ignored):
            f.write(param + "\n")

class IgnoreListWindow(tk.Toplevel):
    def __init__(self, parent, ignored_params: set[str], on_remove_callback):
        super().__init__(parent)
        self.title("ignore list")
        self.geometry("350x300")
        self.ignored_params = ignored_params
        self.on_remove_callback = on_remove_callback

        self.listbox = tk.Listbox(self, selectmode="extended")
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.update_list()

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.remove_btn = tk.Button(btn_frame, text="delete", command=self.remove_selected)
        self.remove_btn.pack(side=tk.RIGHT)

    def update_list(self):
        self.listbox.delete(0, tk.END)
        for param in sorted(self.ignored_params):
            self.listbox.insert(tk.END, param)

    def remove_selected(self):
        selected_indices = self.listbox.curselection()
        if not selected_indices:
            return
        to_remove = [self.listbox.get(i) for i in selected_indices]
        for param in to_remove:
            self.ignored_params.discard(param)
        self.update_list()
        self.on_remove_callback()
        save_ignored_params(self.ignored_params)

class DebuggerWindow:
    def __init__(self, root, main_params):
        self.root = root
        self.root.title("OSC Live Debugger")
        self.root.geometry("600x400")

        # Игнор-лист
        self.ignored_params: set[str] = load_ignored_params()

        # Frame для таблицы и скролла
        frame = tk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True)

        # Treeview с мультивыбором
        self.tree = ttk.Treeview(frame, columns=("Parameter", "Value"), show="headings", selectmode="extended")
        self.tree.heading("Parameter", text="Parameter")
        self.tree.heading("Value", text="Value")

        # Скроллбар
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.set_column_widths()
        self.root.bind("<Configure>", self.on_resize)

        # Нижний фрейм для info и кнопок
        bottom_frame = tk.Frame(root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=8, pady=8)

        # Info label слева
        self.info_label = tk.Label(bottom_frame, text="", anchor="w", justify="left", font=("Consolas", 11))
        self.info_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Кнопка "Игнор-лист"
        self.ignore_list_button = tk.Button(bottom_frame, text="ignore list", command=self.open_ignore_list)
        self.ignore_list_button.pack(side=tk.RIGHT, padx=(5, 0))

        # Кнопка очистки справа
        self.clear_button = tk.Button(bottom_frame, text="clear", command=self.clear_params)
        self.clear_button.pack(side=tk.RIGHT, padx=(5, 0))

        self.main_params = main_params
        self.param_to_item: dict[str, str] = {}
        self.update_table()
        self.update_info()

        # --- Копирование и игнор-лист ---
        self.tree.bind("<Control-c>", self.copy_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)  # ПКМ

        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="copy", command=self.copy_selected)
        self.context_menu.add_command(label="add to ignore", command=self.add_to_ignore)

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
        # Только неигнорируемые параметры
        current_params = set(param for param in param_values.keys() if param not in self.ignored_params)
        tree_params = set(self.param_to_item.keys())

        # Добавить или обновить параметры
        for param in current_params:
            value = param_values[param]
            if param in self.param_to_item:
                item_id = self.param_to_item[param]
                self.tree.set(item_id, "Value", value)
            else:
                item_id = self.tree.insert("", "end", values=(param, value))
                self.param_to_item[param] = item_id

        # Удалить параметры, которых больше нет или они теперь в игноре
        for param in tree_params - current_params:
            item_id = self.param_to_item.pop(param)
            self.tree.delete(item_id)

        self.root.after(100, self.update_table)

    def update_info(self):
        info_text = (
            f'osc="{self.main_params.get("osc", "")}" '
            f'self-interaction="{self.main_params.get("self-interaction", "")}" '
            f'interaction="{self.main_params.get("interaction", "")}"'
        )
        self.info_label.config(text=info_text)
        self.root.after(5000, self.update_info)

    def clear_params(self):
        param_values.clear()
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.param_to_item.clear()
        # self.ignored_params.clear()  # Сброс игнор-листа
        # save_ignored_params(self.ignored_params)

    # --- Копирование выделенных строк ---
    def copy_selected(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        lines = []
        for item_id in selected:
            values = self.tree.item(item_id, "values")
            lines.append(f"{values[0]}\t{values[1]}")
        text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # --- Добавить в игнор-лист ---
    def add_to_ignore(self, event=None):
        selected = self.tree.selection()
        changed = False
        for item_id in selected:
            values = self.tree.item(item_id, "values")
            param = values[0]
            if param not in self.ignored_params:
                self.ignored_params.add(param)
                changed = True
            # Удалить из таблицы
            if param in self.param_to_item:
                self.tree.delete(self.param_to_item[param])
                del self.param_to_item[param]
        if changed:
            save_ignored_params(self.ignored_params)

    # --- Контекстное меню ---
    def show_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            # Если кликнули по строке, выделить её (или добавить к выделению)
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.context_menu.post(event.x_root, event.y_root)

    # --- Окно игнор-листа ---
    def open_ignore_list(self):
        def on_remove():
            # После удаления из игнора обновить таблицу
            save_ignored_params(self.ignored_params)
        IgnoreListWindow(self.root, self.ignored_params, on_remove)

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
