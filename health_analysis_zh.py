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
    metrics_summary = ", ".join(
        f"{label} ({value}%")
        for block in metrics
        for label, value in zip(block["labels"], block["values"])
    )
    return (
        f"任务：请为一位来自 {country} 的 {age} 岁 {gender}，关注“{concern}”，撰写一份四段式健康洞察报告，"
        f"使用数据：{metrics_summary}。\n\n"
        "严格要求：\n"
        "1. **绝不使用**第一人称或第二人称（“你”、“我”、“您的”等），\n"
        "2. **避免**使用“对于来自…而言”等句式，请使用“该年龄段的个体”、“类似年龄段的群体”等中性表述，\n"
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

# --- HTML Generation Functions ---
def generate_user_data_html(user_info, labels):
    html = (
        "<h2 style='font-family: sans-serif; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;'>个人资料摘要</h2>"
        "<table style='width:100%; border-collapse:collapse; font-family:sans-serif; margin-bottom:30px;'>"
    )
    display_order = [
        'name', 'chinese_name', 'age', 'gender', 'country', 
        'height', 'weight', 'condition', 'details', 'referrer', 'angel'
    ]
    for key in display_order:
        val = user_info.get(key)
        label_txt = labels.get(key, key.replace('_', ' ').title())
        if val:
            html += (
                "<tr style='border-bottom:1px solid #eee;'>"
                f"<td style='padding:12px; background:#f9f9f9; font-weight:bold; width:150px;'>{label_txt}</td>"
                f"<td style='padding:12px;'>{val}</td>"
                "</tr>"
            )
    html += "</table>"
    return html


def generate_custom_charts_html(metrics):
    charts_html = (
        "<h2 style='font-family: sans-serif; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;'>健康指标图表</h2>"
    )
    for metric in metrics:
        charts_html += f"<h3 style='font-family: sans-serif; color:#333; margin-top:20px;'>{metric['title']}</h3>"
        for label, value in zip(metric['labels'], metric['values']):
            charts_html += (
                "<div style='margin-bottom:12px; font-family:sans-serif;'>"
                f"<p style='margin:0 0 5px 0;'>- {label}: {value}%</p>"
                "<div style='background:#e0e0e0; border-radius:8px; width:100%; height:16px;'>"
                f"<div style='background:#4CAF50; width:{value}%; height:16px; border-radius:8px;'></div>"
                "</div></div>"
            )
    return charts_html


def generate_footer_html():
    return (
        "<div style='margin-top:40px; border-left:4px solid #4CAF50; padding-left:15px; font-family:sans-serif;'>"
        "<h3 style='font-size:22px; font-weight:bold; color:#333;'>📊 由 KataChat AI 生成的见解</h3>"
        "<p style='font-size:18px; color:#555; line-height:1.6;'>此健康报告使用 KataChat AI 模型生成，基于：</p>"
        "<ul style='list-style-type:disc; padding-left:20px; font-size:18px; color:#555; line-height:1.6;'>"
        "<li>新加坡、马来西亚及台湾用户匿名健康数据</li>"
        "<li>可信 OpenAI 研究库全球健康基准</li>"
        "</ul>"
        "<p style='font-size:18px; color:#555; line-height:1.6; margin-top:15px;'>🛡️ <strong>请注意：</strong>本报告非医疗诊断。如有严重健康问题，请咨询专业人士。</p>"
        "<p style='font-size:18px; color:#555; line-height:1.6; margin-top:15px;'>📬 <strong>附注：</strong>报告将在 24-48 小时内通过邮箱发送。如需深入讨论，可预约 15 分钟通话。</p>"
        "</div>"
    )

# --- Email Sending ---
def send_email_report(recipient, subject, body):
    if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD]):
        logging.warning("SMTP 配置不完整，跳过发送邮件。")
        return
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"KataChat AI <{SMTP_USERNAME}>"
        msg['To'] = recipient
        msg.attach(MIMEText(body, 'html', 'utf-8'))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, [recipient], msg.as_string())
        logging.info(f"健康报告已发送至 {recipient}")
    except Exception as e:
        logging.error(f"邮件发送失败: {e}")
        traceback.print_exc()

