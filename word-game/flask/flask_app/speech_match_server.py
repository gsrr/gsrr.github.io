#!/usr/bin/env python3
import socket
import json
import os
import torchaudio
from speechbrain.pretrained import EncoderClassifier
from scipy.spatial.distance import cosine

# 載入 SpeechBrain speaker embedding 模型
classifier = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir="pretrained_models/spkrec-ecapa-voxceleb"
)

def get_embedding(wav_path):
    signal, fs = torchaudio.load(wav_path)
    if signal.shape[0] > 1:  # 轉單聲道
        signal = signal.mean(dim=0, keepdim=True)
    if fs != 16000:  # 重采樣
        signal = torchaudio.functional.resample(signal, fs, 16000)
    emb = classifier.encode_batch(signal)
    return emb.squeeze().detach().cpu().numpy()

def match_word(user_wav, story, words, base_dir="audios"):
    user_vec = get_embedding(user_wav)
    best_word, best_score = None, float("inf")
    scores = {}
    for word in words:
        ref_wav = os.path.join(base_dir, story, f"{word}.wav")
        if not os.path.exists(ref_wav):
            scores[word] = None
            continue
        ref_vec = get_embedding(ref_wav)
        score = cosine(user_vec, ref_vec)
        scores[word] = float(score)
        if score < best_score:
            best_score = score
            best_word = word
    return {"best_match": best_word, "scores": scores}

def handle_request(req_json):
    try:
        user_wav = req_json["audio"]
        story = req_json["story"]
        words = req_json["words"]
        result = match_word(user_wav, story, words)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})

def start_server(host="127.0.0.1", port=6000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))
        s.listen()
        print(f"✅ speech_match server listening on {host}:{port}")
        while True:
            conn, addr = s.accept()
            with conn:
                data = conn.recv(65536).decode("utf-8")
                if not data:
                    continue
                try:
                    req = json.loads(data)
                    resp = handle_request(req)
                except Exception as e:
                    resp = json.dumps({"error": f"Invalid request: {e}"})
                conn.sendall(resp.encode("utf-8"))

if __name__ == "__main__":
    start_server()

