"""Waypoint tool catalog.

Two layers:
1. CORE tools (~44) hand-designed so benchmark tasks have known correct chains
   linked by typed CONSUMES/PRODUCES edges (plus REQUIRES prerequisites and
   REQUIRES_SCOPE permission edges).
2. DISTRACTOR tools (~260) generated programmatically to reach ~300 tools.
   They share the same type vocabulary and similar wording on purpose:
   vector top-k retrieval should confuse them with core tools, while the
   graph traversal follows exact typed chains.

Token cost per tool = a realistic tool-definition size (name + description +
JSON schema), estimated at len(desc)*1 + schema boilerplate. We compute it
deterministically from the description so preload cost is reproducible.
"""

import json
import random

# ---------------------------------------------------------------- core tools
# key, server, consumes, produces, scopes, requires (prerequisite tool keys)
CORE = [
    # payments / stripe-like
    ("find_charge",        "payments", ["CustomerRef"], ["Charge"],      ["payments:read"],  []),
    ("issue_refund",       "payments", ["Charge"],      ["Refund"],      ["payments:write"], ["find_charge"]),
    ("send_receipt",       "payments", ["Refund"],      ["Receipt"],     ["payments:write"], ["issue_refund"]),
    ("chargeback_lookup",  "payments", ["Charge"],      ["Chargeback"],  ["payments:read"],  ["find_charge"]),
    ("create_customer",    "payments", ["EmailAddr"],   ["CustomerRef"], ["payments:write"], []),
    ("list_invoices",      "payments", ["CustomerRef"], ["InvoiceList"], ["payments:read"],  []),
    ("get_invoice",        "payments", ["InvoiceList"], ["Invoice"],     ["payments:read"],  ["list_invoices"]),
    ("invoice_pdf",        "payments", ["Invoice"],     ["InvoicePdf"],  ["payments:read"],  ["get_invoice"]),
    ("void_invoice",       "payments", ["Invoice"],     ["VoidedInvoice"], ["payments:admin"], ["get_invoice"]),
    # crm
    ("lookup_customer",    "crm",      ["CompanyName"], ["CustomerRef"], ["crm:read"], []),
    ("find_contact",       "crm",      ["CustomerRef"], ["EmailAddr"],   ["crm:read"], ["lookup_customer"]),
    ("find_deal",          "crm",      ["CompanyName"], ["Deal"],        ["crm:read"], []),
    ("update_deal",        "crm",      ["Deal"],        ["DealUpdated"], ["crm:write"], ["find_deal"]),
    # mail
    ("send_email",         "mail",     ["EmailAddr", "InvoicePdf"], ["SentMail"], ["mail:write"], []),
    ("send_email_text",    "mail",     ["EmailAddr", "Summary"],    ["SentMail"], ["mail:write"], []),
    ("search_mail",        "mail",     ["DocText"],     ["MailList"],    ["mail:read"], []),
    ("archive_thread",     "mail",     ["MailList"],    ["Archived"],    ["mail:write"], ["search_mail"]),
    # drive / docs
    ("search_drive",       "drive",    ["DocText"],     ["FileRef"],     ["drive:read"], []),
    ("get_file",           "drive",    ["FileRef"],     ["InvoicePdf"],  ["drive:read"], ["search_drive"]),
    ("share_file",         "drive",    ["FileRef", "EmailAddr"], ["Shared"], ["drive:write"], ["get_file"]),
    ("summarize_doc",      "drive",    ["FileRef"],     ["Summary"],     ["drive:read"], ["search_drive"]),
    # github
    ("search_repo",        "github",   ["RepoName"],    ["Repo"],        ["github:read"], []),
    ("create_issue",       "github",   ["Repo"],        ["Issue"],       ["github:write"], ["search_repo"]),
    ("open_pr",            "github",   ["Repo"],        ["PullRequest"], ["github:write"], ["search_repo"]),
    ("merge_pr",           "github",   ["PullRequest"], ["Merged"],      ["github:admin"], ["open_pr"]),
    ("invite_collaborator","github",   ["Repo", "EmailAddr"], ["Invited"], ["github:admin"], ["search_repo"]),
    # calendar
    ("find_slot",          "calendar", ["TeamRef"],     ["Slot"],        ["calendar:read"], []),
    ("create_event",       "calendar", ["Slot"],        ["Event"],       ["calendar:write"], ["find_slot"]),
    ("cancel_event",       "calendar", ["Event"],       ["Cancelled"],   ["calendar:write"], ["create_event"]),
    # slack-like chat
    ("find_team",          "chat",     ["TeamName"],    ["TeamRef"],     ["chat:read"], []),
    ("post_message",       "chat",     ["TeamRef", "Event"], ["Message"], ["chat:write"], ["find_team"]),
    ("create_channel",     "chat",     ["TeamRef"],     ["Channel"],     ["chat:write"], ["find_team"]),
    # support
    ("get_ticket",         "support",  ["TicketRef"],   ["Ticket"],      ["support:read"], []),
    ("escalate_ticket",    "support",  ["Ticket"],      ["Escalated"],   ["support:write"], ["get_ticket"]),
    ("close_ticket",       "support",  ["Ticket"],      ["Closed"],      ["support:write"], ["get_ticket"]),
    # hr
    ("create_employee",    "hr",       ["EmailAddr"],   ["Employee"],    ["hr:write"], []),
    ("assign_laptop",      "hr",       ["Employee"],    ["LaptopAssigned"], ["hr:write"], ["create_employee"]),
    ("book_onboarding",    "hr",       ["Employee"],    ["Onboarding"],  ["hr:write"], ["create_employee"]),
    # misc
    ("translate_text",     "misc",     ["DocText"],     ["Translated"],  ["misc:write"], []),
    ("ocr_scan",           "misc",     ["FileRef"],     ["DocText"],     ["misc:read"], []),
    ("sign_pdf",           "misc",     ["InvoicePdf"],  ["SignedPdf"],   ["misc:admin"], []),
]

