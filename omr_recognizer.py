# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import subprocess
import sys
import os
import glob
import shutil
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.path.dirname(sys.executable)
TEMP_DIR = os.path.join(BASE_DIR, "temp_audiveris")

def preprocess_image(image_path, output_path=None):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("预处理：读取图片失败，返回原图")
        return image_path

    h, w = img.shape
    target_width = 1200
    if w < target_width:
        scale = target_width / w
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    block_size = max(11, (img.shape[0] // 20) | 1)
    binary = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block_size, 2)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(binary, -1, kernel)

    if output_path is None:
        output_path = image_path + "_preprocessed.png"
    cv2.imwrite(output_path, sharpened)
    return output_path

def recognize(image_path, preprocess=True):
    print(f"[识别] 开始处理: {image_path}")
    if not os.path.exists(image_path):
        print(f"错误：找不到图片文件 {image_path}")
        return None

    # 清理旧临时目录
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # 预处理
    if preprocess:
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        pre_filename = f"pre_{base_name}.png"
        preprocessed_image = os.path.join(TEMP_DIR, pre_filename)
        preprocessed_image = preprocess_image(image_path, preprocessed_image)
    else:
        preprocessed_image = image_path

    # 查找 Audiveris.exe
    audiveris_exe = os.path.join(BASE_DIR, "Audiveris", "Audiveris.exe")
    if not os.path.exists(audiveris_exe):
        audiveris_exe = "Audiveris"  # 尝试系统 PATH

    print(f"[识别] 使用 Audiveris: {audiveris_exe}")

    cmd = [audiveris_exe, "-batch", "-export", "-output", TEMP_DIR, preprocessed_image]
    print(f"[识别] 执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        print(f"[识别] Audiveris 返回码: {result.returncode}")
        if result.stdout:
            print(f"[stdout] {result.stdout[-500:]}")
        if result.stderr:
            print(f"[stderr] {result.stderr[-500:]}")
    except subprocess.TimeoutExpired:
        print("错误：Audiveris 进程超时（超过 2 分钟）")
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        return None
    except FileNotFoundError:
        print("错误：找不到 Audiveris.exe，请检查路径。")
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        return None

    # 从 TEMP_DIR 中查找 .mxl 或 .xml 文件
    xml_files = glob.glob(os.path.join(TEMP_DIR, "*.xml")) + glob.glob(os.path.join(TEMP_DIR, "*.mxl"))
    xml_files = [f for f in xml_files if not f.lower().endswith('.omr')]

    if not xml_files:
        print("警告：未找到 Audiveris 生成的 MusicXML 文件。")
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        return None

    generated = xml_files[0]
    # 移动到 BASE_DIR 下并返回路径
    dest = os.path.join(BASE_DIR, os.path.basename(generated))
    if os.path.abspath(generated) != os.path.abspath(dest):
        shutil.move(generated, dest)
    generated = dest
    print(f"MusicXML 已生成为: {generated}")

    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    return generated