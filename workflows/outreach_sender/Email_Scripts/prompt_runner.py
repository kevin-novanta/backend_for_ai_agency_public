import argparse
import sys
import os
import json
from pathlib import Path
import re
import importlib.util

# Add project root to sys.path for running as a script (absolute imports)
sys.path.append(str(Path(__file__).resolve().parents[2]))

from workflows.outreach_sender.AI_Intergrations.opener_ai_writer import generate_email_from_prompt
from workflows.outreach_sender.Utils.opener_utils import sanitize_email_fields

def remove_brackets(text: str) -> str:
    if not isinstance(text, str):
        return ""
    # Remove all content within [ and ], including the brackets, but preserve whitespace and formatting outside
    return re.sub(r"\[.*?\]", "", text, flags=re.DOTALL)

def load_openai_key():
    creds_path = "/Users/kevinnovanta/backend_for_ai_agency/Creds/gpt_key.json"
    with open(creds_path, "r") as file:
        creds = json.load(file)
    return creds["api_key"]

def run_prompt_test(company_name, industry_info, offer_summary):
    print("📝 Company Name:", company_name)
    print("🏭 Industry Info:", industry_info)
    print("📦 Offer Summary:", offer_summary)

    prompt = f"""
### Company Info:
- Name: {company_name}
- Industry: {industry_info}
- Offer Summary: {offer_summary}

### Your Task:
Write a short, warm cold outreach email (under 110 words) inviting the company to a quick discovery call (free workflow audit) where we identify bottlenecks and propose a tailored automation plan.

### Script Rules:
1. Do NOT re-explain what they do; show you understand their offer by referencing it naturally.
2. Make sure to line break after each sentence or comma for readability, and keep a space in between paragraps
3. Mention our company — Outbound Accelerator — as specialists in advanced AI workflows and ops automation.
4. Touch 1–2 pains relevant to their offer summary:"{offer_summary.lower()}":
   1. Economic & Regulatory Uncertainty

Nearly 60% of small business owners cite economic unpredictability—driven by shifting trade policies, tariffs, inflation, and tax changes—as their biggest concern. This instability paralyzes strategic planning.
￼

2. Cash Flow & Financing Constraints

Access to affordable capital remains tough. Owners struggle with managing working capital amid rising costs and interest rates.
￼ ￼

3. Being Bogged Down in Operations

SMB leaders are trapped in daily operations, unable to focus on strategic growth—the dreaded “working in” rather than “on” the business.
￼

4. Low Productivity & Accountability

A lack of accountability and clear productivity tracking leads to inefficiencies. Workflow owners are looking for clarity and structure.
￼

5. People & Talent Challenges

Issues like staff turnover, poor role clarity, and weak performance feedback create friction and slow business momentum.
￼

6. Customer Support Bottlenecks

Slow response times, repeated explanations, and poor ticket tracking frustrate clients and lead to dissatisfaction.
￼

7. Cybersecurity Complexity

Many businesses now juggle over 20 security tools—causing fragmentation, slower responses, and costing agility. MSPs and automation can simplify these setups.
￼

8. Manual, Repetitive Workflow Overload

Routine tasks like invoicing, onboarding, and reporting consume too much time—automation offers a clear path out.
￼

9. Technology Adoption & Scaling Gaps

While 77% of small businesses plan to adopt emerging tech like AI, many lack the tools or expertise to implement it effectively.
￼

10. Unpredictable Regulatory Changes & Compliance Pain

From minimum wage hikes to new payments reporting (e.g., 1099-K thresholds) and transparency regulations, staying compliant is a hassle.
5. Mention 1–2 practical outcomes:
   1.	Massive Time Savings – Owners reclaim hours each week by automating repetitive, low-value tasks like lead gen, onboarding, invoicing, and reporting.
	2.	Lower Operating Costs – Fewer manual hours, reduced payroll for admin roles, and elimination of redundant software subscriptions.
	3.	Higher Lead Volume – Consistent, automated client acquisition systems filling the pipeline without cold-calling or manual prospecting.
	4.	Improved Lead Quality – Pre-qualified prospects through automated filters, reducing wasted calls and sales effort.
	5.	Faster Sales Cycles – Automated follow-ups and nurturing sequences that move leads from awareness to closed deals in less time.
	6.	Consistent Client Onboarding – No missed steps, faster “time to value,” and smoother client experience right from the start.
	7.	Better Client Retention – Automated check-ins, milestone tracking, and ongoing value delivery keep clients engaged longer.
	8.	Real-Time Visibility & Control – Dashboards showing KPIs, campaign performance, and bottlenecks so owners can make quick decisions.
	9.	Increased Revenue & Profit Margins – More clients at lower acquisition cost, with higher LTV (lifetime value) per client.
	10.	Scalability Without Hiring Spree – Growth supported by systems, not by constantly adding more team members.
	11.	Reduced Human Error – Standardized workflows minimize mistakes that come from manual processes.
	12.	Enhanced Brand Perception – Faster responses, smoother processes, and professional automation make the business look bigger and more credible.
	13.	Easier Compliance & Risk Management – Automated alerts and documentation for regulations and industry requirements.
	14.	Operational Consistency – Every client, lead, and task handled the same way, no matter who’s on the team.
	15.	Peace of Mind – Owners can focus on high-level strategy knowing the “machine” runs without them micromanaging daily operations.
6. Clear CTA: invite them to a 25-30 min discovery call (free) to create a custom workflow plan and breakdown based on the form they'll submit to me pre call via google forms that'll be a short questionare.
7. Keep tone human, specific, concise. No hype, no emojis, no square brackets.
8. Final sentence must include our company name: Outbound Accelerator. 
9. Do not place any custom placeholders or brackets in the email.

### Output Format:
- Casual, friendly, human
"""

    print("🧪 Prompt being sent to OpenAI:\n", prompt)

    print("\n🔄 Generating response from OpenAI...\n")
    openai_key = load_openai_key()
    print("🔑 OpenAI Key loaded successfully.")
    email = generate_email_from_prompt(prompt, openai_key)

    def strip_html_tags(text: str) -> str:
        # Remove all HTML tags except <br> which will be replaced by newlines before calling this function
        return re.sub(r"<[^>]+>", "", text)

    # Process AI output to get raw text without HTML formatting, then remove brackets
    if isinstance(email, dict):
        raw_text = ""
        if email.get("body_text"):
            raw_text = email["body_text"]
        elif email.get("body_html"):
            # Replace <br> and variants with newlines
            body_html = re.sub(r"(?i)<br\s*/?>", "\n", email["body_html"])
            # Strip other HTML tags
            raw_text = strip_html_tags(body_html)
        else:
            raw_text = ""
        cleaned_email = remove_brackets(raw_text)
    else:
        cleaned_email = remove_brackets(str(email))

    print("✅ Email generation completed.")

    print("📧 Generated Email:\n")
    print(cleaned_email)

    print("\n✉️ Plaintext Output (sanitized):\n")
    print(cleaned_email)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the outreach email prompt generator.")
    parser.add_argument("--company_name", type=str, default="Purposeful Agency",
                        help="The name of the company.")
    parser.add_argument("--industry_info", type=str, default="Purposeful Agency is an agency specializing in online learning and video production. For outstanding work in Miami Call: 415 408 8549.",
                        help="Information about the company's industry.")
    parser.add_argument("--offer_summary", type=str, default="Purposeful Agency is an agency specializing in online learning and video production. For outstanding work in Miami Call: 415 408 8549.",
                        help="A summary of the company's offer.")
    args = parser.parse_args()
    run_prompt_test(args.company_name, args.industry_info, args.offer_summary)