# -*- coding: utf-8 -*-
import os, logging, smtplib, traceback, re
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

# --- Language Constants (Simplified Chinese) ---
LANGUAGE = {
    "zh": {
        "email_subject": "您的健康洞察报告",
        "report_title": "🎉 全球健康洞察报告"
    }
}

LANGUAGE_TEXTS = {
    "zh": {
        "name": "法定全名", "dob": "出生日期", "country": "国家", "gender": "性别",
        "age": "年龄", "height": "身高 (厘米)", "weight": "体重 (公斤)", "concern": "主要问题",
        "desc": "补充说明", "ref": "推荐人", "angel": "健康伙伴",
        "footer": "📩 此报告已通过电子邮件发送给您。所有内容均由 KataChat AI 生成，并符合个人信息保护法规定。"
    }
}

# --- Utility ---
def compute_age(dob):
    try:
        dt = parser.parse(dob)
        today = datetime.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except: return 0

# --- AI Prompts (Simplified Chinese - Rewritten for Speed) ---
def build_summary_prompt(age, gender, country, concern, notes, metrics):
    """
    **FINAL FIX:** This prompt is extremely simple and direct to ensure maximum speed.
    """
    metrics_summary = ", ".join([f"{label} ({value}%)" for block in metrics for label, value in zip(block["labels"], block["values"])][:9])
    return (
        f"为一位 {age} 岁的 {gender}（来自 {country}，主要问题：“{concern}”）写一篇4段的健康总结。"
        f"必须使用这些数据：{metrics_summary}。"
        f"分析数据并解释其含义。每段必须包含至少一个百分比。不要用“你”或“您”。"
    )

def build_suggestions_prompt(age, gender, country, concern, notes):
    """
    **FINAL FIX:** This prompt is also simplified for speed.
    """
    return (
        f"为一位 {age} 岁的 {gender}（来自 {country}，问题：“{concern}”）建议10个生活方式的改善点。"
        f"使用表情符号。不要用“你”或“您”。"
    )

# --- OpenAI Interaction ---
def get_openai_response(prompt, temp=0.7):
    try:
        result = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=temp
        )
        return result.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return "⚠️ 无法生成回应。"

def generate_metrics_with_ai(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        lines = res.choices[0].message.content.strip().split("\n")
        metrics = []
        current_title, labels, values = "", [], []
        for line in lines:
            if line.startswith("###"):
                if current_title and labels and values:
                    metrics.append({"title": current_title, "labels": labels, "values": values})
                current_title, labels, values = line.replace("###", "").strip(), [], []
            elif ":" in line:
                try:
                    label, val = line.split(":", 1)
                    labels.append(label.strip())
                    values.append(int(val.strip().replace("%", "")))
                except ValueError: continue
        if current_title and labels and values:
            metrics.append({"title": current_title, "labels": labels, "values": values})
        return metrics or [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50, 75]}]
    except Exception as e:
        logging.error(f"Chart parse error: {e}")
        return [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50, 75]}]

# --- HTML & Email Generation ---
def generate_footer_html():
    return """
    <div style="margin-top: 40px; border-left: 4px solid #4CAF50; padding-left: 15px; font-family: sans-serif;">
        <h3 style="font-size: 22px; font-weight: bold; color: #333;">📊 由 KataChat AI 生成的见解</h3>
        <p style="font-size: 18px; color: #555; line-height: 1.6;">
            此健康报告是使用 KataChat 的专有 AI 模型生成的，基于：
        </p>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 18px; color: #555; line-height: 1.6;">
            <li>来自新加坡、马来西亚和台湾用户的匿名健康与生活方式资料库</li>
            <li>来自可信的 OpenAI 研究数据库的全球健康基准和行为趋势数据</li>
        </ul>
        <p style="font-size: 18px; color: #555; line-height: 1.6;">
            所有分析严格遵守个人数据保护法规，以保护您的个人资料，同时发掘有意义的健康洞察。
        </p>
        <p style="font-size: 18px; color: #555; line-height: 1.6; margin-top: 15px;">
            🛡️ <strong>请注意：</strong>本报告并非医疗诊断。若有任何严重的健康问题，请咨询持牌医疗专业人员。
        </p>
        <p style="font-size: 18px; color: #555; line-height: 1.6; margin-top: 15px;">
            📬 <strong>附注：</strong>个性化报告将在 24-48 小时内发送到您的电子邮箱。若您想更详细地探讨报告结果，我们很乐意安排一个 15 分钟的简短通话。
        </p>
    </div>
    """

def send_email(html_body, lang):
    subject = LANGUAGE.get(lang, {"email_subject": "Health Report"})['email_subject']
    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = SMTP_USERNAME
    msg['To'] = SMTP_USERNAME
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        logging.error(f"Email send error: {e}")

