# -*- coding: utf-8 -*-
import os
import logging
import traceback
import re
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# --- CONFIGURATION ---
try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logging.info("OpenAI client initialized successfully.")
except Exception as e:
    logging.critical(f"OpenAI API key not found or invalid. Error: {e}")
    client = None

# --- LANGUAGE DATA (CHINESE) ---
LABELS_ZH = {
    "summary_title": "🧠 摘要:",
    "suggestions_title": "💡 创意建议:"
}

# --- PROMPT ENGINEERING (CHINESE) ---
def build_single_request_prompt_zh(age, gender, country, concern, notes):
    return (
        f"你是一位专业的健康分析师。请根据以下个人档案，严格按照指定的格式，一次性完成三项任务。\n\n"
        f"**个人档案:**\n"
        f"- 年龄: {age}\n"
        f"- 性别: {gender}\n"
        f"- 国家: {country}\n"
        f"- 主要健康问题: {concern}\n"
        f"- 补充说明: {notes}\n\n"
        f"--- TASKS ---\n"
        f"**任务1：生成健康指标**\n"
        f"生成3个不同的健康指标类别。每个类别必须以 '###' 开头，并包含3个相关的指标，格式为 '指标名称: 数值%'。数值必须在25-90之间。\n\n"
        f"**任务2：撰写摘要**\n"
        f"根据你在任务1中生成的指标，撰写一份四个段落的综合性叙事摘要。必须严格使用群体性措辞（例如“对于此类特征的群体...”），绝不能描述某个特定的人。\n\n"
        f"**任务3：提供创意建议**\n"
        f"提出10条具体、温和且实用的生活方式改善建议。建议应为编号列表，并包含表情符号。\n\n"
        f"--- RESPONSE FORMAT ---\n"
        f"请严格按照以下结构和分隔符提供您的回答，不要添加任何额外的介绍或结语。\n\n"
        f"[METRICS_START]\n\n[METRICS_END]\n\n[SUMMARY_START]\n\n[SUMMARY_END]\n\n[SUGGESTIONS_START]\n\n[SUGGESTIONS_END]"
    )

# --- HELPERS ---
def compute_age(dob_year):
    try:
        return datetime.now().year - int(dob_year)
    except (ValueError, TypeError):
        return 0

def get_openai_response(prompt, temp=0.75):
    if not client:
        raise Exception("OpenAI client not initialized.")
    try:
        result = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=temp,
            max_tokens=2000
        )
        return result.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI API call failed: {e}")
        return "⚠️ AI响应生成失败，请稍后再试。"

def parse_metrics_from_response(response_text):
    try:
        metrics_str = response_text.split("[METRICS_START]")[1].split("[METRICS_END]")[0].strip()
        metrics, current_title, labels, values = [], "", [], []

        for line in metrics_str.splitlines():
            line = line.strip()
            if not line or line.startswith("###"):
                if labels and values:
                    metrics.append({
                        "title": current_title,
                        "labels": labels,
                        "values": values
                    })
                    labels, values = [], []
                current_title = line.replace("###", "").strip()
            elif ":" in line:
                label, val = line.split(":")
                labels.append(label.strip())
                values.append(int(re.findall(r"\d+", val.strip())[0]))

        if labels and values:
            metrics.append({
                "title": current_title,
                "labels": labels,
                "values": values
            })

        return metrics
    except Exception as e:
        logging.error(f"Error parsing metrics: {e}")
        return []

def extract_block(response_text, start_tag, end_tag):
    try:
        return response_text.split(start_tag)[1].split(end_tag)[0].strip()
    except Exception:
        return ""

# --- MAIN ENDPOINT ---
@app.route("/health_analyze_zh", methods=["POST"])
def analyze_health_zh():
    try:
        data = request.json
        age = compute_age(data.get("dob_year"))
        gender = data.get("gender", "")
        country = data.get("country", "")
        concern = data.get("condition", "")
        notes = data.get("details", "")

        prompt = build_single_request_prompt_zh(age, gender, country, concern, notes)
        logging.info("Sending prompt to OpenAI...")

        response_text = get_openai_response(prompt)

        metrics = parse_metrics_from_response(response_text)
        summary = extract_block(response_text, "[SUMMARY_START]", "[SUMMARY_END]")
        suggestions = extract_block(response_text, "[SUGGESTIONS_START]", "[SUGGESTIONS_END]")

        # 🔧 Fix: no backslashes inside f-string expressions
        summary_html = summary.replace('\n', '<br>')
        suggestions_html = suggestions.replace('\n', '<br>')

        html_result = f"""
        <h4>{LABELS_ZH['summary_title']}</h4>
        <p>{summary_html}</p>
        <h4>{LABELS_ZH['suggestions_title']}</h4>
        <p>{suggestions_html}</p>
        <p style="margin-top:30px;font-size:14px;color:#888;">
          🤖 此报告由 KataChat AI 健康分析系统自动生成，仅供参考。我们不会存储您的任何个人数据。
        </p>
        """

        return jsonify({
            "metrics": metrics,
            "html_result": html_result
        })

    except Exception as e:
        logging.error(traceback.format_exc())
        return jsonify({"error": "❌ 系统处理失败，请检查输入或稍后重试。"}), 500

# --- APP ENTRY POINT ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
