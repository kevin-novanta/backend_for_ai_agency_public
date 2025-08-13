import json
import re
from openai import OpenAI

# Load your OpenAI API key from JSON file
with open("/Users/kevinnovanta/backend_for_ai_agency/Creds/gpt_key.json") as f:
    openai_key = json.load(f)["api_key"]

client = OpenAI(api_key=openai_key)

def remove_brackets_only(subject, body_html):
    subject_clean = re.sub(r"\[.*?\]", "", subject)
    body_clean = re.sub(r"\[.*?\]", "", body_html)
    return subject_clean, body_clean

def build_prompt(lead):
    company_name = lead.get("Company Name", "Unknown Company")
    industry_info = lead.get("Custom 2", "Unknown Industry")
    offer_summary = lead.get("Overview", "provide services")

    prompt = f"""
### Company Info:
- Name: {company_name}
- Industry: {industry_info}
- Offer Summary: {offer_summary}

### Your Task:
Write a short, warm cold outreach email (under 110 words) inviting the company to a quick discovery call (free workflow audit) where we identify bottlenecks and propose a tailored automation plan.

### Script Rules:
1. Do NOT re-explain what they do; show you understand their offer by referencing it naturally within the copy smoothly but specically and directly.
2. Make the time extremely friendly as if you're emailing someone you know.
3. Mention our company — Outbound Accelerator — as specialists in advanced AI workflows and ops automation.
4. I want you to Touch 1–2 pains relevant to their offer summary and include their offer along with the painpoints in the email. For example: Instead of saying "We understand the labor and time constraints businesses like you suffer from.." we mention thier offer and say "we help businesses in the construction niche save more by helping you (their goal and offer) by delivering (our services) to fix (x) problem:"{offer_summary.lower()}":
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
- 1–2 short paragraphs + a one‑line CTA
"""
    return prompt
# 📝 Follow-Up Email Template Prompt
follow_up_prompt_template = """
Write a friendly follow-up email to a lead who received our initial outreach but hasn't replied yet. The email should:

- Reference the previous message briefly (no pressure)
- Mention one new benefit or update (e.g., improved automation, new case study, faster onboarding)
- Invite them to a free 20–25 min discovery call to discuss tailored workflow solutions
- Keep it warm, concise, and specific to their business context

# Company Name:
{company_name}

# Industry / Category:
{industry_info}

# Business Summary / Pains:
{offer_summary}

# Requirements:
- 60–90 words
- End with a soft CTA ("open to a quick chat?")
- Mention Outbound Accelerator once.
"""

def generate_email(lead):
    """
    Sends a prompt to OpenAI and returns the subject and body_html.
    """
    prompt = build_prompt(lead)

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a B2B cold email generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        content = response.choices[0].message.content

        try:
            email = json.loads(content)
        except Exception:
            # Fallback plain text parsing
            lines = content.strip().splitlines()
            subject = ""
            body_lines = []
            for line in lines:
                if line.lower().startswith("subject:"):
                    subject = line[len("subject:"):].strip()
                else:
                    body_lines.append(line.strip())
            body_html = "<br>".join(body_lines).strip()
            email = {"subject": subject or "Follow up", "body_html": body_html or "Hi – just following up. Let me know if you're interested."}

        email["subject"], email["body_html"] = remove_brackets_only(email.get("subject", ""), email.get("body_html", ""))
        return email

    except Exception as e:
        print(f"❌ Error generating email: {e}")
        return {"subject": "Follow up", "body_html": "Hi – just following up. Let me know if you're interested."}

def generate_email_from_prompt(prompt, openai_key):
    """
    Sends a custom prompt to OpenAI and returns the subject and body_html.
    """
    local_client = OpenAI(api_key=openai_key)

    try:
        print(f"📨 Prompt being sent:\n{prompt}")
        response = local_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a B2B cold email generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        content = response.choices[0].message.content

        try:
            email = json.loads(content)
        except Exception:
            print(f"⚠️ Raw OpenAI response content:\n{content}")
            lines = content.strip().splitlines()
            subject = ""
            body_lines = []
            for line in lines:
                if line.lower().startswith("subject:"):
                    subject = line[len("subject:"):].strip()
                else:
                    body_lines.append(line.strip())
            body_html = "<br>".join(body_lines).strip()
            email = {"subject": subject or "Follow up", "body_html": body_html or content.strip()}

        email["subject"], email["body_html"] = remove_brackets_only(email.get("subject", ""), email.get("body_html", ""))
        return email

    except Exception as e:
        print(f"❌ Error generating email from prompt: {e}")
        return {"subject": "Follow up", "body_html": "Hi – just following up. Let me know if you're interested."}
