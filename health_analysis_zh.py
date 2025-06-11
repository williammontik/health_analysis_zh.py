# -*- coding: utf-8 -*-
import os, logging, smtplib, traceback, io, base64, re
from datetime import datetime
from dateutil import parser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# Non-interactive backend for matplotlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# --- Config ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "kata.chatbot@gmail.com"
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# --- Language Constants ---
LANGUAGE = {
    "zh": {
        "email_subject": "您的健康洞察报告",
        "report_title": "🎉 全球健康洞察报告"
    }
}
LANGUAGE_TEXTS = {
    "zh": {
        "name": "法定全名", "chinese_name": "中文姓名", "dob": "出生日期", "country": "国家", "gender": "性别",
        "age": "年龄", "height": "身高 (厘米)", "weight": "体重 (公斤)", "condition": "主要问题",
        "details": "补充说明", "referrer": "推荐人", "angel": "健康伙伴",
        "footer": "📩 此报告已通过电子邮件发送给您。所有内容均由 KataChat AI 生成，并符合个人信息保护法规定。"
    }
}

# Utility
def compute_age(dob):
    try:
        dt = parser.parse(dob)
        today = datetime.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except:
        return 0

# AI Prompts
def build_summary_prompt(age, gender, country, condition, notes, metrics):
    metrics_summary = ", ".join([
        f"{label} ({value}% )"
        for block in metrics for label, value in zip(block["labels"], block["values"])])[:9]
    return (
        f"任务：为一位来自 {country} 的 {age} 岁 {gender} 撰写一份四段式的健康分析，其主要问题是“{condition}”。\n\n"
        "请严格遵守以下格式要求：\n"
        "1. 首句格式：每段开头请使用“在相似群体中的"
        f"{age}岁{gender}”或“在该年龄段的{age}岁个体中”，不要使用“在分析…时”或“在…的…中”。\n"
        "2. 深入分析：不要只重复数据。请解释百分比数字对该人群意味着什么，并分析它们的联系。\n"
        "3. 内容丰富：每段都应提供有价值的见解和背景信息，使内容充实。\n"
        "4. 专业且匿名：语气应充满同理心但专业。严禁使用“你”“我”等代词。\n"
        "5. 整合数据：每段中自然融入至少一个具体百分比数据。\n\n"
        f"数据摘要：{metrics_summary}"
    )

def build_suggestions_prompt(age, gender, country, condition, notes):
    return (
        f"为一位来自 {country}、{age} 岁、关注“{condition}”的{gender}，列出10条具体而温和的生活方式改善建议。\n"
        "⚠️ 严格指令：请勿在首行添加任何寒暄（如“当然可以”），直接以列表形式给出建议。\n"
        "建议应实用、符合文化习惯且具滋养性，并带有适量表情符号（如🌱、💡等）。"
    )

# OpenAI Interaction
def get_openai_response(prompt, temp=0.7):
    try:
        result = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=temp
        )
        return result.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return "⚠️ 无法生成回应。"

def generate_metrics_with_ai(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.7
        )
        lines = res.choices[0].message.content.strip().split("\n")
        metrics, current_title, labels, values = [], "", [], []
        for line in lines:
            if line.startswith("###"):
                if current_title:
                    metrics.append({"title": current_title, "labels": labels, "values": values})
                current_title, labels, values = line[3:].strip(), [], []
            elif ":" in line:
                try:
                    label, val = line.split(":", 1)
                    labels.append(label.strip())
                    values.append(int(val.strip().replace("%", "")))
                except: pass
        if current_title:
            metrics.append({"title": current_title, "labels": labels, "values": values})
        return metrics or [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50,75]}]
    except Exception as e:
        logging.error(f"Chart parse error: {e}")
        return [{"title": "默认指标", "labels": ["指标A","指标B"], "values": [50,75]}]

# HTML & Email Helpers
def generate_user_data_html(user_info, labels):
    html = '<h2 style="font-family:sans-serif;color:#333;border-bottom:2px solid #4CAF50;padding-bottom:5px;">个人资料摘要</h2><table style="width:100%;border-collapse:collapse;font-family:sans-serif;margin-bottom:30px;">'
    order = ['name','chinese_name','age','gender','country','height','weight','condition','details','referrer','angel']
    for k in order:
        v = user_info.get(k)
        if v:
            html += f'<tr style="border-bottom:1px solid #eee;">'<br>                f'<td style="padding:12px;background:#f9f9f9;font-weight:bold;width:150px;">{labels.get(k,k)}</td>'<br>                f'<td style="padding:12px;">{v}</td></tr>'
    html += '</table>'
    return html

