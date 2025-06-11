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
# Your original design text is preserved here.
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
    except: return 0

# --- AI Prompts (Unchanged from your original) ---
def build_summary_prompt(age, gender, country, concern, notes, metrics):
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

# --- HTML & Email Generation ---

def generate_user_data_html(user_info, labels):
    """Generates an HTML table for the user's submitted data."""
    html = """
    <h2 style="font-family: sans-serif; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;">个人资料摘要</h2>
    <table style="width: 100%; border-collapse: collapse; font-family: sans-serif; margin-bottom: 30px;">
    """
    display_order = ['name', 'chinese_name', 'age', 'gender', 'country', 'height', 'weight', 'condition', 'details', 'referrer', 'angel']
    for key in display_order:
        value = user_info.get(key)
        label_text = labels.get(key, key.replace('_', ' ').title())
        if value:
            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 12px; background-color: #f9f9f9; font-weight: bold; width: 150px;">{label_text}</td>
                <td style="padding: 12px;">{value}</td>
            </tr>
            """
    html += "</table>"
    return html

def generate_custom_charts_html(metrics):
    """
    Generates HTML for the progress-bar style charts based on your design.
    This does NOT use matplotlib and instead builds the design with HTML/CSS.
    """
    charts_html = '<h2 style="font-family: sans-serif; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;">健康指标图表</h2>'
    
    for metric in metrics:
        charts_html += f'<h3 style="font-family: sans-serif; color: #333; margin-top: 20px;">{metric["title"]}</h3>'
        for label, value in zip(metric["labels"], metric["values"]):
            charts_html += f"""
            <div style="margin-bottom: 12px; font-family: sans-serif;">
                <p style="margin: 0 0 5px 0;">- {label}: {value}%</p>
                <div style="background-color: #e0e0e0; border-radius: 8px; width: 100%; height: 16px;">
                    <div style="background-color: #4CAF50; width: {value}%; height: 16px; border-radius: 8px;"></div>
                </div>
            </div>
            """
    return charts_html


# Your original footer design is preserved here.
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

def send_email_report(recipient_email, subject, body):
    """Connects to SMTP server and sends the complete HTML report."""
    if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD]):
        logging.warning("SMTP settings are not fully configured. Skipping email.")
        return
    try:
        msg = MIMEText(body, 'html', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = f"KataChat AI <{SMTP_USERNAME}>"
        msg['To'] = recipient_email

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, [recipient_email], msg.as_string())
            logging.info(f"Successfully sent health report to {recipient_email}")
    except Exception as e:
        logging.error(f"Failed to send email to {recipient_email}: {e}")
        traceback.print_exc()

# --- Flask Endpoint ---
@app.route("/health_analyze", methods=["POST"])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get("lang", "zh").strip().lower()
        if lang != 'zh': return jsonify({"error": "This endpoint only supports Chinese (zh)."}), 400

        labels = LANGUAGE_TEXTS[lang]
        content_lang = LANGUAGE[lang]
        
        dob = f"{data.get('dob_year')}-{str(data.get('dob_month')).zfill(2)}-{str(data.get('dob_day')).zfill(2)}"
        age = compute_age(dob)
        
        user_info = {k: data.get(k) for k in ["name", "chinese_name", "gender", "height", "weight", "country", "condition", "referrer", "angel", "details"]}
        user_info.update({"dob": dob, "age": age, "notes": data.get("details") or "无补充说明"})

        # --- AI Generation (Unchanged) ---
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
        suggestions_prompt = build_suggestions_prompt(age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'])
        creative = get_openai_response(suggestions_prompt, temp=0.85)

        # --- Build the COMPLETE HTML BODY for the EMAIL ---
        # This now includes the user data and the custom-designed charts.
        email_html_body = f"""
        <div style='font-family: sans-serif; color: #333; max-width: 800px; margin: auto; padding: 20px;'>
            <h1 style='text-align:center; color: #333;'>{content_lang.get('report_title')}</h1>
            
            {generate_user_data_html(user_info, labels)}
            
            {generate_custom_charts_html(metrics)}

            <div style="margin-top: 30px;">
                <h2 style="font-family: sans-serif; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;">🧠 摘要</h2>
                {''.join([f"<p style='line-height:1.7; font-size:16px;'>{p.strip()}</p>" for p in summary.strip().split('  ') if p.strip()])}
            </div>
            
            <div style="margin-top: 30px;">
                <h2 style="font-family: sans-serif; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;">💡 生活建议</h2>
                {''.join([f"<p style='margin:12px 0; font-size:16px; line-height:1.6;'>{line}</p>" for line in creative.splitlines() if line.strip()])}
            </div>

            {generate_footer_html()}
        </div>
        """

        # --- Send the Email ---
        email_subject = f"{content_lang.get('email_subject')} - {user_info.get('name', 'N/A')}"
        send_email_report(SMTP_USERNAME, email_subject, email_html_body)

        # --- Return the original response structure to the front-end ---
        # The web page will still use Chart.js, but the email has the custom HTML charts.
        html_result_for_web = "<div style='font-family: sans-serif; color: #333;'>"
        html_result_for_web += "<div style='font-size:24px; font-weight:bold; margin-top:30px;'>🧠 摘要:</div>"
        html_result_for_web += "".join([f"<p style='line-height:1.7; font-size:16px; margin-top:1em; margin-bottom:1em;'>{p.strip()}</p>" for p in summary.strip().split('\n\n') if p.strip()])
        html_result_for_web += "<div style='font-size:24px; font-weight:bold; margin-top:40px;'>💡 生活建议:</div>"
        html_result_for_web += "".join([f"<p style='margin:16px 0; font-size:17px; line-height:1.6;'>{line}</p>" for line in creative.split("\n") if line.strip()])
        html_result_for_web += generate_footer_html() + "</div>"
        
        return jsonify({
            "metrics": metrics,
            "html_result": html_result_for_web,
            "footer": labels.get('footer'),
            "report_title": content_lang.get('report_title')
        })

    except Exception as e:
        logging.error(f"Health analyze error: {e}")
        traceback.print_exc()
        return jsonify({"error": "发生未预期的服务器错误。"}), 500

if __name__ == "__main__":
    # Use debug=False for production environments
    app.run(debug=False, port=int(os.getenv("PORT", 5000)), host="0.0.0.0")

