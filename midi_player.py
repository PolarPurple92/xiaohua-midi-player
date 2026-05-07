# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import sys
import os
import ctypes
import time
import tempfile
import mido

# ---------- 动态添加 DLL 搜索路径 ----------
if getattr(sys, 'frozen', False):
    dll_dir = sys._MEIPASS          # 打包后的临时目录
else:
    dll_dir = os.path.dirname(os.path.abspath(__file__))   # 开发环境

# 确保 dll 能被找到 (Python 3.8+)
try:
    os.add_dll_directory(dll_dir)
except AttributeError:
    # Python 3.7 及以下用 PATH
    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

# 拦截 pyfluidsynth 内部的错误路径检查，让其静默失败
try:
    _original = os.add_dll_directory
    def _safe_add_dll_directory(path):
        try:
            _original(path)
        except FileNotFoundError:
            pass   # 忽略不存在的路径（如 C:\tools\fluidsynth\bin）
    os.add_dll_directory = _safe_add_dll_directory
except AttributeError:
    pass

# 现在安全导入 fluidsynth
import fluidsynth
# ------------------------------------------

def resource_path(relative_path):
    """获取资源真实路径（兼容打包与开发环境）"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def get_midi_duration(midi_file, speed=1.0):
    try:
        mid = mido.MidiFile(midi_file)
        tempo = 500000
        ticks_per_beat = mid.ticks_per_beat
        total_ticks = 0
        for track in mid.tracks:
            ticks = 0
            for msg in track:
                ticks += msg.time
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
            total_ticks = max(total_ticks, ticks)
        duration = (total_ticks / ticks_per_beat) * (tempo / 1_000_000)
        return duration / speed
    except Exception:
        return 0.0

def adjust_midi_speed(input_path, output_path, speed):
    mid = mido.MidiFile(input_path)
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                msg.tempo = int(msg.tempo / speed)
    mid.save(output_path)

def play_midi(midi_file, sf2_file="soundfont.sf2", volume=1.0, audio_driver=None, speed=1.0):
    if not os.path.exists(midi_file):
        print(f"错误：找不到 MIDI 文件 {midi_file}")
        return

    # 自动查找音色库
    if not os.path.exists(sf2_file):
        bundled_sf = resource_path(os.path.join("soundfonts", os.path.basename(sf2_file)))
        if os.path.exists(bundled_sf):
            sf2_file = bundled_sf
        else:
            bundled_dir = resource_path("soundfonts")
            if os.path.isdir(bundled_dir):
                sf2_files = [f for f in os.listdir(bundled_dir) if f.lower().endswith('.sf2')]
                if sf2_files:
                    sf2_file = os.path.join(bundled_dir, sf2_files[0])
                    print(f"自动选择音色库: {sf2_file}")
    if not os.path.exists(sf2_file):
        print(f"错误：找不到 SoundFont 文件 {sf2_file}")
        return

    # 速度调整
    temp_midi = None
    actual_midi_file = midi_file
    if abs(speed - 1.0) > 0.001:
        try:
            fd, temp_midi = tempfile.mkstemp(suffix='.mid', prefix='speed_')
            os.close(fd)
            adjust_midi_speed(midi_file, temp_midi, speed)
            actual_midi_file = temp_midi
            print(f"速度调整: {speed}x, 临时文件: {temp_midi}")
        except Exception as e:
            print(f"警告：无法调整速度，将以原速播放。错误: {e}")

    fs = fluidsynth.Synth()
    drivers = ["dsound", "coreaudio", "pulseaudio", "alsa"]
    if audio_driver:
        drivers = [audio_driver] + drivers
    started = False
    for drv in drivers:
        try:
            fs.start(driver=drv)
            print(f"成功使用音频驱动: {drv}")
            started = True
            break
        except:
            continue
    if not started:
        print("错误：无法启动任何音频驱动")
        fs.delete()
        return

    sfid = fs.sfload(sf2_file)
    if sfid < 0:
        print(f"错误：无法加载音色库 {sf2_file}")
        fs.delete()
        return

    fs.program_select(0, sfid, 0, 0)
    try:
        fs.setting('synth.gain', volume)
    except:
        print("警告：设置音量失败")

    duration = get_midi_duration(actual_midi_file, speed=1.0)
    if duration <= 0:
        duration = 3.0

    print(f"正在播放 {actual_midi_file} (预计 {duration:.1f} 秒)...")
    fs.play_midi_file(actual_midi_file)
    time.sleep(duration + 0.5)

    fs.delete()
    print("播放结束")

    if temp_midi and os.path.exists(temp_midi):
        try:
            os.remove(temp_midi)
        except:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python midi_player.py <MIDI文件> [音量] [驱动] [速度]")
    else:
        vol = 1.0
        drv = None
        spd = 1.0
        if len(sys.argv) >= 3: vol = float(sys.argv[2])
        if len(sys.argv) >= 4: drv = sys.argv[3]
        if len(sys.argv) >= 5: spd = float(sys.argv[4])
        play_midi(sys.argv[1], volume=vol, audio_driver=drv, speed=spd)