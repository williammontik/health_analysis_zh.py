# -*- coding: utf-8 -*-
import os, logging, smtplib, traceback, io, base64
from datetime import datetime
from dateutil import parser
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# --- NEW: Import matplotlib for chart generation ---
import matplotlib
matplotlib.use('Agg') # Use a non-interactive backend for server-side rendering
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

# --- Language Constants (zh for Simplified Chinese) ---
LANGUAGE = {
    "zh": {
        "email_subject": "您的健康洞察报告",
        "report_title": "全球健康洞察报告" # Removed emoji for cleaner email subject
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

# --- Utility ---
def compute_age(dob):
    try:
        dt = parser.parse(dob)
        today = datetime.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except: return 0

# --- AI Prompts (Unchanged) ---
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
# --- NEW: Function to generate user data table ---
def generate_user_data_html(user_info, labels):
    html = """
    <h2 style="color: #333;">个人资料摘要</h2>
    <table style="width: 100%; border-collapse: collapse; font-family: sans-serif; margin-bottom: 30px;">
    """
    display_order = ['name', 'chinese_name', 'age', 'gender', 'country', 'height', 'weight', 'condition', 'details', 'referrer', 'angel']
    for key in display_order:
        value = user_info.get(key)
        if value: # Only show fields that have a value
            label = labels.get(key, key.replace('_', ' ').title())
            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 12px; background-color: #f9f9f9; font-weight: bold; width: 30%;">{label}</td>
                <td style="padding: 12px;">{value}</td>
            </tr>
            """
    html += "</table>"
    return html

# --- NEW: Function to generate charts as images ---
def generate_charts_html(metrics):
    charts_html = '<h2 style="color: #333; margin-top: 30px;">健康指标图表</h2>'
    plt.rcParams['font.sans-serif'] = ['SimHei'] # Use a font that supports Chinese characters
    plt.rcParams['axes.unicode_minus'] = False

    for metric in metrics:
        try:
            fig, ax = plt.subplots(figsize=(8, 4))
            labels = metric['labels']
            values = metric['values']
            
            ax.barh(labels, values, color='#4CAF50')
            ax.set_title(metric['title'], fontsize=14, fontweight='bold')
            ax.set_xlabel('百分比 (%)', fontsize=10)
            ax.set_xlim(0, 100)
            ax.invert_yaxis() # To have the first item on top
            
            # Add value labels on bars
            for index, value in enumerate(values):
                ax.text(value + 1, index, str(value), color='black', va='center')

            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            image_base64 = base64.b64encode(buf.read()).decode('utf-8')
            buf.close()
            plt.close(fig)

            charts_html += f'<div style="text-align: center; margin-bottom: 20px;"><img src="data:image/png;base64,{image_base64}" alt="{metric["title"]}" style="max-width: 100%; height: auto;"></div>'
        except Exception as e:
            logging.error(f"Error generating chart for {metric.get('title')}: {e}")
            continue # Skip broken charts
            
    return charts_html

def generate_footer_html():
    return """
    <div style="margin-top: 40px; border-top: 1px solid #ccc; padding-top: 20px; font-family: sans-serif;">
        <h3 style="font-size: 18px; font-weight: bold; color: #333;">📊 由 KataChat AI 生成的见解</h3>
        <p style="font-size: 14px; color: #555; line-height: 1.6;">
            此健康报告是使用 KataChat 的专有 AI 模型生成的，并严格遵守个人数据保护法规。
            🛡️ <strong>请注意：</strong>本报告并非医疗诊断。若有任何严重的健康问题，请咨询持牌医疗专业人员。
        </p>
    </div>
    """

def send_email_report(recipient_email, subject, body):
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


# --- MODIFIED: Flask Endpoint ---
@app.route("/health_analyze", methods=["POST"])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get("lang", "zh").strip().lower()
        if lang != 'zh': return jsonify({"error": "This endpoint only supports Chinese (zh) language."}), 400

        labels = LANGUAGE_TEXTS[lang]
        content_lang = LANGUAGE[lang]
        
        dob = f"{data.get('dob_year')}-{str(data.get('dob_month')).zfill(2)}-{str(data.get('dob_day')).zfill(2)}"
        age = compute_age(dob)
        
        user_info = {k: data.get(k) for k in ["name", "chinese_name", "gender", "height", "weight", "country", "condition", "details", "referrer", "angel"]}
        user_info.update({"dob": dob, "age": age, "notes": data.get("details") or "无补充说明"})

        # --- AI Generation (same as before) ---
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

        # --- MODIFIED: Build a COMPLETE HTML for the email ---
        email_html_body = f"""
        <div style='font-family: sans-serif; color: #333; max-width: 800px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;'>
            <h1 style='text-align:center; color: #4CAF50;'>{content_lang.get('report_title')}</h1>
            
            {generate_user_data_html(user_info, labels)}
            
            {generate_charts_html(metrics)}
            
            <h2 style='color: #333; margin-top: 30px;'>🧠 摘要</h2>
            {''.join([f"<p style='line-height:1.7; font-size:16px;'>{p.strip()}</p>" for p in summary.strip().split('  ') if p.strip()])}
            
            <h2 style='color: #333; margin-top: 30px;'>💡 生活建议</h2>
            {''.join([f"<p style='margin:12px 0; font-size:16px; line-height:1.6;'>{line}</p>" for line in creative.splitlines() if line.strip()])}
            
            {generate_footer_html()}
        </div>
        """

        # Send the complete email
        email_subject = f"{content_lang.get('email_subject')} - {user_info.get('name', 'N/A')}"
        send_email_report(SMTP_USERNAME, email_subject, email_html_body)

        # --- Build HTML for the WEB PAGE (can be simpler, as JS will handle charts) ---
        web_html_result = f"""
            <div style='font-family: sans-serif; color: #333;'>
                <div style='font-size:24px; font-weight:bold; margin-top:30px;'>🧠 摘要:</div>
                {''.join([f"<p style='line-height:1.7; font-size:16px; margin-top:1em; margin-bottom:1em;'>{p.strip()}</p>" for p in summary.strip().split('  ') if p.strip()])}
                <div style='font-size:24px; font-weight:bold; margin-top:40px;'>💡 生活建议:</div>
                {''.join([f"<p style='margin:16px 0; font-size:17px; line-height:1.6;'>{line}</p>" for line in creative.splitlines() if line.strip()])}
                {generate_footer_html()}
            </div>
        """

        return jsonify({
            "metrics": metrics,
            "html_result": web_html_result, # Send web-specific HTML back to the page
            "footer": labels.get('footer'),
            "report_title": "🎉 " + content_lang.get('report_title') # Add emoji back for web
        })

    except Exception as e:
        logging.error(f"Health analyze error: {e}")
        traceback.print_exc()
        return jsonify({"error": "发生未预期的服务器错误。"}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
