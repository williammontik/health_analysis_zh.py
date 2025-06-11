# -*- coding: utf-8 -*-
import os, logging, smtplib, traceback
from datetime import datetime
from dateutil import parser
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.DEBUG)

# --- Config ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "kata.chatbot@gmail.com"
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# --- Language Constants (zh-TW for Traditional Chinese) ---
LANGUAGE = {
    "zh-TW": {
        "email_subject": "您的健康洞察報告",
        "report_title": "🎉 全球健康洞察報告"
    }
}

LANGUAGE_TEXTS = {
    "zh-TW": {
        "name": "法定全名", "dob": "出生日期", "country": "國家", "gender": "性別",
        "age": "年齡", "height": "身高 (公分)", "weight": "體重 (公斤)", "concern": "主要問題",
        "desc": "補充說明", "ref": "推薦人", "angel": "健康夥伴",
        "footer": "📩 此報告已透過電子郵件發送給您。所有內容均由 KataChat AI 生成，並符合個資法規定。"
    }
}

# --- Utility ---
def compute_age(dob):
    try:
        dt = parser.parse(dob)
        today = datetime.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except: return 0

# --- AI Prompts (Traditional Chinese) ---
def build_summary_prompt(age, gender, country, concern, notes, metrics):
    metrics_summary = ", ".join([f"{label} ({value}%)" for block in metrics for label, value in zip(block["labels"], block["values"])][:9])
    return (
        f"任務：為一位來自 {country} 的 {age} 歲 {gender} 撰寫一份四段式的健康分析，其主要問題是「{concern}」。請使用以下數據：{metrics_summary}。\n\n"
        f"指令：\n"
        f"1. **深入分析**：不要只重複數據。請解釋這些百分比數字對這個用戶群體意味著什麼，並分析它們之間的聯繫。例如，高皮脂分泌如何影響皮膚問題。\n"
        f"2. **內容豐富**：每個段落都應提供有價值的見解和背景資訊，使其內容充實。\n"
        f"3. **專業且匿名**：語氣應充滿同理心但專業。嚴禁使用「你」、「我」等代詞。請使用「該年齡段的女性…」或「來自 {country} 的個體…」等措辭。\n"
        f"4. **整合數據**：每段話中都必須自然地融入至少一個具體的百分比數據。"
    )

def build_suggestions_prompt(age, gender, country, concern, notes):
    return (
        f"為一位來自 {country}、{age} 歲、關注「{concern}」的「{gender}」，提出 10 項具體而溫和的生活方式改善建議。"
        f"請使用溫暖、支持的語氣，並包含有幫助的表情符號。"
        f"建議應實用、符合文化習慣且具滋養性。"
        f"⚠️ **嚴格指令**：請勿使用姓名、代詞（她/她的/他/他的）或「該個體」等詞語。"
        f"僅使用如「在 {country} 60多歲的女性」或「面臨此問題的個體」等描述。"
    )

# --- OpenAI Interaction ---
def get_openai_response(prompt, temp=0.7):
    try:
        result = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=temp
        )
        return result.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return "⚠️ 無法生成回應。"

def generate_metrics_with_ai(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.7
        )
        lines = res.choices[0].message.content.strip().split("\n")
        metrics = []
        current_title, labels, values = "", [], []
        for line in lines:
            if line.startswith("###"):
                if current_title: metrics.append({"title": current_title, "labels": labels, "values": values})
                current_title, labels, values = line.replace("###", "").strip(), [], []
            elif ":" in line:
                try:
                    label, val = line.split(":", 1)
                    labels.append(label.strip())
                    values.append(int(val.strip().replace("%", "")))
                except ValueError: continue
        if current_title: metrics.append({"title": current_title, "labels": labels, "values": values})
        return metrics or [{"title": "預設指標", "labels": ["指標A", "指標B"], "values": [50, 75]}]
    except Exception as e:
        logging.error(f"Chart parse error: {e}")
        return [{"title": "預設指標", "labels": ["指標A", "指標B"], "values": [50, 75]}]

# --- HTML & Email Generation ---
def generate_footer_html():
    return """
    <div style="margin-top: 40px; border-left: 4px solid #4CAF50; padding-left: 15px; font-family: sans-serif;">
        <h3 style="font-size: 22px; font-weight: bold; color: #333;">📊 由 KataChat AI 生成的見解</h3>
        <p style="font-size: 18px; color: #555; line-height: 1.6;">
            此健康報告是使用 KataChat 的專有 AI 模型生成的，基於：
        </p>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 18px; color: #555; line-height: 1.6;">
            <li>來自新加坡、馬來西亞和台灣用戶的匿名健康與生活方式資料庫</li>
            <li>來自可信的 OpenAI 研究數據庫的全球健康基準和行為趨勢數據</li>
        </ul>
        <p style="font-size: 18px; color: #555; line-height: 1.6;">
            所有分析嚴格遵守個人資料保護法規，以保護您的個人資料，同時發掘有意義的健康洞察。
        </p>
        <p style="font-size: 18px; color: #555; line-height: 1.6; margin-top: 15px;">
            🛡️ <strong>請注意：</strong>本報告並非醫療診斷。若有任何嚴重的健康問題，請諮詢持牌醫療專業人員。
        </p>
        <p style="font-size: 18px; color: #555; line-height: 1.6; margin-top: 15px;">
            📬 <strong>附註：</strong>個人化報告將在 24-48 小時內發送到您的電子郵件。若您想更詳細地探討報告結果，我們很樂意安排一個 15 分鐘的簡短通話。
        </p>
    </div>
    """

