# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import fluidsynth
import sys
import os
import time
import tempfile
import mido   # 用于调整 MIDI 速度
import shutil

def adjust_midi_speed(input_path, output_path, speed):
    """
    读取 MIDI 文件，将所有 SetTempo 事件的速度按 speed 倍率调整，
    保存为新文件。
    speed=1.0  => 不变
    speed=2.0  => 快一倍（tempo 值减半）
    speed=0.5  => 慢一倍
    """
    mid = mido.MidiFile(input_path)
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                # tempo 单位是微秒每四分音符，速度加倍则 tempo 减半
                msg.tempo = int(msg.tempo / speed)
    mid.save(output_path)

def play_midi(midi_file, sf2_file="soundfont.sf2", volume=1.0, audio_driver=None, speed=1.0):
    if not os.path.exists(midi_file):
        print(f"错误：找不到 MIDI 文件 {midi_file}")
        return

    # 自动查找音色库（优先 soundfonts 文件夹，再回退根目录）
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

    # ----- 速度处理：如果 speed != 1.0，生成临时变速 MIDI -----
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
    # -------------------------------------------

    fs = fluidsynth.Synth()

    # 驱动选择
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

    # 设置音量
    try:
        fs.setting('synth.gain', volume)
    except:
        print("警告：设置音量失败")

    print(f"正在播放 {actual_midi_file} ...")
    fs.play_midi_file(actual_midi_file)

    # 等待播放完成（通过轮询状态）
    while fs.get_status() == fluidsynth.FLUID_PLAYER_PLAYING:
        time.sleep(0.1)

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