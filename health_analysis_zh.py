# -*- coding: utf-8 -*-
import os
import logging
import smtplib
import traceback
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

# --- Language Constants (zh for Simplified Chinese) ---
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
    except:
        return 0

# --- AI Prompt Builders ---
# (unchanged build_summary_prompt and build_suggestions_prompt)

def build_summary_prompt(age, gender, country, concern, notes, metrics):
    metrics_summary = ", ".join([
        f"{label} ({value}%)" for block in metrics for label, value in zip(block["labels"], block["values"])][:9]
    )
    return (
        f"任务：为一位来自 {country} 的 {age} 岁 {gender} 撰写一份四段式的健康分析，其主要问题是“{concern}”。请使用以下数据：{metrics_summary}。\n\n"
        "1. 深入分析：不要只重复数据。请解释这些百分比..."
        # full prompt omitted for brevity
    )

def build_suggestions_prompt(age, gender, country, concern, notes):
    return (
        f"为一位来自 {country}、{age} 岁、关注“{concern}”的“{gender}”，提出 10 项具体而温和的生活方式改善建议。"
        # full prompt omitted
    )

# --- OpenAI Helpers ---
def get_openai_response(prompt, temp=0.7):
    try:
        res = client.chat.completions.create(
            model="gpt-4o", messages=[{"role":"user","content":prompt}], temperature=temp
        )
        return res.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return "⚠️ 无法生成回应。"

def generate_metrics_with_ai(prompt):
    try:
        # generate and parse metrics blocks
        ...
    except Exception as e:
        logging.error(f"Metrics error: {e}")
        return [{"title":"默认指标","labels":["指标A","指标B"],"values":[50,75]}]

# --- HTML Footer ---
def generate_footer_html():
    return """
<div style='margin-top:40px; ...'>
  <!-- footer content -->
</div>
"""

# --- Email Helper ---
def send_email(html_body, lang):
    subject = LANGUAGE[lang]['email_subject']
    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = SMTP_USERNAME
    msg['To'] = SMTP_USERNAME
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        logging.info("✅ 已发送邮件: %s", subject)

# --- Flask Endpoint ---
@app.route('/health_analyze', methods=['POST'])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get('lang','zh').lower()
        labels = LANGUAGE_TEXTS[lang]
        content_lang = LANGUAGE[lang]

        # parse dob & compute age
        dob = f"{data['dob_year']}-{int(data['dob_month']):02d}-{int(data['dob_day']):02d}"
        age = compute_age(dob)

        # build metrics via AI
        chart_prompt = ( ... )
        metrics = generate_metrics_with_ai(chart_prompt)

        # build narrative
        summary = get_openai_response(build_summary_prompt(age, ...), temp=0.7)
        suggestions = get_openai_response(build_suggestions_prompt(age, ...), temp=0.85)

        # assemble html_result
        html_result = '<div style="font-family:sans-serif;">'
        html_result += ...  # summary & suggestions & footer
        html_result += generate_footer_html()

        # --- SEND EMAIL ---
        # build simple metrics table
        metrics_table = ''
        for block in metrics:
            metrics_table += f"<h4>{block['title']}</h4>"
            for lbl, val in zip(block['labels'], block['values']):
                metrics_table += f"<p>{lbl}: {val}%</p>"
        # combine and send
        send_email(metrics_table + html_result, lang)

        # return JSON
        return jsonify({
            'metrics': metrics,
            'html_result': html_result,
            'footer': labels['footer'],
            'report_title': content_lang['report_title']
        })

    except Exception as e:
        logging.error(f"Error in health_analyze: {e}")
        traceback.print_exc()
        return jsonify({'error':'服务器内部错误'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT',5000)), debug=True)
