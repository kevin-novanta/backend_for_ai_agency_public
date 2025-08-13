def lookup_lead_id_by_email(email): return email
def get_followup_eligible_leads(client):
    return [
        {"Email":"demo1@example.com","Company Name":"Acme Co","Custom 2":"B2B ops platform"},
        {"Email":"demo2@example.com","Company Name":"Globex","Custom 2":"Logistics analytics"},
    ]
def update_fields(lead_id, fields): pass
def set_responded(lead_id, val): pass
def is_automatic_reply(text): return False
