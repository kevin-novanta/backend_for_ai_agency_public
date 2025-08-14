# === Personalizer helpers ===
def _load_subject_personalizer_prompt(prompt_override=None):
    if prompt_override is not None:
        print(f"[Personalizer] Using provided prompt override for subject personalizer.")
        return prompt_override
    env_prompt = os.environ.get("SUBJECT_PERSONALIZER_PROMPT")
    if env_prompt:
        print(f"[Personalizer] Loaded subject personalizer prompt from environment variable SUBJECT_PERSONALIZER_PROMPT.")
        return env_prompt
    path = os.environ.get("SUBJECT_PERSONALIZER_PROMPT_PATH") or \
           "/Users/kevinnovanta/backend_for_ai_agency/workflows/outreach_sender/Utils/subject_personalizer_prompt.txt"
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
            print(f"[Personalizer] Loaded subject personalizer prompt from file: {path}")
            return prompt_content
    print(f"[Personalizer] No subject personalizer prompt found. Returning empty prompt.")
    return ""
# Deprecated: use personalize_email(base_subject, base_body_html, lead, prompt_override=None)
def personalize_subject(base_subject, lead, prompt_override=None):
    """Personalize a subject line using lead data and a configurable prompt."""
    prompt = _load_subject_personalizer_prompt(prompt_override)
    print(f"[Personalizer] Loaded subject personalizer prompt. (First 300 chars): {prompt[:300]!r}")
    token_map = _build_token_map(lead, base_subject, "")
    print(f"[Personalizer] Sample lead data: {dict(list(lead.items())[:3])}")
    prompt = _render_placeholders(prompt, token_map)

    # Specialize generic phrasing in the base subject before sending
    company_name = token_map.get("company_name", "")
    offer_summary = token_map.get("custom_2", "") or token_map.get("industry", "")
    base_subject = _specialize_subject(base_subject or "", company_name, offer_summary)

    payload = json.dumps({
        "base_subject": base_subject,
        "company_name": company_name,
        "offer_summary": offer_summary,
        "overview": token_map.get("overview", ""),
        "custom_1": token_map.get("custom_1", "")
    })

    model_name = "gpt-4o-mini"
    prompt_tokens = len(prompt.split())
    print(f"[Personalizer] Preparing to send request to AI API. Model: {model_name}, Prompt tokens: {prompt_tokens}")
    print(f"[Personalizer] Prompt preview (first 300 chars): {prompt[:300]!r}")
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You write concise, non-spammy subject lines for B2B cold emails."},
                {"role": "user", "content": prompt.strip()},
                {"role": "user", "content": f"Lead and base subject JSON:\n{payload}"}
            ],
            temperature=0.5,
            max_tokens=80,
        )
        output = response.choices[0].message.content.strip()
        print(f"[Personalizer] Raw AI output: {output!r}")
        print("[Personalizer] Starting sanitation of AI output...")
        try:
            parsed = json.loads(output)
            subject = parsed.get("subject", base_subject)
        except Exception:
            subject = base_subject
    except Exception as e:
        print(f"[Personalizer] Exception during AI request: {e}")
        subject = base_subject

    subject = remove_brackets_only(subject)
    print(f"[Personalizer] Sanitized subject: {subject!r}")
    print(f"[Personalizer] Personalization complete for lead: {lead.get('Email', '[no email]')}")
    return {"subject": subject or (base_subject or "Quick question")}
import os
import sys
import re

# Ensure project root is on sys.path so absolute imports work when running this file directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

import json
from openai import OpenAI

def remove_brackets_only(text):
    return re.sub(r"\[.*?\]", "", text).strip()

