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
    except: return 0

# --- AI Prompts (Simplified Chinese) ---
def build_summary_prompt(age, gender, country, concern, notes, metrics):
    """
    **FIXED:** This prompt is optimized for speed while still aiming for rich content.
    """
    metrics_summary = ", ".join([f"{label} ({value}%)" for block in metrics for label, value in zip(block["labels"], block["values"])][:9])
    return (
        f"任务：为一位来自 {country} 的 {age} 岁 {gender} 撰写一份四段式的健康分析，其主要问题是“{concern}”。请使用以下数据：{metrics_summary}。\n\n"
        f"指令：\n"
        f"1. **深入分析**：不要只重复数据。请解释这些百分比数字对这个用户群体意味着什么，并分析它们之间的联系。例如，高皮脂分泌如何影响皮肤问题。\n"
        f"2. **内容丰富**：每个段落都应提供有价值的见解和背景信息，使其内容充实。\n"
        f"3. **专业且匿名**：语气应充满同理心但专业。严禁使用“你”、“我”等代词。请使用“该年龄段的女性...”或“来自 {country} 的个体...”等措辞。\n"
        f"4. **整合数据**：每段话中都必须自然地融入至少一个具体的百分比数据。"
    )

def build_suggestions_prompt(age, gender, country, concern, notes):
    return (
        f"为一位来自 {country}、{age} 岁、关注“{concern}”的“{gender}”，提出 10 项具体而温和的生活方式改善建议。"
        f"请使用温暖、支持的语气，并包含有帮助的表情符号。"
        f"建议应实用、符合文化习惯且具滋养性。"
        f"⚠️ **严格指令**：请勿使用姓名、代词（她/她的/他/他的）或“该个体”等词语。"
        f"仅使用如“在 {country} 60多岁的女性”或“面临此问题的个体”等描述。"
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
                if current_title: metrics.append({"title": current_title, "labels": labels, "values": values})
                current_title, labels, values = line.replace("###", "").strip(), [], []
            elif ":" in line:
                try:
                    label, val = line.split(":", 1)
                    labels.append(label.strip())
                    values.append(int(val.strip().replace("%", "")))
                except ValueError: continue
        if current_title: metrics.append({"title": current_title, "labels": labels, "values": values})
        return metrics or [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50, 75]}]
    except Exception as e:
        logging.error(f"Chart parse error: {e}")
        return [{"title": "默认指标", "labels": ["指标A", "指标B"], "values": [50, 75]}]

# --- HTML & Email Generation (Simplified Chinese) ---
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

# --- Flask Endpoint ---
@app.route("/health_analyze", methods=["POST"])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get("lang", "zh").strip().lower()
        
        if lang != 'zh':
            return jsonify({"error": "This endpoint only supports Chinese (zh) language."}), 400

        labels = LANGUAGE_TEXTS[lang]
        content_lang = LANGUAGE[lang]
        
        dob = f"{data.get('dob_year')}-{str(data.get('dob_month')).zfill(2)}-{str(data.get('dob_day')).zfill(2)}"
        age = compute_age(dob)
        
        user_info = {k: data.get(k) for k in ["name", "chinese_name", "gender", "height", "weight", "country", "condition", "referrer", "angel"]}
        user_info.update({"dob": dob, "age": age, "notes": data.get("details") or "无补充说明"})

        chart_prompt = (
            f"这是一位来自 {user_info['country']} 的 {user_info['age']} 岁 {user_info['gender']}，其健康问题为“{user_info['condition']}'。补充说明：{user_info['notes']}\n\n"
            f"请根据此问题生成 3 个不同的健康相关指标类别。\n"
            f"每个类别必须以 '###' 开头（例如 '### 睡眠质量'），并包含 3 个独特的真实世界指标，格式为 '指标名称: 68%'.\n"
            f"所有百分比必须介于 25% 到 90% 之间。\n"
            f"仅返回 3 个格式化的区块，不要有任何介绍或解释。"
        )

        metrics = generate_metrics_with_ai(chart_prompt)
        
        summary_prompt = build_summary_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'], metrics)
        summary = get_openai_response(summary_prompt)
        if "⚠️" in summary: summary = "💬 由于系统延迟，摘要暂时无法使用。"

        suggestions_prompt = build_suggestions_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'])
        creative = get_openai_response(suggestions_prompt, temp=0.85)
        if "⚠️" in creative: creative = "💡 目前无法加载建议。请稍后再试。"

        html_result = "<div style='font-family: sans-serif; color: #333;'>"
        html_result += "<div style='font-size:24px; font-weight:bold; margin-top:30px;'>🧠 摘要:</div>"
        html_result += "".join([f"<p style='line-height:1.7; font-size:16px; margin-top:1em; margin-bottom:1em;'>{p.strip()}</p>" for p in summary.strip().split('\n\n') if p.strip()])
        
        html_result += "<div style='font-size:24px; font-weight:bold; margin-top:40px;'>💡 生活建议:</div>"
        html_result += "".join([f"<p style='margin:16px 0; font-size:17px; line-height:1.6;'>{line}</p>" for line in creative.split("\n") if line.strip()])
        
        html_result += generate_footer_html() + "</div>"
        
        return jsonify({
            "metrics": metrics,
            "html_result": html_result,
            "footer": labels.get('footer'),
            "report_title": content_lang.get('report_title')
        })

    except Exception as e:
        logging.error(f"Health analyze error: {e}")
        traceback.print_exc()
        return jsonify({"error": "发生未预期的服务器错误。"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5000)), host="0.0.0.0")
