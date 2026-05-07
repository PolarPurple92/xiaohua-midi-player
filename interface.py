# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import sys, os, json, shutil, threading, time, traceback, subprocess, tkinter as tk
from tkinter import ttk, messagebox, Menu, simpledialog, filedialog
from PIL import Image, ImageTk, ImageGrab
import tkinterdnd2

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

from omr_recognizer import recognize
from score_to_midi import musicxml_to_midi
from midi_player import play_midi as play_midi_file

# ---------- 路径与配置 ----------
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(BASE_DIR, relative_path)

SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
XML_DIR = os.path.join(BASE_DIR, "xml_outputs")
MIDI_DIR = os.path.join(BASE_DIR, "midi_outputs")
SHEET_IMG_DIR = os.path.join(BASE_DIR, "sheet_images")

# 音色库默认文件夹：开发环境在项目目录，打包后在临时目录
_raw_sf_dir = os.path.join(BASE_DIR, "soundfonts")
SOUNDFONT_DIR = resource_path("soundfonts") if os.path.isdir(resource_path("soundfonts")) else _raw_sf_dir

for d in (SCREENSHOT_DIR, XML_DIR, MIDI_DIR, SHEET_IMG_DIR, SOUNDFONT_DIR):
    os.makedirs(d, exist_ok=True)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DEFAULT_HOTKEY = "ctrl+shift+z"

def load_config():
    defaults = {
        "hotkey": DEFAULT_HOTKEY,
        "auto_play": False,
        "sf2_folder": "",
        "sf2_name": "",
        "volume": 1.0,
        "speed": 1.0,
        "musescore_path": "",
        "auto_render": False
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    return defaults

def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)

