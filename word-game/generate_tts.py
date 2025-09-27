import os
import pyttsx3

# 初始化 TTS 引擎
engine = pyttsx3.init()

# 設定語音屬性 (可以調整)
engine.setProperty("rate", 150)   # 語速
engine.setProperty("volume", 1.0) # 音量

input_dir = "images"
output_dir = "audios"

for root, dirs, files in os.walk(input_dir):
    for file in files:
        if file.endswith(".png"):
            word = os.path.splitext(file)[0]  # 檔名當文字
            rel_path = os.path.relpath(root, input_dir)  # 例如 xxx
            out_dir = os.path.join(output_dir, rel_path)
            os.makedirs(out_dir, exist_ok=True)

            out_file = os.path.join(out_dir, f"{word}.wav")
            print(f"生成語音: {word} -> {out_file}")

            engine.save_to_file(word.replace("_", " "), out_file)

# 最後執行一次 runAndWait() 才會真正輸出檔案
engine.runAndWait()

