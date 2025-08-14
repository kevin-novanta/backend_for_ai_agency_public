import json
import re
import os
from openai import OpenAI

# Load your OpenAI API key from JSON file
with open("/Users/kevinnovanta/backend_for_ai_agency/Creds/gpt_key.json") as f:
    openai_key = json.load(f)["api_key"]

client = OpenAI(api_key=openai_key)

# === Prompt loader helpers ===
def _load_opener_prompt():
    """Load opener prompt from env or default txt file."""
    p = os.environ.get("OPENER_PROMPT")
    if p:
        print("🔍 _load_opener_prompt: Loaded prompt from environment variable OPENER_PROMPT")
        print(f"🔍 _load_opener_prompt: Prompt snippet: {p[:100]}{'...' if len(p) > 100 else ''}")
        return p
    path = os.environ.get("OPENER_PROMPT_PATH") or \
           "/Users/kevinnovanta/backend_for_ai_agency/workflows/outreach_sender/Utils/opener_prompt.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            print(f"🔍 _load_opener_prompt: Loaded prompt from file at path: {path}")
            print(f"🔍 _load_opener_prompt: Prompt snippet: {content[:100]}{'...' if len(content) > 100 else ''}")
            return content
    except Exception as e:
        print(f"❌ _load_opener_prompt: Failed to load prompt from file at path: {path}, error: {e}")
        return ""

def _load_subject_prompt():
    """Load generic subject prompt from env or default txt file."""
    p = os.environ.get("SUBJECT_PROMPT")
    if p:
        print("🔍 _load_subject_prompt: Loaded prompt from environment variable SUBJECT_PROMPT")
        print(f"🔍 _load_subject_prompt: Prompt snippet: {p[:100]}{'...' if len(p) > 100 else ''}")
        return p
    path = os.environ.get("SUBJECT_PROMPT_PATH") or \
           "/Users/kevinnovanta/backend_for_ai_agency/workflows/outreach_sender/Utils/subject_prompt.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            print(f"🔍 _load_subject_prompt: Loaded prompt from file at path: {path}")
            print(f"🔍 _load_subject_prompt: Prompt snippet: {content[:100]}{'...' if len(content) > 100 else ''}")
            return content
    except Exception as e:
        print(f"❌ _load_subject_prompt: Failed to load prompt from file at path: {path}, error: {e}")
        return ""

def remove_brackets_only(subject, body_html):
    print(f"🔍 remove_brackets_only: Original subject: {subject}")
    print(f"🔍 remove_brackets_only: Original body_html: {body_html}")
    subject_clean = re.sub(r"\[.*?\]", "", subject)
    body_clean = re.sub(r"\[.*?\]", "", body_html)
    print(f"🔍 remove_brackets_only: Cleaned subject: {subject_clean}")
    print(f"🔍 remove_brackets_only: Cleaned body_html: {body_clean}")
    return subject_clean, body_clean