def _aliases_for_key(key) -> list:
    """
    Given a key, return a list of aliases:
    - original key (as string)
    - lowercase
    - snake_case version
    Safely handles None and non-string keys.
    """
    def to_snake_case(s: str) -> str:
        s = re.sub(r'[\s\-]+', '_', s)
        s = re.sub(r'([A-Z]+)', lambda m: '_' + m.group(1).lower(), s)
        s = re.sub(r'^_', '', s)
        s = s.lower()
        return s

    if key is None:
        print("[Personalizer] Warning: encountered None key in lead; skipping alias generation.")
        return []
    try:
        key_str = str(key)
    except Exception:
        print(f"[Personalizer] Warning: could not stringify key {key!r}; skipping.")
        return []

    aliases = [key_str, key_str.lower(), to_snake_case(key_str)]
    # Deduplicate while preserving order
    seen = set()
    result = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            result.append(a)
    return result

def _build_token_map(lead, base_subject, base_body_html):
    """
    Build a dict mapping placeholder names to values.
    Includes:
    - original keys from lead plus aliases
    - convenience keys: company_name, custom_2, industry, overview, custom_1, email
    - base_subject, base_body_html
    """
    token_map = {}

    # Add original keys and their aliases (robust to None / non-strings)
    for key, value in lead.items():
        alias_list = _aliases_for_key(key)
        if not alias_list:
            continue
        safe_val = "" if value is None else value
        for alias in alias_list:
            token_map[alias] = safe_val

    # Convenience keys with fallback to empty string if missing
    token_map['company_name'] = lead.get("Company Name", "") or ""
    token_map['custom_2'] = lead.get("Custom 2", "") or ""
    token_map['industry'] = lead.get("Industry", "") or ""
    token_map['overview'] = lead.get("Overview", "") or ""
    token_map['custom_1'] = lead.get("Custom 1", "") or ""
    token_map['email'] = lead.get("Email", "") or ""

    token_map['base_subject'] = base_subject or ""
    token_map['base_body_html'] = base_body_html or ""

    return token_map

def _render_placeholders(template: str, token_map: dict) -> str:
    """
    Replace {{token}} placeholders in template with values from token_map.
    Unknown tokens replaced with empty string.
    Lookup tries raw token, then snake_case and stripped variants.
    """
    def to_snake_case(s):
        s = s.strip()
        s = re.sub(r'[\s\-]+', '_', s)
        s = s.lower()
        return s

    pattern = re.compile(r"\{\{\s*([\w\s\-]+)\s*\}\}")

    def replacer(match):
        token = match.group(1)
        # Try raw token
        if token in token_map:
            return str(token_map[token])
        # Try stripped token
        stripped = token.strip()
        if stripped in token_map:
            return str(token_map[stripped])
        # Try snake_case token
        snake = to_snake_case(token)
        if snake in token_map:
            return str(token_map[snake])
        # Not found, replace with empty string
        return ""

    return pattern.sub(replacer, template)

