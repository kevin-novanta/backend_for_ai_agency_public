import os
import sys
import re

# Ensure project root is on sys.path so absolute imports work when running this file directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

import json
import openai

def remove_brackets_only(text):
    return re.sub(r"\[.*?\]", "", text).strip()

with open("/Users/kevinnovanta/backend_for_ai_agency/Creds/gpt_key.json") as f:
    secrets = json.load(f)
openai.api_key = secrets.get("api_key") or secrets.get("OPENAI_API_KEY")

def generate_personalized_email(lead):
    company_name = lead.get("Company Name", "").strip()
    offer_summary = lead.get("Custom 2", "").strip() or lead.get("Industry", "").strip()
    overview = lead.get("Overview", "").strip()

    base_subject = "Quick Question"
    base_body = "Hey – just came across your company and had an idea. Mind if I share?"

    prompt = (
        f"You are given a base email subject and body:\n"
        f"Subject: {base_subject}\n"
        f"Body: {base_body}\n\n"
        f"Please rewrite the subject and body to be personalized for a company with the following details:\n"
        f"Company Name: {company_name}\n"
        f"Offer Summary: {offer_summary}\n"
        f"Overview: {overview}\n\n"
        f"Keep the structure similar but add personalization and relevance based on these details.\n"
        f"Respond only with a strict JSON object in the following format:\n"
        f'{{\n  "subject": "...",\n  "body_html": "..." \n}}\n'
        f"Do not include any other text or explanation."
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        output = response.choices[0].message.content.strip()
        try:
            parsed = json.loads(output)
            subject = parsed.get("subject", base_subject)
            body_html = parsed.get("body_html", base_body)
        except json.JSONDecodeError:
            # Fallback: parse plain text output for subject and body_html
            subject = base_subject
            body_html = base_body
            lines = output.split("\n")
            for line in lines:
                if line.lower().startswith("subject:"):
                    subject = line.split(":", 1)[1].strip()
                elif line.lower().startswith("body:"):
                    body_html = line.split(":", 1)[1].strip()
                else:
                    body_html += "\n" + line.strip()
            body_html = str(body_html)

        subject = remove_brackets_only(subject)
        body_html = remove_brackets_only(body_html)
        return {"subject": subject, "body_html": body_html}

    except Exception as e:
        print(f"❌ Error generating personalized email: {e}")
        subject = remove_brackets_only(base_subject)
        body_html = remove_brackets_only(base_body)
        return {"subject": subject, "body_html": body_html}