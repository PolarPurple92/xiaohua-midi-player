# Copyright (c) 2026 饭吃完了我吃什么 (B站同名)
# Licensed under the MIT License
import subprocess
import sys
import os
import glob
import cv2
import numpy as np
import shutil

# 项目根目录
if getattr(sys, 'frozen', False):
    # 打包成 EXE 后，使用 EXE 所在目录
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 直接用 Python 脚本运行时，使用脚本所在目录
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Audiveris 临时工作目录（所有非 MusicXML 文件都会放在这里）
TEMP_DIR = os.path.join(BASE_DIR, "temp_audiveris")

def preprocess_image(image_path, output_path=None):
    """对乐谱截图进行预处理，返回输出路径"""
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
    """
    使用 Audiveris 识别乐谱截图，返回生成的 MusicXML 文件路径（或 None）。
    所有临时文件放在 TEMP_DIR 中，识别后清理。
    """
    if not os.path.exists(image_path):
        print(f"错误：找不到图片文件 {image_path}")
        return None

    # 准备临时工作目录（每次都清空）
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # 预处理（如果需要）
    if preprocess:
        # 预处理后的图片也存到 TEMP_DIR，避免根目录污染
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        pre_filename = f"pre_{base_name}.png"
        preprocessed_image = os.path.join(TEMP_DIR, pre_filename)
        preprocessed_image = preprocess_image(image_path, preprocessed_image)
    else:
        preprocessed_image = image_path

    # Audiveris 可执行文件路径
    audiveris_exe = os.path.join(BASE_DIR, "Audiveris", "Audiveris.exe")
    if not os.path.exists(audiveris_exe):
        audiveris_exe = "Audiveris"

    # 构建命令：输出目录指定为 TEMP_DIR
    cmd = [audiveris_exe, "-batch", "-export", "-output", TEMP_DIR, preprocessed_image]
    print(f"执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        print(f"[Audiveris] 返回码: {result.returncode}")
        if result.stdout:
            print(f"[stdout]\n{result.stdout}")
        if result.stderr:
            print(f"[stderr]\n{result.stderr}")
    except subprocess.TimeoutExpired:
        print("错误：Audiveris 进程超时（超过 2 分钟）")
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        return None
    except FileNotFoundError:
        print("错误：找不到 Audiveris.exe，请检查路径。")
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        return None

    # 从 TEMP_DIR 中查找生成的 MusicXML 文件（.xml / .mxl，排除 .omr）
    xml_files = glob.glob(os.path.join(TEMP_DIR, "*.xml")) + glob.glob(os.path.join(TEMP_DIR, "*.mxl"))
    xml_files = [f for f in xml_files if not f.lower().endswith('.omr')]

    generated = None
    if xml_files:
        # 取第一个，移动到根目录
        generated = xml_files[0]
        dest = os.path.join(BASE_DIR, os.path.basename(generated))
        if os.path.abspath(generated) != os.path.abspath(dest):
            shutil.move(generated, dest)
        generated = dest
        print(f"MusicXML 已生成为: {generated}")
    else:
        print("警告：未找到 Audiveris 生成的 MusicXML 文件。")

    # 清理整个临时目录
    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    return generated