# === Personalizer helpers ===
def _load_prompt_override(prompt_override=None):
    """
    Loads a prompt override from argument, env var PERSONALIZER_PROMPT, env var PERSONALIZER_PROMPT_PATH,
    or from default file path. Returns a string.
    """
    if prompt_override is not None:
        print(f"[Personalizer] Using provided prompt override for email personalizer.")
        return prompt_override
    env_prompt = os.environ.get("PERSONALIZER_PROMPT")
    if env_prompt:
        print(f"[Personalizer] Loaded personalizer prompt from environment variable PERSONALIZER_PROMPT.")
        return env_prompt
    prompt_path = os.environ.get("PERSONALIZER_PROMPT_PATH")
    if prompt_path and os.path.isfile(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
            print(f"[Personalizer] Loaded personalizer prompt from file: {prompt_path}")
            return prompt_content
    # fallback to default file path
    default_path = "/Users/kevinnovanta/backend_for_ai_agency/workflows/outreach_sender/Utils/personalizer_prompt.txt"
    if os.path.isfile(default_path):
        with open(default_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
            print(f"[Personalizer] Loaded personalizer prompt from default file: {default_path}")
            return prompt_content
    print(f"[Personalizer] No personalizer prompt found. Returning empty prompt.")
    return ""  # If all else fails, return empty string

def _clean_pair(subj, body):
    """
    Applies remove_brackets_only to both subject and body, returns tuple.
    """
    return remove_brackets_only(subj), remove_brackets_only(body)

def _ensure_sentence_linebreaks(text: str) -> str:
    """Ensure each sentence ends with a blank line ("\n\n"). Conservative and punctuation-aware."""
    if not text:
        return ""
    # Normalize Windows newlines then split on sentence enders.
    t = (text or "").replace("\r\n", "\n")
    # First, collapse multiple blank lines to max two.
    t = re.sub(r"\n{3,}", "\n\n", t)
    # Ensure a blank line after sentence enders if not already present.
    t = re.sub(r"([.!?])\s*(?!\n\n)", r"\1\n\n", t)
    # Trim whitespace
    return t.strip()

def _fix_company_like_yours(text: str, company_name: str) -> str:
    """Replace awkward patterns like '<Company> like yours' with 'companies like yours'."""
    if not text:
        return ""
    cn = (company_name or "").strip()
    out = text
    if cn:
        # Case-insensitive replace of '<Company> like yours' → 'companies like yours'
        pattern = re.compile(re.escape(cn) + r"\s+like\s+yours", re.IGNORECASE)
        out = pattern.sub("companies like yours", out)
    # Also guard more generic accidental constructions
    out = re.sub(r"\b[a-zA-Z0-9&\-\s]+\s+like\s+yours\b", "companies like yours", out)

    # --- NEW: handle dangling patterns when company_name is missing ---
    # Fix greetings like 'Hi ,' or 'Hi  ,' -> 'Hi there,'
    out = re.sub(r'\bHi\s*,', 'Hi there,', out)
    out = re.sub(r'\bHi\s{2,},', 'Hi there,', out)
    # Remove incomplete phrases like 'resonate with .' or 'for .'
    out = re.sub(r'\bresonate with\s*\.', '', out, flags=re.IGNORECASE)
    out = re.sub(r'\bfor\s*\.', '', out, flags=re.IGNORECASE)
    # Remove any 'with .' at sentence end
    out = re.sub(r'with\s*\.', '', out, flags=re.IGNORECASE)
    # Remove multiple spaces left after removals
    out = re.sub(r' {2,}', ' ', out)
    # Remove double commas or stray spaces before commas
    out = re.sub(r'\s+,', ',', out)
    out = re.sub(r',\s+,', ',', out)
    return out

def _offer_hint(offer_summary: str) -> str:
    """Derive a short, neutral hint from messy offer text (drops first-person fluff)."""
    if not offer_summary:
        return ""
    t = offer_summary.strip()
    # Remove leading first-person phrases
    t = re.sub(r"^\s*(we|our|i)\s+(specialize\s+in|love\s+to|love\s+doing|help|offer)\b[:\s-]*", "", t, flags=re.IGNORECASE)
    # Remove trailing calls to action or exclamations
    t = re.sub(r"\b(contact|book|schedule|call|click)\b.*$", "", t, flags=re.IGNORECASE)
    # Keep it short and noun/verb heavy
    t = re.sub(r"[^\w\s&/-]", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # Limit to ~12 words
    words = t.split()
    if len(words) > 12:
        t = " ".join(words[:12])
    return t


def _specialize_generic_claims(text: str, company_name: str, offer_summary: str) -> str:
    """Replace generic phrases (businesses/companies/business owners/teams) with a specific company name or offer summary."""
    if not text:
        return text or ""
    cn = (company_name or "").strip()
    osum = (offer_summary or "").strip()
    target = cn or osum
    out = text
    # If both company_name and offer_summary are missing, fallback to offer_hint or remove/smooth phrases
    if not target:
        # Try to use offer_hint if possible
        offer_hint = _offer_hint(offer_summary)
        if offer_hint:
            # Replace generic recipient phrases with offer_hint
            out = re.sub(r"\bwe\s+help\s+(?:business\s*owners|businesses|companies|teams)\b", f"we help {offer_hint}", out, flags=re.IGNORECASE)
            out = re.sub(r"\bfor\s+(?:business\s*owners|businesses|companies|teams)\b", f"for {offer_hint}", out, flags=re.IGNORECASE)
            out = re.sub(r"\bhelp\s+(?:your|their)\s+(?:business|company)\b", f"help {offer_hint}", out, flags=re.IGNORECASE)
        else:
            # Remove or smooth dangling placeholders
            out = re.sub(r"\bwe\s+help\s+(?:business\s*owners|businesses|companies|teams)\b", "we help", out, flags=re.IGNORECASE)
            out = re.sub(r"\bfor\s+(?:business\s*owners|businesses|companies|teams)\b", "", out, flags=re.IGNORECASE)
            out = re.sub(r"\bhelp\s+(?:your|their)\s+(?:business|company)\b", "help", out, flags=re.IGNORECASE)
        return out
    # If we have a target, proceed as before
    out = re.sub(r"\bwe\s+help\s+(?:business\s*owners|businesses|companies|teams)\b", f"we help {target}", out, flags=re.IGNORECASE)
    out = re.sub(r"\bfor\s+(?:business\s*owners|businesses|companies|teams)\b", f"for {target}", out, flags=re.IGNORECASE)
    out = re.sub(r"\bhelp\s+(?:your|their)\s+(?:business|company)\b", f"help {target}", out, flags=re.IGNORECASE)
    return out


def _specialize_subject(subject: str, company_name: str, offer_summary: str) -> str:
    """Lightly specialize generic subject phrasing using company name or offer summary."""
    subj = subject or ""
    cn = (company_name or "").strip()
    osum = (offer_summary or "").strip()
    target = cn or osum
    if not target:
        return subj
    subj = re.sub(r"\byour\s+business\b", target, subj, flags=re.IGNORECASE)
    return subj


with open("/Users/kevinnovanta/backend_for_ai_agency/Creds/gpt_key.json") as f:
    secrets = json.load(f)
_api_key = secrets.get("api_key") or secrets.get("OPENAI_API_KEY")
if _api_key:
    os.environ.setdefault("OPENAI_API_KEY", _api_key)
client = OpenAI()

def personalize_email(base_subject, base_body_html, lead, prompt_override=None):
    """
    Personalizes a base email subject/body_html for a given lead using OpenAI.
    Loads a prompt override from argument/env/file, builds JSON context, and expects only JSON response.
    If parsing fails, returns base subject/body unchanged.
    Removes bracketed placeholders before returning.
    """
    # 1. Load prompt
    prompt = _load_prompt_override(prompt_override)
    print(f"[Personalizer] Loaded email personalizer prompt. (First 300 chars): {prompt[:300]!r}")

    token_map = _build_token_map(lead, base_subject, base_body_html)
    print(f"[Personalizer] Sample lead data: {dict(list(lead.items())[:3])}")
    prompt = _render_placeholders(prompt, token_map)

    # 1a. Specialize generic claims in the base subject/body using company/offer
    company_name = token_map.get("company_name", "")
    offer_summary = token_map.get("custom_2", "") or token_map.get("industry", "")
    offer_hint = _offer_hint(offer_summary)
    base_subject = _specialize_subject(base_subject, company_name, offer_summary)
    base_body_html = _specialize_generic_claims(base_body_html, company_name, offer_summary)
    # Keep token_map in sync so placeholders like {{base_body_html}} reflect the specialized text
    token_map["base_subject"] = base_subject
    token_map["base_body_html"] = base_body_html

    # 2. Build payload with relevant lead fields
    lead_payload = {
        "base_subject": base_subject,
        "base_body_html": base_body_html,
        "company_name": lead.get("Company Name", ""),
        "offer_summary": lead.get("Custom 2", "") or lead.get("Industry", ""),
        "offer_hint": offer_hint,
        "overview": lead.get("Overview", ""),
        "custom_1": lead.get("Custom 1", "")
    }
    payload_json = json.dumps(lead_payload)

    model_name = "gpt-4o-mini"
    prompt_tokens = len(prompt.split())
    print(f"[Personalizer] Preparing to send request to AI API. Model: {model_name}, Prompt tokens: {prompt_tokens}")
    print(f"[Personalizer] Prompt preview (first 300 chars): {prompt[:300]!r}")
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You rewrite emails with subtle, high-signal personalization."},
                {"role": "user", "content": prompt.strip()},
                {"role": "user", "content": f"Lead and base email JSON:\n{payload_json}"}
            ],
            temperature=0.7,
            max_tokens=350,
        )
        output = response.choices[0].message.content.strip()
        print(f"[Personalizer] Raw AI output: {output!r}")
        print("[Personalizer] Starting sanitation of AI output...")
        try:
            parsed = json.loads(output)
            subject = parsed.get("subject", base_subject)
            body_html = parsed.get("body_html", base_body_html)
        except Exception:
            # fallback: return base subject/body
            subject = base_subject
            body_html = base_body_html
    except Exception as e:
        print(f"[Personalizer] Exception during AI request: {e}")
        # On any error, return base subject/body
        subject = base_subject
        body_html = base_body_html

    subject, body_html = _clean_pair(subject, body_html)
    # --- Remove linebreak normalization so line breaks are preserved as generated by the AI ---
    body_html = _fix_company_like_yours(body_html, company_name)
    # --- NEW: Fix articles before vowel-starting words (e.g., 'a audit' -> 'an audit') ---
    def fix_articles(text):
        # Replace 'a <vowel>' with 'an <vowel>', case-insensitive, word boundary
        return re.sub(r'\ba\s+([aeiouAEIOU])', r'an \1', text)
    body_html = fix_articles(body_html)
    subject = fix_articles(subject)
    print(f"[Personalizer] Sanitized subject: {subject!r}")
    print(f"[Personalizer] Sanitized body_html preview (first 300 chars): {body_html[:300]!r}")
    print(f"[Personalizer] Personalization complete for lead: {lead.get('Email', '[no email]')}")
    return {"subject": subject, "body_html": body_html}


# Deprecated: use personalize_email(base_subject, base_body_html, lead, prompt_override=None)
def generate_personalized_email(lead):
    company_name = lead.get("Company Name", "").strip()
    offer_summary = lead.get("Custom 2", "").strip() or lead.get("Industry", "").strip()
    overview = lead.get("Overview", "").strip()

    base_subject = "Quick Question"
    base_body = "Hey – just came across your company and had an idea. Mind if I share?"

    print(f"[Personalizer] Sample lead being processed: {dict(list(lead.items())[:3])}")
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

    model_name = "gpt-4o-mini"
    prompt_tokens = len(prompt.split())
    print(f"[Personalizer] Preparing to send request to AI API. Model: {model_name}, Prompt tokens: {prompt_tokens}")
    print(f"[Personalizer] Prompt preview (first 300 chars): {prompt[:300]!r}")
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        output = response.choices[0].message.content.strip()
        print(f"[Personalizer] Raw AI output: {output!r}")
        print("[Personalizer] Starting sanitation of AI output...")
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
        print(f"[Personalizer] Sanitized subject: {subject!r}")
        print(f"[Personalizer] Sanitized body_html preview (first 300 chars): {body_html[:300]!r}")
        print(f"[Personalizer] Personalization complete for lead: {lead.get('Email', '[no email]')}")
        return {"subject": subject, "body_html": body_html}

    except Exception as e:
        print(f"❌ Error generating personalized email: {e}")
        subject = remove_brackets_only(base_subject)
        body_html = remove_brackets_only(base_body)
        print(f"[Personalizer] Personalization complete for lead: {lead.get('Email', '[no email]')}")
        return {"subject": subject, "body_html": body_html}