def send_email(html_body, lang):
    subject = LANGUAGE.get(lang, {}).get("email_subject", "Health Report")
    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = SMTP_USERNAME
    msg['To'] = SMTP_USERNAME
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
            logging.info(f"Email sent to {SMTP_USERNAME} for language {lang}")
    except Exception as e:
        logging.error(f"Email send error: {e}")

# --- Flask Endpoint ---
@app.route("/health_analyze", methods=["POST"])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get("lang", "zh-TW").strip()

        if lang not in LANGUAGE:
            return jsonify({"error": f"Language '{lang}' not supported."}), 400

        labels = LANGUAGE_TEXTS[lang]
        content_lang = LANGUAGE[lang]
        
        dob = f"{data.get('dob_year')}-{str(data.get('dob_month')).zfill(2)}-{str(data.get('dob_day')).zfill(2)}"
        age = compute_age(dob)
        
        user_info = {k: data.get(k) for k in ["name", "chinese_name", "gender", "height", "weight", "country", "condition", "referrer", "angel"]}
        user_info.update({"dob": dob, "age": age, "notes": data.get("details") or "無補充說明"})

        chart_prompt = (
            f"這是一位來自 {user_info['country']} 的 {user_info['age']} 歲 {user_info['gender']}，其健康問題為「{user_info['condition']}」。補充說明：{user_info['notes']}\n\n"
            f"請根據此問題生成 3 個不同的健康相關指標類別，每個類別以 '###' 開頭，並包含 3 個指標。"
        )

        metrics = generate_metrics_with_ai(chart_prompt)
        
        summary_prompt = build_summary_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'], metrics)
        summary = get_openai_response(summary_prompt)
        if "⚠️" in summary: summary = "💬 由於系統延遲，摘要暫時無法使用。"

        suggestions_prompt = build_suggestions_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'])
        creative = get_openai_response(suggestions_prompt, temp=0.85)
        if "⚠️" in creative: creative = "💡 目前無法載入建議。請稍後再試。"

        html_result = "<div style='font-family: sans-serif; color: #333;'>"
        html_result += "<div style='font-size:24px; font-weight:bold; margin-top:30px;'>🧠 摘要:</div>"
        html_result += "".join([f"<p style='line-height:1.7; font-size:16px; margin-top:1em; margin-bottom:1em;'>{p.strip()}</p>" for p in summary.strip().split('\n\n') if p.strip()])
        
        html_result += "<div style='font-size:24px; font-weight:bold; margin-top:40px;'>💡 生活建議:</div>"
        html_result += "".join([f"<p style='margin:16px 0; font-size:17px; line-height:1.6;'>{line}</p>" for line in creative.split("\n") if line.strip()])
        
        html_result += generate_footer_html() + "</div>"
        
        # **FIXED: THIS SECTION WAS MISSING AND IS NOW RE-ADDED**
        # --- Build and Send Full Email ---
        charts_html = "<div style='margin-top:30px;'><strong style='font-size:18px;'>📈 健康指標分析:</strong><br><br>"
        for block in metrics:
            charts_html += f"<h4 style='margin-bottom:6px; margin-top:20px;'>{block['title']}</h4>"
            for label, value in zip(block['labels'], block['values']):
                charts_html += f"<div style='margin:6px 0;'><span style='font-size:15px;'>{label}: {value}%</span><br><div style='background:#eee; border-radius:6px; width:100%; max-width:500px; height:14px;'><div style='width:{value}%; background:#4CAF50; height:14px; border-radius:6px;'></div></div></div>"
        charts_html += "</div>"

        data_table = f"<div style='margin-top:20px; font-size:16px; font-family: sans-serif;'><strong>📌 您提交的資訊:</strong><br><br><ul style='line-height:1.8; padding-left:18px;'>"
        for key, value in user_info.items():
            label_text = labels.get(key, key.replace('_', ' ').title())
            if key == 'chinese_name': label_text = "🈶 中文姓名"
            data_table += f"<li><strong>{label_text}:</strong> {value}</li>"
        data_table += "</ul></div>"

        full_email_html = data_table + html_result.replace('sans-serif', 'Arial, sans-serif') + charts_html
        send_email(full_email_html, lang)
        # **END OF FIXED SECTION**
        
        return jsonify({
            "metrics": metrics,
            "html_result": html_result,
            "footer": labels.get('footer'),
            "report_title": content_lang.get('report_title')
        })

    except Exception as e:
        logging.error(f"Health analyze error: {e}")
        traceback.print_exc()
        return jsonify({"error": "發生未預期的伺服器錯誤。"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5000)), host="0.0.0.0")