def generate_custom_charts_html(metrics):
    html = '<h2 style="font-family:sans-serif;color:#333;border-bottom:2px solid #4CAF50;padding-bottom:5px;">健康指标图表</h2>'
    for m in metrics:
        html += f'<h3 style="font-family:sans-serif;color:#333;margin-top:20px;">{m['title']}</h3>'
        for label, val in zip(m['labels'], m['values']):
            html += f'<div style="margin-bottom:12px;font-family:sans-serif;">'<br>                    f'<p style="margin:0 0 5px 0;">- {label}: {val}%</p>'<br>                    f'<div style="background:#e0e0e0;border-radius:8px;width:100%;height:16px;">'<br>                        f'<div style="background:#4CAF50;width:{val}%;height:16px;border-radius:8px;"></div>'<br>                    '</div></div>'
    return html

def generate_footer_html():
    return ("<div style='margin-top:40px;border-left:4px solid #4CAF50;padding-left:15px;font-family:sans-serif;'>"
            "<h3 style='font-size:22px;font-weight:bold;color:#333;'>📊 由 KataChat AI 生成的见解</h3>"
            "<p style='font-size:18px;color:#555;line-height:1.6;'>此报告为 AI 生成，基于匿名健康数据与全球基准。</p>"
            "</div>")

@app.route('/health_analyze', methods=['POST'])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get('lang','zh').lower()
        if lang!='zh': return jsonify({'error':'Unsupported language'}),400
        dob = f"{data['dob_year']}-{int(data['dob_month']):02d}-{int(data['dob_day']):02d}"
        age = compute_age(dob)
        user_info = {k:data.get(k) for k in ['name','chinese_name','gender','height','weight','country','condition','referrer','angel','details']}
        user_info.update({'dob':dob,'age':age,'notes':data.get('details') or '无补充说明'})

        # Generate metrics
        cp = (f"这是一位来自 {user_info['country']} 的 {user_info['age']} 岁 {user_info['gender']}，其健康问题为“{user_info['condition']}”。"
              f"补充说明：{user_info['notes']}\n\n"
              "请根据此问题生成 3 个不同的健康相关指标类别。"
              "每个类别必须以 '###' 开头，并包含 3 个指标，格式如 '指标名称: 68%'。百分比在25-90之间，仅返回3个区块。"
        )
        metrics = generate_metrics_with_ai(cp)

        # Summary & suggestions
        summary = get_openai_response(build_summary_prompt(age,user_info['gender'],user_info['country'],user_info['condition'],user_info['notes'],metrics))
        creative = get_openai_response(build_suggestions_prompt(age,user_info['gender'],user_info['country'],user_info['condition'],user_info['notes']),temp=0.85)

        # Post-process
        summary = re.sub(r'^(在分析[^。]+时)', lambda m:m.group(1).replace('在分析','在相似群体中的'), summary)
        creative = re.sub(r'^当然可以！\s*','',creative)

        # Build email
        email_body = f"<h1>{LANGUAGE['zh']['report_title']}</h1>" + generate_user_data_html(user_info,LANGUAGE_TEXTS['zh']) + generate_custom_charts_html(metrics)
        email_body += '<h2>🧠 摘要</h2>' + ''.join([f"<p>{p}</p>" for p in summary.split('\n') if p])
        email_body += '<h2>💡 建议</h2>' + ''.join([f"<p>{l}</p>" for l in creative.splitlines() if l])
        email_body += generate_footer_html()
        send_email_report(SMTP_USERNAME, LANGUAGE['zh']['email_subject'], email_body)

        # Web response
        resp_html = '<div>' + ''.join([f"<p>{p}</p>" for p in summary.split('\n') if p]) + ''.join([f"<p>{l}</p>" for l in creative.splitlines()]) + '</div>'
        return jsonify({'metrics':metrics,'html_result':resp_html,'footer':LANGUAGE_TEXTS['zh']['footer'],'report_title':LANGUAGE['zh']['report_title']})
    except Exception as e:
        logging.error(f"Error: {e}")
        traceback.print_exc()
        return jsonify({'error':'服务器错误'}),500

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT',5000)), debug=False)
