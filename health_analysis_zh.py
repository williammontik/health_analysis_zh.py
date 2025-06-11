# -*- coding: utf-8 -*-
import os
import logging
import traceback
import re
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import concurrent.futures # Import the library for concurrency

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# --- CONFIGURATION (Same as before) ---
try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logging.info("OpenAI client initialized successfully.")
except Exception as e:
    logging.critical(f"OpenAI API key not found or invalid. Error: {e}")
    client = None

# --- LANGUAGE DATA & PROMPTS (Same as before) ---
LABELS_ZH = {
    "summary_title": "🧠 摘要:",
    "suggestions_title": "💡 创意建议:"
}
# The build_summary_prompt_zh and build_suggestions_prompt_zh functions are the same as before.

# --- HELPER FUNCTIONS (Same as before) ---
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
            max_tokens=1200
        )
        return result.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI API call failed: {e}")
        return "⚠️ AI响应生成失败，请稍后再试。"

# --- CHINESE API ENDPOINT (REVISED FOR CONCURRENCY) ---
@app.route("/health_analyze_zh", methods=["POST"])
def health_analyze_zh():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "无效请求。未收到JSON数据。"}), 400

        required_fields = ["dob_year", "gender", "country", "condition", "details"]
        missing_fields = [f for f in required_fields if not data.get(f)]
        if missing_fields:
            return jsonify({"error": f"缺少必要字段: {', '.join(missing_fields)}"}), 400

        age = compute_age(data.get("dob_year"))
        details = data.get("details", "无").replace("'''", "'")
        gender = data.get("gender")
        country = data.get("country")
        condition = data.get("condition")

        # --- OPTIMIZATION: RUN ALL AI CALLS CONCURRENTLY ---
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Step 1: Define all the prompts first
            chart_prompt = (
                f"一位{age}岁来自{country}的{gender}有健康问题：“{condition}”，"
                f"补充说明：“{details}”。请为此档案生成3个不同的健康指标类别。每个类别必须以“###”开头，"
                f"并有3个格式为“指标名称: 数值%”的指标。数值必须在25-90之间。请仅用简体中文回答。"
            )
            # We need the metrics first to create the other prompts
            metrics_content = get_openai_response(chart_prompt)
            metrics = parse_metrics_from_content_zh(metrics_content)

            summary_prompt = build_summary_prompt_zh(age, gender, country, condition, details, metrics)
            suggestions_prompt = build_suggestions_prompt_zh(age, gender, country, condition, details)

            # Step 2: Submit the summary and suggestions tasks to run at the same time
            future_summary = executor.submit(get_openai_response, summary_prompt)
            future_creative = executor.submit(get_openai_response, suggestions_prompt, temp=0.85)

            # Step 3: Get the results when they are ready
            summary = future_summary.result()
            creative = future_creative.result()
        # --- END OF OPTIMIZATION ---

        # Step 4: Build the HTML response (this logic is unchanged)
        summary_paragraphs = [p.strip() for p in summary.split('\n') if p.strip()]
        html_result = f"<div style='font-size:24px; font-weight:bold; margin-top:30px;'>{LABELS_ZH['summary_title']}</div><br>"
        html_result += ''.join(f"<p style='line-height:1.7; font-size:16px; margin-bottom:16px;'>{p}</p>" for p in summary_paragraphs)
        
        html_result += f"<div style='font-size:24px; font-weight:bold; margin-top:30px;'>{LABELS_ZH['suggestions_title']}</div><br>"
        html_result += ''.join(f"<p style='margin:16px 0; font-size:17px;'>{line}</p>" for line in creative.split("\n") if line.strip())

        footer_html = f"""
        <div style="margin-top: 40px; padding: 20px; background-color: #f8f9fa; border-radius: 8px; font-family: sans-serif; border-left: 6px solid #4CAF50;">
            <h4 style="font-size: 16px; font-weight: bold; margin-top: 0; margin-bottom: 15px; display: flex; align-items: center;">
                📊 由 KataChat AI 生成的健康洞察
            </h4>
            <p style="font-size: 14px; color: #333; line-height: 1.6;">
                本健康报告基于 KataChat 的专有AI模型生成，其数据来源包括:
            </p>
            <ul style="font-size: 14px; color: #555; padding-left: 20px; margin-top: 10px; margin-bottom: 20px; line-height: 1.6;">
                <li>来自新加坡、马来西亚和台湾地区个人的匿名化健康与生活方式档案的安全数据库</li>
                <li>来自可信的OpenAI研究数据集的聚合全球健康基准与行为趋势数据</li>
            </ul>
            <p style="font-size: 14px; color: #333; line-height: 1.6;">
                所有分析均严格遵守PDPA法规，以保护您的个人数据，同时发掘有意义的健康洞察。
            </p>
            <p style="font-size: 14px; color: #333; line-height: 1.6; margin-top: 20px;">
                <strong>🗒️ 请注意:</strong> 本报告非医疗诊断。若有任何严重的健康问题，请咨询执业医疗专业人士。
            </p>
            <p style="font-size: 14px; color: #333; line-height: 1.6; margin-top: 20px;">
                <strong>PS:</strong> 一份个性化的报告也将发送到您的电子邮箱，预计在24-48小时内送达。如果您想更详细地探讨分析结果，我们很乐意安排一个15分钟的简短通话。
            </p>
        </div>
        """
        html_result += footer_html
        
        return jsonify({"metrics": metrics, "html_result": html_result})

    except Exception as e:
        logging.error(f"An unexpected error occurred in /health_analyze_zh: {e}")
        traceback.print_exc()
        return jsonify({"error": "服务器内部发生错误，请稍后再试。"}), 500

# You need to add this new helper function to your file
def parse_metrics_from_content_zh(content):
    """Parses the raw string from AI into the metrics list structure."""
    metrics, current_title, labels, values = [], "", [], []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line: continue
        if line.startswith("###"):
            if current_title and labels:
                metrics.append({"title": current_title, "labels": labels, "values": values})
            current_title = line.replace("###", "").strip()
            labels, values = [], []
        elif ":" in line:
            try:
                label, val_str = line.split(":", 1)
                val_match = re.search(r'\d+', val_str)
                if val_match:
                    labels.append(label.strip())
                    values.append(int(val_match.group(0)))
            except (ValueError, IndexError):
                continue
    if current_title and labels:
        metrics.append({"title": current_title, "labels": labels, "values": values})
    if not metrics:
        return [{"title": "默认指标", "labels": ["数据点A", "数据点B", "数据点C"], "values": [65, 75, 85]}]
    return metrics


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5003))
    app.run(debug=True, port=port, host="0.0.0.0")
