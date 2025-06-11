# -*- coding: utf-8 -*-
import os, logging, smtplib, traceback
from datetime import datetime
from dateutil import parser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# Configure logging
typelog = logging.INFO
logging.basicConfig(level=typelog)

# Initialize OpenAI client and SMTP settings
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
        "name": "法定全名", "chinese_name": "中文姓名", "dob": "出生日期",
        "country": "国家", "gender": "性别", "age": "年龄",
        "height": "身高 (厘米)", "weight": "体重 (公斤)", "condition": "主要健康问题",
        "details": "补充说明", "referrer": "推荐人", "angel": "健康伙伴",
        "footer": "📩 此报告已通过电子邮件发送给您。所有内容均由 KataChat AI 生成，并符合个人信息保护法规定。"
    }
}

# --- Utility Functions ---
def compute_age(dob: str) -> int:
    """Compute age in years given a date string."""
    try:
        dt = parser.parse(dob)
        today = datetime.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except Exception:
        return 0

# --- Prompt Builders (Enforce neutral, group-based language & avoid interjections) ---
def build_summary_prompt(age, gender, country, concern, notes, metrics):
    """Constructs a four-paragraph summary prompt with strict requirements."""
    # Build a list of metric descriptors to avoid indentation issues
    metric_items = [
        f"{label} ({value}%)"
        for block in metrics
        for label, value in zip(block["labels"], block["values"])
    ]
    metrics_summary = ", ".join(metric_items)

    return (
        f"任务：请为一位来自 {country} 的 {age} 岁 {gender}，关注“{concern}”，撰写一份四段式健康洞察报告，"
        f"使用数据：{metrics_summary}。\n\n"
        "严格要求：\n"
        "1. **绝不使用**第一人称或第二人称（“你”、“我”、“您的”等），\n"
        "2. **避免**使用“对于…而言”句式，请使用“该年龄段的个体”、“类似年龄段的群体”等中性表述，\n"
        "3. 每段至少引用一个具体百分比，并解释其对该群体健康的意义，\n"
        "4. 语气应专业且温暖，充满同理心，但**不得**出现任何代词。\n"
    )


def build_suggestions_prompt(age, gender, country, concern, notes):
    """Constructs a suggestions prompt with strict neutral language rules."""
    return (
        f"请针对来自{country}、{age}岁、关注“{concern}”的{gender}，提出10项具体、温和的生活方式改善建议。\n\n"
        "严格要求：\n"
        "1. **绝不**使用姓名、代词或直接称呼，\n"
        "2. 建议需使用“同年龄段的群体”或“类似背景的个体”等中性表述，\n"
        "3. 建议内容应直接以数字序号开头，**避免**使用“当然”、“以下是”等过渡词，\n"
        "4. 语气温暖、支持，可适当使用表情符号，但**不得**出现“您”“你”等词语。\n"
    )

# --- OpenAI Interaction Functions ---
def get_openai_response(prompt, temp=0.7):
    try:
        res = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=temp
        )
        return res.choices[0].message.content
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

# … rest of code unchanged …
