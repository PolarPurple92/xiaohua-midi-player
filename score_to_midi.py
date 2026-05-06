# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import sys
import os
from music21 import converter

def musicxml_to_midi(xml_file, midi_file="output.mid"):
    if not os.path.exists(xml_file):
        print(f"错误：找不到文件 {xml_file}")
        return False
    try:
        score = converter.parse(xml_file)  # music21 自动处理 .xml 和 .mxl
        score.write("midi", midi_file)
        print(f"转换成功：{xml_file} → {midi_file}")
        return True
    except Exception as e:
        print(f"转换失败：{e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python score_to_midi.py <MusicXML或MXL文件> [输出MIDI文件]")
    else:
        xml_in = sys.argv[1]
        midi_out = sys.argv[2] if len(sys.argv) > 2 else "output.mid"
        musicxml_to_midi(xml_in, midi_out)