# --- Flask Endpoints (Structure matches working English version) ---
@app.route("/health_analyze", methods=["POST"])
def health_analyze():
    try:
        data = request.get_json(force=True)
        logging.debug(f"POST received: {data}")

        lang = data.get("lang", "zh").strip().lower()
        labels = LANGUAGE_TEXTS.get(lang, LANGUAGE_TEXTS["zh"])
        
        dob = f"{data.get('dob_year')}-{str(data.get('dob_month')).zfill(2)}-{str(data.get('dob_day')).zfill(2)}"
        age = compute_age(dob)
        
        user_info = {
            "name": data.get("name"), "chinese_name": data.get("chinese_name"), "dob": dob, "age": age,
            "gender": data.get("gender"), "height": data.get("height"), "weight": data.get("weight"),
            "country": data.get("country"), "condition": data.get("condition"),
            "notes": data.get("details") or "无补充说明",
            "ref": data.get("referrer"), "angel": data.get("angel")
        }

        chart_prompt = (
             f"这是一位来自 {user_info['country']} 的 {user_info['age']} 岁 {user_info['gender']}，其健康问题为“{user_info['condition']}'。补充说明：{user_info['notes']}\n\n"
             f"请根据此问题生成 3 个不同的健康相关指标类别，每个类别以 '###' 开头，并包含 3 个指标。"
        )
        metrics = generate_metrics_with_ai(chart_prompt)

        summary_prompt = build_summary_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'], metrics)
        summary = get_openai_response(summary_prompt)
        if "⚠️" in summary:
            summary = "💬 摘要暂时无法使用。"

        suggestions_prompt = build_suggestions_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'])
        creative = get_openai_response(suggestions_prompt, temp=0.85)
        if "⚠️" in creative:
            creative = "💡 生活建议目前无法载入。"

        summary_clean = re.sub(r'(\n\s*\n)+', '\n', summary.strip())
        html_result = f"<div style='font-size:24px; font-weight:bold; margin-top:30px;'>🧠 摘要:</div><br>"
        html_result += f"<div style='line-height:1.7; font-size:16px; margin-bottom:4px;'>{summary_clean.replace(chr(10), '<br>')}</div>"
        html_result += f"<div style='font-size:24px; font-weight:bold; margin-top:30px;'>💡 生活建议:</div><br>"
        html_result += ''.join([f"<p style='margin:16px 0; font-size:17px;'>{line}</p>" for line in creative.split("\n") if line.strip()])
        html_result += generate_footer_html()

        charts_html = "<div style='margin-top:30px;'><strong style='font-size:18px;'>📈 健康指标分析:</strong><br><br>"
        for block in metrics:
            charts_html += f"<h4 style='margin-bottom:6px; margin-top:20px;'>{block['title']}</h4>"
            for label, value in zip(block['labels'], block['values']):
                charts_html += f"""
                <div style='margin:6px 0;'><span style='font-size:15px;'>{label}: {value}%</span><br>
                    <div style='background:#eee; border-radius:6px; width:100%; max-width:500px; height:14px;'>
                        <div style='width:{value}%; background:#4CAF50; height:14px; border-radius:6px;'></div>
                    </div></div>"""
        charts_html += "</div>"

        data_table = f"""
        <div style='margin-top:20px; font-size:16px; font-family: sans-serif;'>
            <strong>📌 您提交的信息:</strong><br><br>
            <ul style='line-height:1.8; padding-left:18px;'>
                <li><strong>{labels['name']}:</strong> {user_info['name']}</li>
                <li><strong>🈶 中文姓名:</strong> {user_info['chinese_name']}</li>
                <li><strong>{labels['dob']}:</strong> {user_info['dob']}</li>
                <li><strong>{labels['age']}:</strong> {user_info['age']}</li>
                <li><strong>{labels['gender']}:</strong> {user_info['gender']}</li>
                <li><strong>{labels['country']}:</strong> {user_info['country']}</li>
                <li><strong>{labels['height']}:</strong> {user_info['height']} cm</li>
                <li><strong>{labels['weight']}:</strong> {user_info['weight']} kg</li>
                <li><strong>{labels['concern']}:</strong> {user_info['concern']}</li>
                <li><strong>{labels['desc']}:</strong> {user_info['notes']}</li>
                <li><strong>{labels['ref']}:</strong> {user_info['ref']}</li>
                <li><strong>{labels['angel']}:</strong> {user_info['angel']}</li>
            </ul></div>"""
        
        full_email_html = data_table + html_result.replace('sans-serif', 'Arial, sans-serif') + charts_html
        send_email(full_email_html, lang)

        return jsonify({
            "metrics": metrics,
            "html_result": html_result,
            "footer": labels['footer']
        })

    except Exception as e:
        logging.error(f"Health analyze error: {e}")
        traceback.print_exc()
        return jsonify({"error": "发生未预期的服务器错误。"}), 500

# WAKEUP ENDPOINT TO PREVENT TIMEOUTS
@app.route("/wakeup", methods=["GET"])
def wakeup():
    """
    This endpoint does nothing but return a success message.
    Its only purpose is to wake up a sleeping server on a free tier.
    """
    return jsonify({"status": "I am awake."})


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5000)), host="0.0.0.0")