# --- Flask App and Endpoint ---
app = Flask(__name__)
CORS(app)

@app.route("/health_analyze", methods=["POST"])
def health_analyze():
    try:
        data = request.get_json(force=True)
        lang = data.get("lang", "zh").lower()
        if lang != 'zh':
            return jsonify({"error": "仅支持中文 (zh) 端点。"}), 400

        labels = LANGUAGE_TEXTS[lang]
        content_lang = LANGUAGE[lang]

        dob = f"{data.get('dob_year')}-{int(data.get('dob_month', 0)):02d}-{int(data.get('dob_day', 0)):02d}"
        age = compute_age(dob)

        user_info = {k: data.get(k) for k in [
            "name","chinese_name","gender","height","weight",
            "country","condition","referrer","angel","details"
        ]}
        user_info.update({"dob": dob, "age": age, "notes": data.get("details") or "无补充说明"})

        # Generate AI metrics
        chart_prompt = (
            f"### 请为来自 {user_info['country']} 的 {age} 岁 {user_info['gender']}，关注“{user_info['condition']}”，生成 3 个健康指标类别。"
            "每个类别以 '###' 开头，包含 3 项指标，格式“指标: xx%”，百分比介于 25%-90%。"
        )
        metrics = generate_metrics_with_ai(chart_prompt)

        # Summary and suggestions
        summary_prompt = build_summary_prompt(
            age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes'], metrics
        )
        summary = get_openai_response(summary_prompt)

        suggestions_prompt = build_suggestions_prompt(
            age, user_info['gender'], user_info['country'], user_info['condition'], user_info['notes']
        )
        creative = get_openai_response(suggestions_prompt, temp=0.85)

        # Build email HTML with proper paragraph splitting
        short_paras = [p.strip() for p in summary.split("\n\n") if p.strip()]
        summary_html = "".join(f"<p style='line-height:1.7; font-size:16px;'>{p}</p>" for p in short_paras)

        email_html_body = f"""
        <div style='font-family:sans-serif; color:#333; max-width:800px; margin:auto; padding:20px;'>
            <h1 style='text-align:center; color:#333;'>{content_lang['report_title']}</h1>
            {generate_user_data_html(user_info, labels)}
            {generate_custom_charts_html(metrics)}
            <div style='margin-top:30px;'>
                <h2 style='font-family:sans-serif; color:#333; border-bottom:2px solid #4CAF50; padding-bottom:5px;'>🧠 摘要</h2>
                {summary_html}
            </div>
            <div style='margin-top:30px;'>
                <h2 style='font-family:sans-serif; color:#333; border-bottom:2px solid #4CAF50; padding-bottom:5px;'>💡 生活建议</h2>
                {''.join(f"<p style='margin:12px 0; font-size:16px; line-height:1.6;'>{line}</p>" for line in creative.splitlines() if line.strip())}
            </div>
            {generate_footer_html()}
        </div>
        """

        # Send email
        subject = f"{content_lang['email_subject']} - {user_info.get('name','N/A')}"
        send_email_report(SMTP_USERNAME, subject, email_html_body)

        # Build web response
        html_parts = [f"<p style='line-height:1.7; font-size:16px; margin:1em 0;'>{p}</p>" for p in summary.split("\n\n") if p.strip()]
        html_result = (
            "<div style='font-family:sans-serif; color:#333;'>"
            "<div style='font-size:24px; font-weight:bold; margin-top:30px;'>🧠 摘要:</div>"
            + "".join(html_parts)
            + "<div style='font-size:24px; font-weight:bold; margin-top:40px;'>💡 生活建议:</div>"
            + "".join(f"<p style='margin:16px 0; font-size:17px; line-height:1.6;'>{l}</p>" for l in creative.split("\n") if l.strip())
            + generate_footer_html()
            + "</div>"
        )

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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
