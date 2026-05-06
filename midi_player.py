# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import fluidsynth
import sys
import os
import time
import tempfile
import mido
import shutil

def get_midi_duration(midi_file, speed=1.0):
    """
    计算 MIDI 文件的总播放时长（秒），考虑速度因子。
    返回 float 秒数，如果无法计算则返回 0。
    """
    try:
        mid = mido.MidiFile(midi_file)
        tempo = 500000  # 默认 120 BPM (微秒每四分音符)
        ticks_per_beat = mid.ticks_per_beat
        total_ticks = 0
        for track in mid.tracks:
            ticks = 0
            for msg in track:
                ticks += msg.time
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
            total_ticks = max(total_ticks, ticks)
        # 计算总时长 (秒) = (total_ticks / ticks_per_beat) * (tempo / 1_000_000)
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
        base = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()
        sf_dir = os.path.join(base, "soundfonts")
        if os.path.isdir(sf_dir):
            sf2_files = [f for f in os.listdir(sf_dir) if f.lower().endswith('.sf2')]
            if sf2_files:
                sf2_file = os.path.join(sf_dir, sf2_files[0])
                print(f"自动选择音色库: {sf2_file}")

    if not os.path.exists(sf2_file):
        print(f"错误：找不到 SoundFont 文件 {sf2_file}")
        return

    # 处理速度（非 1.0 时生成临时变速文件）
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
            actual_midi_file = midi_file

    # 初始化 FluidSynth
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

    # 计算预计播放时长
    duration = get_midi_duration(actual_midi_file, speed=1.0)  # 已经在文件里改了速度，所以speed传1.0即可
    if duration <= 0:
        duration = 3.0  # 回退默认等待

    print(f"正在播放 {actual_midi_file} (预计 {duration:.1f} 秒)...")
    fs.play_midi_file(actual_midi_file)

    # 等待音频完全输出
    time.sleep(duration + 0.5)  # 多缓冲 0.5 秒确保播放结束

    fs.delete()
    print("播放结束")

    # 清理临时变速文件
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
        if len(sys.argv) >= 3:
            try:
                vol = float(sys.argv[2])
            except:
                pass
        if len(sys.argv) >= 4:
            drv = sys.argv[3]
        if len(sys.argv) >= 5:
            try:
                spd = float(sys.argv[4])
            except:
                pass
        play_midi(sys.argv[1], volume=vol, audio_driver=drv, speed=spd)