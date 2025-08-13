class StateStore:
    def __init__(self, client="Demo"): self.sent=set()
    def was_sent(self, lead_id, seq_id, step_id, idempotency_key): return (lead_id,seq_id,step_id,idempotency_key) in self.sent
    def mark_sent(self, lead_id, seq_id, step_id, idempotency_key): self.sent.add((lead_id,seq_id,step_id,idempotency_key))
    def is_stopped(self, lead_id): return False
    def mark_replied(self, lead_id): pass
