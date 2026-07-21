import os
import tempfile
import threading
import requests
from flask import Flask, request, jsonify
from groq import Groq
from pydub import AudioSegment

app = Flask(__name__)

def download_audio_from_api(video_url, save_path):
    # استخدام سيرفر وسيط لتجاوز حظر يوتيوب تماماً
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "url": video_url,
        "isAudioOnly": True,
        "aFormat": "mp3"
    }
    try:
        response = requests.post("https://api.cobalt.tools/api/json", json=payload, headers=headers)
        if response.status_code == 200:
            audio_link = response.json().get("url")
            if audio_link:
                # تحميل الملف الصوتي الجاهز
                r = requests.get(audio_link)
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                return True
    except:
        pass
    return False

def process_video_background(video_url, webhook_url, groq_key):
    client = Groq(api_key=groq_key)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio.mp3")

            # سحب الصوت عبر الوسيط
            success = download_audio_from_api(video_url, audio_path)
            
            if not success:
                requests.post(webhook_url, json={"status": "error", "error_message": "فشل الوسيط في سحب الصوت، يرجى المحاولة لاحقاً."})
                return

            # التقطيع والتفريغ
            audio = AudioSegment.from_mp3(audio_path)
            chunk_length_ms = 10 * 60 * 1000
            chunks = [audio[i:i+chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            full_text = ""
            for i, chunk in enumerate(chunks):
                chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
                chunk.export(chunk_path, format="mp3", bitrate="64k")

                with open(chunk_path, "rb") as file:
                    transcription = client.audio.transcriptions.create(
                      file=(os.path.basename(chunk_path), file.read()),
                      model="whisper-large-v3",
                    )
                    full_text += transcription.text + " "

            # إرسال النص النهائي إلى n8n
            requests.post(webhook_url, json={"status": "success", "text": full_text})

    except Exception as e:
        requests.post(webhook_url, json={"status": "error", "error_message": str(e)})

@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    url = data.get('url')
    webhook_url = data.get('webhook_url')
    groq_key = os.environ.get("GROQ_API_KEY")

    if not url or not webhook_url:
        return jsonify({"error": "Missing URL or Webhook"}), 400

    thread = threading.Thread(target=process_video_background, args=(url, webhook_url, groq_key))
    thread.start()

    return jsonify({"message": "تم استلام الطلب بنجاح. سيتم إرسال النص المفرغ فور الانتهاء."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
