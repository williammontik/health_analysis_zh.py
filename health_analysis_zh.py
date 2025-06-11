# -*- coding: utf-8 -*-
import os, logging, smtplib, traceback, io, base64
from datetime import datetime
from dateutil import parser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# This is a non-interactive backend for matplotlib, needed for server-side image generation
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


app = Flask(__name__)
CORS(app)
# Using INFO level for cleaner logs in production, but DEBUG is fine for development.
logging.basicConfig(level=logging.INFO)

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
        "name": "法定全名", "chinese_name": "中文姓名", "dob": "出生日期", "country": "国家", "gender": "性别",
        "age": "年龄", "height": "身高 (厘米)", "weight": "体重 (公斤)", "concern": "主要问题",
        "details": "补充说明", "referrer": "推荐人", "angel": "健康伙伴",
        "footer": "📩 此报告已通过电子邮件发送给您。所有内容均由 KataChat AI 生成，并符合个人信息保护法规定。"
    }
}

# --- Utility (Unchanged) ---
def compute_age(dob):
    try:
        dt = parser.parse(dob)
        today = datetime.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except:
        return 0

# --- AI Prompts (Modified) ---
def build_summary_prompt(age, gender, country, concern, notes, metrics):
    metrics_summary = ", ".join(
        [f"{label} ({value}%" for block in metrics for label, value in zip(block["labels"], block["values"])])
    )
    return (
        f"对于大约 {age} 岁的女性，其主要健康问题为“{concern}”，"
        f"请基于以下数据撰写一份四段式的健康分析：{metrics_summary}。\n\n"
        f"指令：\n"
        f"1. **深入分析**：不要只重复数据。请解释这些百分比数字对该群体意味着什么，并分析它们之间的联系。\n"
        f"2. **内容丰富**：每个段落都应提供有价值的见解和背景信息，使其内容充实。\n"
        f"3. **专业且匿名**：语气应充满同理心但专业。严禁使用“你”、“我”等代词。请使用“该年龄段的女性”或“来自{country}的类似女性”等措辞。\n"
        f"4. **整合数据**：每段话中都必须自然地融入至少一个具体的百分比数据。"
    )


def build_suggestions_prompt(age, gender, country, concern, notes):
    return (
        f"针对大约 {age} 岁、关心“{concern}”的女性，"
        f"提出 10 项具体而温和的生活方式改善建议。"
        f"请使用温暖、支持的语气，且不用“当然可以！”之类的开场白。"
        f"建议应实用、符合文化习惯并富有滋养性。\n"
        f"⚠️ **严格指令**：请勿使用姓名或代词。仅用“对于该年龄段的女性”或“类似女性群体”之类的描述。"
    )

# --- OpenAI Interaction (Unchanged) ---
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
        metrics = []
        current_title, labels, values = "", [], []
        for line in lines:
            if line.startswith("###"):
                if current_title:
                    metrics.append({"title": current_title, "labels": labels, "values": values})
                current_title, labels, values = line.replace("###", "").strip(), [], []
            elif ":" in line:
                try:
                    label, val = line.split(":", 1)
                    labels.append(label.strip())
                    values.append(int(val.strip().replace("%", "")))
                except ValueError:
                    continue
        if current_title:
            metrics.append({"title": current_title, "labels": labels, "values": values})
        return metrics or [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50, 75]}]
    except Exception as e:
        logging.error(f"Chart parse error: {e}")
        return [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50, 75]}]

# --- HTML & Email Generation (Unchanged) ---
# ... rest of functions unchanged ...

# --- Flask Endpoint (Unchanged) ---
# ... endpoint implementation unchanged ...

if __name__ == "__main__":
    app.run(debug=False, port=int(os.getenv("PORT", 5000)), host="0.0.0.0")