DESCRIPTIONS = {
    "find_charge": "Find a payment charge for a customer so a refund or dispute can reference it.",
    "issue_refund": "Issue a refund against an existing charge. Refund only; does not notify the customer.",
    "send_receipt": "Send the customer a receipt for a completed refund transaction.",
    "lookup_customer": "Look up a customer record in the CRM from a company name to get its customer reference.",
    "get_invoice": "Fetch a single invoice record from a customer's invoice list.",
    "invoice_pdf": "Render an invoice record as a PDF document.",
    "send_email": "Send an email with a PDF attachment to an email address.",
    "find_contact": "Find the finance contact email address for a CRM customer.",
}

GENERIC_DESC = "Tool {key} on the {server} server. Consumes {consumes} and produces {produces}."

# ------------------------------------------------------- distractor templates
DISTRACTOR_PATTERNS = [
    ("export_{x}_report", ["DocText"], ["FileRef"]),
    ("sync_{x}_records", ["CustomerRef"], ["Synced"]),
    ("audit_{x}_log", ["DocText"], ["Summary"]),
    ("backup_{x}_data", ["FileRef"], ["Backup"]),
    ("schedule_{x}_job", ["DocText"], ["Scheduled"]),
    ("validate_{x}_entry", ["DocText"], ["Validated"]),
    ("convert_{x}_format", ["FileRef"], ["Converted"]),
    ("notify_{x}_team", ["TeamRef"], ["Message"]),
    ("archive_{x}_items", ["FileRef"], ["Archived"]),
    ("generate_{x}_summary", ["DocText"], ["Summary"]),
    ("check_{x}_status", ["DocText"], ["Status"]),
    ("update_{x}_settings", ["DocText"], ["Updated"]),
    ("fetch_{x}_metrics", ["DocText"], ["Metrics"]),
    ("clean_{x}_duplicates", ["DocText"], ["Cleaned"]),
    ("import_{x}_file", ["FileRef"], ["Imported"]),
    ("tag_{x}_record", ["DocText"], ["Tagged"]),
    ("search_{x}_archive", ["DocText"], ["FileRef"]),
    ("rotate_{x}_keys", ["DocText"], ["Rotated"]),
    ("monitor_{x}_queue", ["DocText"], ["Metrics"]),
    ("purge_{x}_cache", ["DocText"], ["Purged"]),
    ("refund_status_{x}", ["Charge"], ["Status"]),          # lookalike: mentions refund, wrong job
    ("receipt_template_{x}", ["DocText"], ["FileRef"]),      # lookalike: mentions receipt, wrong job
    ("invoice_reminder_{x}", ["Invoice"], ["Message"]),      # lookalike: near send_email chain
    ("charge_report_{x}", ["Charge"], ["Summary"]),          # lookalike: near find_charge chain
    ("contact_export_{x}", ["CustomerRef"], ["FileRef"]),    # lookalike: near find_contact chain
    ("email_campaign_{x}", ["EmailAddr"], ["SentMail"]),     # lookalike: sends mail, wrong semantics
]

DISTRACTOR_SUBJECTS = [
    "billing", "sales", "vendor", "partner", "legacy", "mobile", "web",
    "internal", "regional", "trial", "enterprise", "retail",
]

SERVERS = ["payments", "crm", "mail", "drive", "github", "calendar",
           "chat", "support", "hr", "misc", "analytics", "ops"]


def est_tokens(desc: str) -> int:
    """Deterministic tool-definition token estimate: description words plus
    a fixed JSON-schema boilerplate per tool."""
    return 60 + len(desc.split()) * 2


def build_catalog() -> list[dict]:
    tools = []
    for i, (key, server, consumes, produces, scopes, requires) in enumerate(CORE):
        desc = DESCRIPTIONS.get(key) or GENERIC_DESC.format(
            key=key, server=server, consumes=", ".join(consumes), produces=", ".join(produces))
        tools.append({
            "id": 100 + i, "key": key, "server": server,
            "consumes": consumes, "produces": produces,
            "scopes": scopes, "requires": requires,
            "desc": desc, "tokens": est_tokens(desc), "core": True,
        })
    rng = random.Random(42)
    n = 0
    next_id = 200
    for server in SERVERS:
        for subj in DISTRACTOR_SUBJECTS:
            for pat, consumes, produces in rng.sample(DISTRACTOR_PATTERNS, 2):
                key = pat.format(x=f"{subj}_{server}")
                desc = GENERIC_DESC.format(key=key, server=server,
                                           consumes=", ".join(consumes),
                                           produces=", ".join(produces))
                tools.append({
                    "id": next_id, "key": key, "server": server,
                    "consumes": consumes, "produces": produces,
                    "scopes": [f"{server}:read"], "requires": [],
                    "desc": desc, "tokens": est_tokens(desc), "core": False,
                })
                next_id += 1
                n += 1
    return tools


if __name__ == "__main__":
    tools = build_catalog()
    core = [t for t in tools if t["core"]]
    print(f"total={len(tools)} core={len(core)} distractors={len(tools) - len(core)}")
    print(f"preload_tokens_all={sum(t['tokens'] for t in tools)}")
    with open("../data/tools.json", "w") as f:
        json.dump(tools, f, indent=1)
    print("wrote data/tools.json")
