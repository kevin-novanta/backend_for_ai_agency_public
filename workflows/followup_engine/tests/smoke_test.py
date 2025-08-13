from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any

from workflows.followup_engine.utils import logger

class LLMUnavailable(Exception):
    pass

class LLMClient:
    """Very small wrapper around an LLM provider.
    - Tries OpenAI via key file at GPT_KEY_PATH; falls back to env var if you extend it later.
    - If unavailable, raise LLMUnavailable so callers can gracefully fallback.
    """
    def __init__(self):
        # Path to your key file
        GPT_KEY_PATH = Path("/Users/kevinnovanta/backend_for_ai_agency/Creds/gpt_key.json")

        api_key = None
        if GPT_KEY_PATH.exists():
            with open(GPT_KEY_PATH, "r") as f:
                data = json.load(f)
                api_key = data.get("OPENAI_API_KEY") or data.get("api_key")

        self.api_key = api_key
        # Lazy import to avoid hard dependency if not installed
        self._openai = None
        try:
            import openai  # type: ignore
            if self.api_key:
                openai.api_key = self.api_key
            else:
                logger.warn(f"⚠️ No OpenAI API key found at {GPT_KEY_PATH}")
            self._openai = openai
        except Exception:
            # If the SDK isn't installed, treat as unavailable
            self._openai = None

    def available(self) -> bool:
        return bool(self._openai and self.api_key)

    def generate_email(self, *, system: str, prompt: str, temperature: float = 0.3, max_tokens: int = 220) -> Dict[str, str]:
        if not self.available():
            raise LLMUnavailable("No LLM provider available or API key not set.")
        try:
            resp = self._openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise LLMUnavailable(f"LLM call failed: {e}")

        import json as _json
        subject = ""
        body = ""
        try:
            data = _json.loads(text)
            subject = (data.get("subject") or "").strip()
            body = (data.get("body_one_paragraph") or data.get("body") or "").strip()
        except Exception:
            body = text
        return {"subject": subject, "body_one_paragraph": " ".join(body.split())}


def render_llm_email(template_name: str, lead: Dict[str, Any], *, fallback_subject: str = "", llm_opts: Dict[str, Any] | None = None, context: Dict[str, Any] | None = None) -> Dict[str, str]:
    llm_opts = llm_opts or {}
    context = context or {}

    company = (lead.get("Company Name") or lead.get("Company") or "your team").strip()
    desc = (lead.get("Custom 2") or "").strip()
    first_name = (lead.get("First Name") or lead.get("FirstName") or "there").strip()

    opener_summary = context.get("opener_summary", "Short follow-up on my earlier note.")
    thread_summary = context.get("thread_summary", "No prior replies from the prospect yet.")

    system = (
        "You are an expert B2B SDR writing concise, friendly follow-up emails for workflow automation.\n"
        "Rules:\n- One paragraph, 3–6 sentences.\n- Reference the opener gently; don't repeat it.\n- Personalize with company and the short description if relevant.\n- Avoid links.\n- Keep language concrete and simple.\n- Output strict JSON with keys: subject, body_one_paragraph."
    )

    style = llm_opts.get("style", "concise, friendly, expert")
    constraints = llm_opts.get("constraints", {"one_paragraph": True, "csv_safe": True, "avoid_links": True})
    temperature = float(llm_opts.get("temperature", 0.3))
    max_tokens = int(llm_opts.get("max_tokens", 220))

    prompt = (
        f"Prospect: {first_name} at {company}.\n"
        f"Company description: {desc or 'n/a'}.\n"
        f"Opener summary: {opener_summary}.\n"
        f"Thread summary: {thread_summary}.\n"
        f"Style: {style}. Constraints: {constraints}.\n"
        "Task: Write a follow-up that advances the conversation with a low-friction CTA (e.g., 'Want a 60-sec loom?').\n"
        "Return JSON {\"subject\": \"...\", \"body_one_paragraph\": \"...\"}."
    )

    client = LLMClient()
    if not client.available():
        subj = fallback_subject or f"A quick win for {company}"
        body = (
            f"Hey {first_name}, following up on my earlier note — based on what {company} does"
            f"{(': ' + desc) if desc else ''}, I can share a 60-sec loom showing the exact workflow."
            " If now isn't ideal, happy to circle back later or close the loop."
        )
        return {"subject": subj, "body_one_paragraph": " ".join(body.split())}

    return client.generate_email(system=system, prompt=prompt, temperature=temperature, max_tokens=max_tokens)