# ---------- 截图捕获 ----------
class ScreenCapture:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.top = tk.Toplevel(master)
        self.top.attributes('-fullscreen', True, '-alpha', 0.3, '-topmost', True)
        self.top.configure(cursor='cross')
        self.canvas = tk.Canvas(self.top, bg='gray', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.start_x = self.start_y = None
        self.rect = None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.top.bind("<Escape>", self.cancel)

    def on_press(self, event):
        self.start_x, self.start_y = self.top.winfo_pointerx(), self.top.winfo_pointery()
        self.rect = self.canvas.create_rectangle(0,0,0,0, outline='red', width=2)

    def on_drag(self, event):
        cx, cy = self.top.winfo_pointerx(), self.top.winfo_pointery()
        self.canvas.coords(self.rect, self.start_x, self.start_y, cx, cy)

    def on_release(self, event):
        ex, ey = self.top.winfo_pointerx(), self.top.winfo_pointery()
        self.top.destroy()
        x1, x2 = sorted([self.start_x, ex])
        y1, y2 = sorted([self.start_y, ey])
        if x2 - x1 < 10 or y2 - y1 < 10:
            self.callback(None)
            return
        img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        import datetime
        fn = f"cap_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        save_path = os.path.join(SCREENSHOT_DIR, fn)
        img.save(save_path)
        self.callback(save_path)

    def cancel(self, event=None):
        self.top.destroy()
        self.callback(None)

# ---------- 缩略图单元 ----------
class ScoreThumbnail(tk.Frame):
    def __init__(self, master, filepath, on_delete, on_play, **kw):
        super().__init__(master, **kw)
        self.filepath = filepath
        self.on_delete = on_delete
        self.on_play = on_play
        try:
            img = Image.open(filepath)
            img.thumbnail((150, 100))
            self.thumb = ImageTk.PhotoImage(img)
        except:
            self.thumb = None
        self.label = tk.Label(self, image=self.thumb, text=os.path.basename(filepath),
                              compound=tk.TOP, relief=tk.RIDGE, width=160, height=120)
        self.label.pack(padx=2, pady=2)
        self.label.bind("<Double-Button-1>", lambda e: os.startfile(filepath))
        self.label.bind("<Button-3>", self.show_menu)
        self.menu = Menu(self, tearoff=False)
        self.menu.add_command(label="▶ 识别并播放", command=self.play)
        self.menu.add_command(label="❌ 删除", command=self.delete)

    def show_menu(self, event):
        self.menu.post(event.x_root, event.y_root)

    def play(self):
        self.on_play(self.filepath)

    def delete(self):
        if messagebox.askyesno("确认删除", f"确定要删除 {os.path.basename(self.filepath)} 吗？"):
            os.remove(self.filepath)
            self.on_delete(self)

# ---------- 主应用 ----------
class ScoreBrowserApp:
    def __init__(self, root):
        self.root = root
        self.root.title("小花截图MIDI播放工具")
        self.root.geometry("1050x750")
        self.root.drop_target_register(tkinterdnd2.DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.on_drop)

        self.config = load_config()
        self.thumbnails = {}
        self.capturing = False
        self.last_hotkey_time = 0
        self.processing_lock = threading.Lock()
        self.processing_files = set()
        self.status_text = tk.StringVar(value="就绪")

        # 窗口图标
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
            except Exception:
                pass

        if HAS_KEYBOARD:
            self.register_hotkey()
            root.protocol("WM_DELETE_WINDOW", self.on_closing)
        else:
            print("未安装 keyboard 库，全局热键不可用。区域截图请使用界面按钮。")

        # ----- 菜单 -----
        menubar = Menu(root)
        root.config(menu=menubar)
        settings_menu = Menu(menubar, tearoff=False)
        settings_menu.add_command(label="修改截图快捷键", command=self.change_hotkey)
        settings_menu.add_command(label="选择音色库文件夹", command=self.choose_sf2_folder)
        settings_menu.add_command(label="设置 MuseScore 路径", command=self.set_musescore_path)
        menubar.add_cascade(label="设置", menu=settings_menu)
        about_menu = Menu(menubar, tearoff=False)
        about_menu.add_command(label="关于作者", command=self.show_about)
        menubar.add_cascade(label="关于", menu=about_menu)

        # ----- 工具栏 -----
        toolbar = ttk.Frame(root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        ttk.Button(toolbar, text="区域截图", command=self.area_capture).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="从剪贴板添加", command=self.clipboard_add).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="刷新", command=self.full_refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="打开截图文件夹", command=lambda: os.startfile(SCREENSHOT_DIR)).pack(side=tk.LEFT, padx=2)

        # 音色库
        tk.Label(toolbar, text=" 音色:").pack(side=tk.LEFT)
        self.sf2_var = tk.StringVar(value=self.config.get("sf2_name", ""))
        self.sf2_combo = ttk.Combobox(toolbar, textvariable=self.sf2_var, width=15, state="readonly")
        self.sf2_combo.pack(side=tk.LEFT, padx=2)
        self._update_sf2_list()
        self.sf2_combo.bind("<<ComboboxSelected>>", self._on_sf2_change)

        # 音量
        tk.Label(toolbar, text=" 音量:").pack(side=tk.LEFT)
        self.volume_var = tk.DoubleVar(value=self.config.get("volume", 1.0))
        self.volume_scale = ttk.Scale(toolbar, from_=0.0, to=2.0, variable=self.volume_var,
                                      orient=tk.HORIZONTAL, length=120, command=self._on_volume_change)
        self.volume_scale.pack(side=tk.LEFT, padx=2)
        self.volume_label = tk.Label(toolbar, text=f"{int(self.volume_var.get()*100)}%")
        self.volume_label.pack(side=tk.LEFT)

        # 速度
        tk.Label(toolbar, text=" 速度:").pack(side=tk.LEFT)
        self.speed_var = tk.DoubleVar(value=self.config.get("speed", 1.0))
        self.speed_scale = ttk.Scale(toolbar, from_=0.3, to=2.0, variable=self.speed_var,
                                     orient=tk.HORIZONTAL, length=120, command=self._on_speed_change)
        self.speed_scale.pack(side=tk.LEFT, padx=2)
        self.speed_label = tk.Label(toolbar, text=f"{self.speed_var.get():.1f}x")
        self.speed_label.pack(side=tk.LEFT)

        # 自动播放
        self.auto_play_var = tk.BooleanVar(value=self.config.get("auto_play", False))
        self.auto_cb = ttk.Checkbutton(toolbar, text="截图后自动播放", variable=self.auto_play_var,
                                       command=self._toggle_auto_play)
        self.auto_cb.pack(side=tk.LEFT, padx=10)

        # 自动渲染乐谱图
        self.auto_render_var = tk.BooleanVar(value=self.config.get("auto_render", False))
        self.auto_render_cb = ttk.Checkbutton(toolbar, text="自动渲染乐谱图", variable=self.auto_render_var,
                                              command=self._toggle_auto_render)
        self.auto_render_cb.pack(side=tk.LEFT, padx=10)

        hotkey_text = f"全局截图: {self.config.get('hotkey','未设置')}" if HAS_KEYBOARD else "全局热键: 未启用"
        ttk.Label(toolbar, text=f"   {hotkey_text}").pack(side=tk.RIGHT, padx=5)

        # 状态栏
        status_frame = ttk.Frame(root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)
        ttk.Label(status_frame, textvariable=self.status_text, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X)

        # ----- 标签页 -----
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 截图页
        self.img_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.img_tab, text="截图")
        canvas_frame = ttk.Frame(self.img_tab)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg='SystemButtonFace')
        self.img_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.img_scrollbar.set)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.scrollable_frame, anchor="nw")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.img_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # XML 页
        self.xml_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.xml_tab, text="XML 文件")
        xml_frame = ttk.Frame(self.xml_tab)
        xml_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.xml_listbox = tk.Listbox(xml_frame, selectmode=tk.SINGLE)
        xml_scroll = ttk.Scrollbar(xml_frame, orient=tk.VERTICAL, command=self.xml_listbox.yview)
        self.xml_listbox.configure(yscrollcommand=xml_scroll.set)
        self.xml_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        xml_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.xml_menu = Menu(self.xml_listbox, tearoff=False)
        self.xml_menu.add_command(label="打开文件", command=self.open_xml)
        self.xml_menu.add_command(label="用 MuseScore 编辑", command=self.edit_xml_in_musescore)
        self.xml_menu.add_command(label="渲染为乐谱图片", command=lambda: self.render_xml_to_image(self.get_selected_xml()))
        self.xml_menu.add_command(label="转换为 MIDI", command=self.convert_xml_to_midi)
        self.xml_menu.add_command(label="播放（转换后播放）", command=self.play_xml)
        self.xml_menu.add_separator()
        self.xml_menu.add_command(label="删除", command=self.delete_xml)
        self.xml_listbox.bind("<Button-3>", self.show_xml_menu)
        self.xml_listbox.bind("<Double-Button-1>", lambda e: self.open_xml())

        # MIDI 页
        self.midi_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.midi_tab, text="MIDI 文件")
        midi_frame = ttk.Frame(self.midi_tab)
        midi_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.midi_listbox = tk.Listbox(midi_frame, selectmode=tk.SINGLE)
        midi_scroll = ttk.Scrollbar(midi_frame, orient=tk.VERTICAL, command=self.midi_listbox.yview)
        self.midi_listbox.configure(yscrollcommand=midi_scroll.set)
        self.midi_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        midi_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.midi_menu = Menu(self.midi_listbox, tearoff=False)
        self.midi_menu.add_command(label="播放", command=self.play_midi_file_gui)
        self.midi_menu.add_command(label="删除", command=self.delete_midi)
        self.midi_listbox.bind("<Button-3>", self.show_midi_menu)
        self.midi_listbox.bind("<Double-Button-1>", lambda e: self.play_midi_file_gui())

        # 乐谱图片页
        self.sheet_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.sheet_tab, text="乐谱图片")
        sheet_frame = ttk.Frame(self.sheet_tab)
        sheet_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.sheet_listbox = tk.Listbox(sheet_frame, selectmode=tk.SINGLE)
        sheet_scroll = ttk.Scrollbar(sheet_frame, orient=tk.VERTICAL, command=self.sheet_listbox.yview)
        self.sheet_listbox.configure(yscrollcommand=sheet_scroll.set)
        self.sheet_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sheet_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.sheet_menu = Menu(self.sheet_listbox, tearoff=False)
        self.sheet_menu.add_command(label="打开图片", command=self.open_sheet_image)
        self.sheet_menu.add_command(label="删除", command=self.delete_sheet_image)
        self.sheet_listbox.bind("<Button-3>", self.show_sheet_menu)
        self.sheet_listbox.bind("<Double-Button-1>", lambda e: self.open_sheet_image())

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.full_refresh()

    # ---------- 音色库管理 ----------
    def choose_sf2_folder(self):
        folder = filedialog.askdirectory(title="请选择包含 .sf2 音色库文件的文件夹")
        if not folder:
            return
        sf2_files = [f for f in os.listdir(folder) if f.lower().endswith('.sf2')]
        if not sf2_files:
            messagebox.showinfo("提示", "所选文件夹中没有找到 .sf2 音色库文件。")
            return
        sf2_files.sort()
        self.config["sf2_folder"] = folder
        self.config["sf2_name"] = sf2_files[0]
        save_config(self.config)
        self._update_sf2_list()
        self.sf2_var.set(sf2_files[0])
        messagebox.showinfo("成功", f"已加载 {len(sf2_files)} 个音色库。")

    def _update_sf2_list(self):
        folder = self.config.get("sf2_folder", "")
        if folder and os.path.isdir(folder):
            files = [f for f in os.listdir(folder) if f.lower().endswith('.sf2')]
        else:
            sf_dir = SOUNDFONT_DIR if os.path.isdir(SOUNDFONT_DIR) else os.path.join(BASE_DIR, "soundfonts")
            if not os.path.isdir(sf_dir):
                os.makedirs(sf_dir, exist_ok=True)
            files = [f for f in os.listdir(sf_dir) if f.lower().endswith('.sf2')]
            if not files and os.path.isfile(os.path.join(BASE_DIR, "soundfont.sf2")):
                files.append("soundfont.sf2")
        if not files:
            self.sf2_combo['values'] = ["未配置音色库"]
            self.sf2_var.set("未配置音色库")
        else:
            files.sort()
            self.sf2_combo['values'] = files
            if self.config.get("sf2_name", "") not in files:
                self.config["sf2_name"] = files[0]
                self.sf2_var.set(files[0])
            else:
                self.sf2_var.set(self.config["sf2_name"])

    def _on_sf2_change(self, event=None):
        new_name = self.sf2_var.get()
        if new_name != "未配置音色库":
            self.config["sf2_name"] = new_name
            save_config(self.config)

    def get_sf2_path(self):
        name = self.config.get("sf2_name", "")
        if not name or name == "未配置音色库":
            fallback = os.path.join(SOUNDFONT_DIR, "soundfont.sf2")
            if os.path.exists(fallback):
                return fallback
            return ""
        folder = self.config.get("sf2_folder", "")
        if folder and os.path.isdir(folder):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return path
        path = os.path.join(SOUNDFONT_DIR, name)
        if os.path.exists(path):
            return path
        path = os.path.join(BASE_DIR, name)
        if os.path.exists(path):
            return path
        return ""

    def _check_sf2(self):
        sf2 = self.get_sf2_path()
        if not sf2:
            messagebox.showwarning("缺少音色库", "未找到音色库文件，请先在菜单“设置”中“选择音色库文件夹”。")
            return None
        return sf2

    # ---------- MuseScore 集成 ----------
    def set_musescore_path(self):
        path = filedialog.askopenfilename(
            title="选择 MuseScore 可执行文件",
            filetypes=[("MuseScore", "MuseScore*.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.config["musescore_path"] = path
            save_config(self.config)
            messagebox.showinfo("成功", f"MuseScore 路径已设置为：{path}")

    def _find_musescore(self):
        common = [
            "C:/Program Files/MuseScore 4/bin/MuseScore4.exe",
            "C:/Program Files/MuseScore 3/bin/MuseScore3.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\MuseScore 4\bin\MuseScore4.exe"),
            os.path.expandvars(r"%ProgramFiles%\MuseScore 4\bin\MuseScore4.exe"),
        ]
        for p in common:
            if os.path.exists(p):
                self.config["musescore_path"] = p
                save_config(self.config)
                return p
        return None

    def edit_xml_in_musescore(self):
        xml_path = self.get_selected_xml()
        if not xml_path:
            return
        musescore = self.config.get("musescore_path", "")
        if not musescore or not os.path.isfile(musescore):
            musescore = self._find_musescore()
        if not musescore:
            messagebox.showwarning("MuseScore 未找到", "请先在“设置 -> 设置 MuseScore 路径”中指定 MuseScore 程序。")
            return
        try:
            subprocess.Popen([musescore, xml_path])
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    # ---------- 渲染乐谱图片 ----------
    def render_xml_to_image(self, xml_path):
        if not xml_path or not os.path.isfile(xml_path):
            messagebox.showinfo("提示", "无效的 XML 文件。")
            return

        musescore = self.config.get("musescore_path", "")
        if not musescore or not os.path.isfile(musescore):
            musescore = self._find_musescore()
        if not musescore:
            messagebox.showwarning("MuseScore 未找到", "请先在“设置 -> 设置 MuseScore 路径”中指定 MuseScore 程序。")
            return

        base_name = os.path.splitext(os.path.basename(xml_path))[0]
        output_path = os.path.join(SHEET_IMG_DIR, base_name + ".png")

        def task():
            # 记录渲染前 SHEET_IMG_DIR 中所有现有文件
            before = set(os.listdir(SHEET_IMG_DIR))

            try:
                from music21 import environment, converter
                us = environment.UserSettings()
                us['musescoreDirectPNGPath'] = musescore
                score = converter.parse(xml_path)
                score.write('musicxml.png', output_path)

                # 找出新生成的所有文件
                after = set(os.listdir(SHEET_IMG_DIR))
                new_files = after - before

                # 我们期望的图片文件名
                target_name = base_name + ".png"
                target_found = False

                # 若目标文件已存在于新文件中，直接使用
                if target_name in new_files:
                    target_found = True
                else:
                    # 寻找所有新出现的 .png 文件，重命名为目标文件名
                    png_files = [f for f in new_files if f.lower().endswith('.png')]
                    if png_files:
                        # 选择第一个（通常就是乐谱第一页）
                        src = os.path.join(SHEET_IMG_DIR, png_files[0])
                        dest = os.path.join(SHEET_IMG_DIR, target_name)
                        if os.path.exists(dest):
                            os.remove(dest)
                        os.rename(src, dest)
                        target_found = True
                        # 更新 new_files 以便后续清理
                        new_files.discard(png_files[0])
                        new_files.add(target_name)

                if not target_found:
                    raise RuntimeError("music21 没有生成任何图片文件，请检查 MuseScore 是否正确安装并已配置路径。")

                # 删除所有其他新增文件（多余的图片、可能被误生成的 .xml 等）
                for fname in new_files:
                    if fname != target_name:
                        try:
                            os.remove(os.path.join(SHEET_IMG_DIR, fname))
                        except OSError:
                            pass

                self.root.after(0, lambda: messagebox.showinfo("成功", f"乐谱图片已生成：{os.path.join(SHEET_IMG_DIR, target_name)}"))
                self.root.after(0, self.refresh_sheet_images)

            except Exception as e:
                err_msg = str(e)
                print(err_msg)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror("渲染失败", msg))

        threading.Thread(target=task, daemon=True).start()

    # ---------- 乐谱图片列表操作 ----------
    def refresh_sheet_images(self):
        self.sheet_listbox.delete(0, tk.END)
        for f in sorted(os.listdir(SHEET_IMG_DIR)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                self.sheet_listbox.insert(tk.END, f)

    def show_sheet_menu(self, event):
        try:
            self.sheet_listbox.selection_clear(0, tk.END)
            self.sheet_listbox.selection_set(self.sheet_listbox.nearest(event.y))
            self.sheet_menu.post(event.x_root, event.y_root)
        except: pass

    def get_selected_sheet_image(self):
        sel = self.sheet_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个乐谱图片。")
            return None
        return os.path.join(SHEET_IMG_DIR, self.sheet_listbox.get(sel[0]))

    def open_sheet_image(self):
        path = self.get_selected_sheet_image()
        if path: os.startfile(path)

    def delete_sheet_image(self):
        path = self.get_selected_sheet_image()
        if path and messagebox.askyesno("确认删除", f"删除 {os.path.basename(path)}？"):
            os.remove(path)
            self.refresh_sheet_images()

    # ---------- 其他设置 ----------
    def _toggle_auto_play(self):
        self.config["auto_play"] = self.auto_play_var.get()
        save_config(self.config)

    def _toggle_auto_render(self):
        self.config["auto_render"] = self.auto_render_var.get()
        save_config(self.config)

    def _on_volume_change(self, event=None):
        self.config["volume"] = self.volume_var.get()
        save_config(self.config)
        self.volume_label.config(text=f"{int(self.volume_var.get()*100)}%")

    def _on_speed_change(self, event=None):
        self.config["speed"] = self.speed_var.get()
        save_config(self.config)
        self.speed_label.config(text=f"{self.speed_var.get():.1f}x")

    def register_hotkey(self):
        try:
            keyboard.remove_hotkey('capture_hotkey')
        except: pass
        hotkey = self.config.get('hotkey', DEFAULT_HOTKEY)
        def debounced():
            now = time.time()
            if now - self.last_hotkey_time < 0.5: return
            self.last_hotkey_time = now
            self.root.after(0, self.area_capture)
        keyboard.add_hotkey(hotkey, debounced, suppress=False)
        print(f"全局热键已注册: {hotkey}")

    def change_hotkey(self):
        new_hotkey = simpledialog.askstring("修改截图快捷键", "请输入组合键（如 ctrl+shift+a）:", initialvalue=self.config.get('hotkey', ''))
        if new_hotkey and new_hotkey.strip():
            self.config['hotkey'] = new_hotkey.strip()
            save_config(self.config)
            if HAS_KEYBOARD: self.register_hotkey()
            messagebox.showinfo("成功", f"全局截图快捷键已设置为: {new_hotkey}")
        else:
            messagebox.showwarning("取消", "快捷键未更改。")

    def on_closing(self):
        if HAS_KEYBOARD: keyboard.unhook_all_hotkeys()
        self.root.destroy()

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    # ---------- 截图/剪贴板/拖放 ----------
    def area_capture(self):
        if self.capturing: return
        self.capturing = True
        self.root.iconify()
        self.root.after(200, self._launch_capture)

    def _launch_capture(self):
        ScreenCapture(self.root, self._on_capture_done)

    def _on_capture_done(self, filepath):
        self.capturing = False
        self.root.deiconify()
        self.root.lift()
        if filepath:
            self.refresh_screenshots()
            if self.auto_play_var.get():
                self.play_score(filepath)

    def clipboard_add(self):
        img = ImageGrab.grabclipboard()
        if img is None:
            hotkey = self.config.get('hotkey', DEFAULT_HOTKEY)
            messagebox.showinfo("提示", f"剪贴板中没有图片。\n请先使用系统截图工具（如 Win+Shift+S）截图到剪贴板，或按 {hotkey} 使用区域截图。")
            return
        if isinstance(img, list):
            messagebox.showinfo("提示", "剪贴板中是文件列表，请截图后再试。")
            return
        import datetime
        filename = f"clip_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        save_path = os.path.join(SCREENSHOT_DIR, filename)
        img.save(save_path)
        self.refresh_screenshots()
        if self.auto_play_var.get():
            self.play_score(save_path)

    def on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        for f in files:
            if os.path.isfile(f):
                ext = os.path.splitext(f)[1].lower()
                if ext in ('.png','.jpg','.jpeg','.bmp','.tiff','.gif'):
                    dest = os.path.join(SCREENSHOT_DIR, os.path.basename(f))
                    shutil.copy2(f, dest)
                    self.refresh_screenshots()
                    if self.auto_play_var.get():
                        self.play_score(dest)

    # ---------- 刷新各列表 ----------
    def full_refresh(self):
        self.refresh_screenshots()
        self.refresh_xml_list()
        self.refresh_midi_list()
        self.refresh_sheet_images()

    def refresh_screenshots(self):
        for w in self.scrollable_frame.winfo_children():
            w.destroy()
        self.thumbnails.clear()
        valid_ext = ('.png','.jpg','.jpeg','.bmp','.tiff','.gif')
        files = sorted([f for f in os.listdir(SCREENSHOT_DIR) if f.lower().endswith(valid_ext)])
        row, col = 0, 0
        max_cols = 4
        for f in files:
            filepath = os.path.join(SCREENSHOT_DIR, f)
            thumb = ScoreThumbnail(self.scrollable_frame, filepath,
                                   on_delete=lambda p=filepath: self._on_item_deleted(p),
                                   on_play=self.play_score)
            thumb.grid(row=row, column=col, padx=5, pady=5)
            self.thumbnails[filepath] = thumb
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def _on_item_deleted(self, filepath):
        self.refresh_screenshots()

    # ---------- XML 列表操作 ----------
    def refresh_xml_list(self):
        self.xml_listbox.delete(0, tk.END)
        for f in sorted(os.listdir(XML_DIR)):
            if f.lower().endswith(('.xml','.mxl')):
                self.xml_listbox.insert(tk.END, f)

    def show_xml_menu(self, event):
        try:
            self.xml_listbox.selection_clear(0, tk.END)
            self.xml_listbox.selection_set(self.xml_listbox.nearest(event.y))
            self.xml_menu.post(event.x_root, event.y_root)
        except: pass

    def get_selected_xml(self):
        sel = self.xml_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个 XML 文件。")
            return None
        return os.path.join(XML_DIR, self.xml_listbox.get(sel[0]))

    def open_xml(self):
        path = self.get_selected_xml()
        if path: os.startfile(path)

    def convert_xml_to_midi(self):
        xml_path = self.get_selected_xml()
        if not xml_path: return
        midi_path = os.path.join(MIDI_DIR, os.path.splitext(os.path.basename(xml_path))[0] + ".mid")
        if musicxml_to_midi(xml_path, midi_path):
            messagebox.showinfo("成功", f"已转换为 MIDI：{midi_path}")
            self.refresh_midi_list()
        else:
            messagebox.showerror("失败", "转换失败")

    def play_xml(self):
        xml_path = self.get_selected_xml()
        if not xml_path: return
        midi_path = os.path.join(MIDI_DIR, os.path.splitext(os.path.basename(xml_path))[0] + ".mid")
        if not musicxml_to_midi(xml_path, midi_path):
            messagebox.showerror("失败", "转换 MIDI 失败")
            return
        sf2 = self._check_sf2()
        if not sf2: return
        self.refresh_midi_list()
        threading.Thread(target=lambda: play_midi_file(
            midi_path, sf2, volume=self.volume_var.get(), speed=self.speed_var.get()), daemon=True).start()

    def delete_xml(self):
        path = self.get_selected_xml()
        if path and messagebox.askyesno("确认删除", f"删除 {os.path.basename(path)}？"):
            os.remove(path)
            self.refresh_xml_list()

    # ---------- MIDI 列表操作 ----------
    def refresh_midi_list(self):
        self.midi_listbox.delete(0, tk.END)
        for f in sorted(os.listdir(MIDI_DIR)):
            if f.lower().endswith(('.mid','.midi')):
                self.midi_listbox.insert(tk.END, f)

    def show_midi_menu(self, event):
        try:
            self.midi_listbox.selection_clear(0, tk.END)
            self.midi_listbox.selection_set(self.midi_listbox.nearest(event.y))
            self.midi_menu.post(event.x_root, event.y_root)
        except: pass

    def get_selected_midi(self):
        sel = self.midi_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个 MIDI 文件。")
            return None
        return os.path.join(MIDI_DIR, self.midi_listbox.get(sel[0]))

    def play_midi_file_gui(self):
        midi_path = self.get_selected_midi()
        if not midi_path: return
        sf2 = self._check_sf2()
        if not sf2: return
        threading.Thread(target=lambda: play_midi_file(
            midi_path, sf2, volume=self.volume_var.get(), speed=self.speed_var.get()), daemon=True).start()

    def delete_midi(self):
        path = self.get_selected_midi()
        if path and messagebox.askyesno("确认删除", f"删除 {os.path.basename(path)}？"):
            os.remove(path)
            self.refresh_midi_list()

    # ---------- 关于对话框 ----------
    def show_about(self):
        about = tk.Toplevel(self.root)
        about.title("关于 小花截图MIDI播放工具")
        about.geometry("500x280")
        about.resizable(False, False)
        about.transient(self.root)
        about.grab_set()
        left = tk.Frame(about, width=200, height=280)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left.pack_propagate(False)
        img_label = tk.Label(left)
        img_label.pack(expand=True)
        watermark_path = resource_path("watermark.png")
        if os.path.exists(watermark_path):
            try:
                img = Image.open(watermark_path).convert("RGBA")
                img.thumbnail((180, 180))
                bg_color = left.cget("bg")
                try:
                    rgb = self.root.winfo_rgb(bg_color)
                    r, g, b = [x//256 for x in rgb]
                except:
                    r, g, b = 240,240,240
                bg = Image.new("RGBA", img.size, (r,g,b,255))
                composite = Image.alpha_composite(bg, img)
                photo = ImageTk.PhotoImage(composite)
                img_label.config(image=photo)
                img_label.image = photo
            except Exception as e:
                img_label.config(text="(图片加载失败)")
        else:
            img_label.config(text="(图片缺失)")
        right = tk.Frame(about, width=300, height=280)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        right.pack_propagate(False)
        info = ("小花截图MIDI播放工具\n\n版本 2.0.0\n\n作者：饭吃完了我吃什么\nB站同名，感谢使用！\n\n截图即听，让乐谱活起来")
        tk.Label(right, text=info, justify=tk.LEFT, padx=20, pady=20).pack(fill=tk.BOTH, expand=True)
        ttk.Button(about, text="确定", command=about.destroy).pack(pady=10)

    # ---------- 核心：识别并播放 ----------
    def play_score(self, filepath):
        if filepath in self.processing_files:
            print(f"图片 {filepath} 正在处理中，忽略重复请求。")
            return
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        existing_midi = os.path.join(MIDI_DIR, base_name + ".mid")
        if os.path.exists(existing_midi):
            self.status_text.set("已有 MIDI，直接播放中...")
            sf2 = self._check_sf2()
            if not sf2: return
            threading.Thread(target=play_midi_file,
                             args=(existing_midi, sf2),
                             kwargs={"volume": self.volume_var.get(), "speed": self.speed_var.get()},
                             daemon=True).start()
            return

        if not self.processing_lock.acquire(blocking=False):
            messagebox.showinfo("提示", "正在处理其他乐谱，请稍候。")
            return

        self.status_text.set("正在处理中...")
        self.root.config(cursor="watch")
        self.processing_files.add(filepath)

        def task():
            try:
                actual_xml = recognize(filepath)
                if not actual_xml:
                    self.root.after(0, lambda: messagebox.showerror("识别失败", "未找到生成的 MusicXML 文件。"))
                    return
                dest_name = os.path.basename(actual_xml)
                dest = os.path.join(XML_DIR, dest_name)
                counter = 1
                while os.path.exists(dest):
                    n, e = os.path.splitext(dest_name)
                    dest = os.path.join(XML_DIR, f"{n}_{counter}{e}")
                    counter += 1
                shutil.move(actual_xml, dest)
                actual_xml = dest

                # 自动渲染乐谱图（如果勾选）
                if self.config.get("auto_render", False):
                    self.root.after(0, lambda x=actual_xml: self.render_xml_to_image(x))

                base_midi = os.path.splitext(dest_name)[0] + ".mid"
                mid_output = os.path.join(MIDI_DIR, base_midi)
                counter = 1
                while os.path.exists(mid_output):
                    n, e = os.path.splitext(base_midi)
                    mid_output = os.path.join(MIDI_DIR, f"{n}_{counter}{e}")
                    counter += 1
                if not musicxml_to_midi(actual_xml, mid_output):
                    # 额外检查文件是否存在且有效
                    if os.path.exists(actual_xml) and os.path.getsize(actual_xml) > 100:
                        err = "MusicXML 转 MIDI 出错，可能是识别结果不完整，请重新截图或尝试不同清晰度的图片。"
                    else:
                        err = "生成的 MusicXML 文件无效（过小或不存在），请重新截图。"
                    self.root.after(0, lambda msg=err: messagebox.showerror("转换失败", msg))
                    return
                self.root.after(0, self.refresh_xml_list)
                self.root.after(0, self.refresh_midi_list)

                def play():
                    sf2 = self._check_sf2()
                    if sf2:
                        play_midi_file(mid_output, sf2, volume=self.volume_var.get(), speed=self.speed_var.get())
                self.root.after(0, lambda: threading.Thread(target=play, daemon=True).start())
            except Exception as e:
                err = traceback.format_exc()
                self.root.after(0, lambda msg=err: messagebox.showerror("错误", msg))
            finally:
                self.processing_files.discard(filepath)
                self.processing_lock.release()
                self.root.after(0, self.reset_status)

        threading.Thread(target=task, daemon=True).start()

    def reset_status(self):
        self.status_text.set("就绪")
        self.root.config(cursor="")

if __name__ == "__main__":
    root = tkinterdnd2.Tk()
    app = ScoreBrowserApp(root)
    root.mainloop()