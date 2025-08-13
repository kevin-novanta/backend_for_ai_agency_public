import os
def render_llm_email(template_name, lead, fallback_subject="", llm_opts=None, context=None):
    subj = fallback_subject or f"Follow-up for {lead.get('Company Name','your team')}"
    body = f"Hi there — demo follow-up for {lead.get('Company Name','your team')}."
    if os.getenv("OPENAI_API_KEY"): pass
    return {"subject": subj, "body_one_paragraph": body}