def build_prompt():
    print("🔍 build_prompt: Building opener prompt...")
    prompt = _load_opener_prompt()
    print(f"🔍 build_prompt: Loaded prompt length: {len(prompt)}")
    print(f"🔍 build_prompt: Prompt snippet: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    return prompt

def _normalize_linebreaks(text: str) -> str:
    """Convert any <br> pairs to \n\n and normalize spacing; keep \n\n intact."""
    if not isinstance(text, str):
        return ""
    t = text.replace("\r\n", "\n")
    # HTML <br> -> newlines
    t = re.sub(r"(<br\s*/?>\s*){2,}", "\n\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    # Collapse 3+ newlines to exactly two
    t = re.sub(r"\n{3,}", "\n\n", t)
    # Trim trailing spaces per line
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    return t.strip()


def _light_smooth(text: str) -> str:
    """Very light smoothing without removing content: fix 'Hi ,', extra spaces, common artifacts."""
    if not isinstance(text, str):
        return ""
    t = text
    # Hi , -> Hi there,
    t = re.sub(r"\bHi\s*,\b", "Hi there,", t)
    t = re.sub(r"\bHello\s*,\b", "Hello there,", t)
    # Remove ' at .' / ' with .' / ' for .' fragments
    t = re.sub(r"\b(at|with|for)\s*\.(?=\s|$)", "", t, flags=re.IGNORECASE)
    # Article fix: a audit -> an audit
    t = re.sub(r"\ba\s+(?=[aeiouAEIOU])", "an ", t)
    # Collapse 2+ spaces
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _extract_subject_and_body_from_freeform(content: str):
    """Extract a subject if a 'Subject:' header exists; otherwise return None for subject.
    Always return the body as the original text (normalized) with minimal smoothing."""
    if not isinstance(content, str):
        return None, ""
    lines = [l.rstrip() for l in content.splitlines()]
    subject = None
    body_lines = []
    for i, line in enumerate(lines):
        if i == 0 and line.lower().startswith("subject:"):
            subject = line[len("subject:"):].strip()
            body_lines = lines[i+1:]
            break
    else:
        # No explicit Subject: header; whole content is body
        body_lines = lines
    body_text = "\n".join(body_lines)
    body_text = _light_smooth(body_text)
    # Final guard: if subject exists, smooth it lightly too
    if subject:
        subject = _light_smooth(subject)
    return subject, body_text

def generate_generic_subject():
    """Generate a concise, generic subject using a configurable prompt file."""
    prompt = _load_subject_prompt() or "Return ONLY JSON: {\"subject\": \"Quick question\"}"
    print(f"🔍 generate_generic_subject: Sending prompt to OpenAI:\n{prompt}")
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write concise, non-spammy email subjects."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )
        content = resp.choices[0].message.content
        print(f"🔍 generate_generic_subject: Raw AI content received:\n{content}")
        try:
            data = json.loads(content)
            print(f"🔍 generate_generic_subject: Parsed JSON data: {data}")
            subj = data.get("subject", "Quick question")
        except Exception as e:
            print(f"⚠️ generate_generic_subject: JSON parsing failed: {e}, using fallback subject")
            subj = "Quick question"
        subj = re.sub(r"\[.*?\]", "", subj)
        print(f"🔍 generate_generic_subject: Final sanitized subject: {subj.strip() or 'Quick question'}")
        return {"subject": subj.strip() or "Quick question"}
    except Exception as e:
        print(f"❌ Error generating generic subject: {e}")
        return {"subject": "Quick question"}

def generate_email(lead):
    """
    Sends a prompt to OpenAI and returns a generic subject and body_html for a cold outreach email.
    """
    prompt = build_prompt()
    print(f"🔍 generate_email: Using prompt:\n{prompt}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a B2B cold email generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        content = response.choices[0].message.content
        print(f"🔍 generate_email: Raw AI content received (freeform):\n{content}")

        # No JSON expectation: extract minimally
        subj, body_text = _extract_subject_and_body_from_freeform(content)
        email = {
            # Subject will be overridden by generate_generic_subject() later; keep None/empty safe
            "subject": subj or "",
            # Keep body as plain text with \n\n; runner/personalizer can convert if needed
            "body_html": body_text
        }
        print(f"🔍 generate_email: Using freeform email (no JSON parsing). Subject: '{email['subject']}' | Body preview: {email['body_html'][:140]}{'...' if len(email['body_html'])>140 else ''}")
        return email

    except Exception as e:
        print(f"❌ Error generating email: {e}")
        return {"subject": "Quick question", "body_html": ""}

def generate_email_from_prompt(prompt, openai_key):
    """
    Sends a custom prompt to OpenAI and returns the subject and body_html.
    """
    local_client = OpenAI(api_key=openai_key)

    try:
        print(f"🔍 generate_email_from_prompt: Prompt being sent:\n{prompt}")
        response = local_client.chat.completions.create(
           model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a B2B cold email generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        content = response.choices[0].message.content
        print(f"🔍 generate_email_from_prompt: Raw AI content received (freeform):\n{content}")

        subj, body_text = _extract_subject_and_body_from_freeform(content)
        email = {"subject": subj or "", "body_html": body_text}
        print(f"🔍 generate_email_from_prompt: Using freeform email (no JSON parsing). Subject: '{email['subject']}' | Body preview: {email['body_html'][:140]}{'...' if len(email['body_html'])>140 else ''}")
        return email

    except Exception as e:
        print(f"❌ Error generating email from prompt: {e}")
        return {"subject": "Quick question", "body_html": ""}
