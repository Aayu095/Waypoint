"""Waypoint benchmark tasks.

Each task: a natural-language request, the entity it mentions (resolved via
resolve_entity), the input type the agent starts with, the goal type it must
produce, the ONE correct tool chain, the role allowed to run it, and the
trap that makes vector top-k fail (a lookalike tool whose words match but
whose typed chain does not reach the goal).

Ground truth is by construction: chains follow CONSUMES/PRODUCES types and
REQUIRES prerequisites in catalog.py.
"""

TASKS = [
    # --- payments chains
    {"id": "t01", "text": "Refund Sharma Traders for order 4821 and send them the receipt",
     "entity": "Sharma Traders", "start": "CustomerRef", "goal": "Receipt",
     "chain": ["find_charge", "issue_refund", "send_receipt"], "role": "support_agent",
     "trap": "receipt_template_* tools mention receipts but produce FileRef, never a Receipt; "
             "send_receipt itself is word-closest to the goal yet invalid until the refund exists."},
    {"id": "t02", "text": "Check whether the charge for Acme Corp was charged back",
     "entity": "Acme Corp", "start": "CustomerRef", "goal": "Chargeback",
     "chain": ["find_charge", "chargeback_lookup"], "role": "support_agent",
     "trap": "charge_report_* summarises a charge but produces Summary, not Chargeback."},
    {"id": "t03", "text": "Email Acme Corp's March invoice PDF to their finance contact",
     "entity": "Acme Corp", "start": "CompanyName", "goal": "SentMail",
     "chain": ["lookup_customer", "list_invoices", "get_invoice", "invoice_pdf", "find_contact", "send_email"],
     "role": "finance_agent",
     "trap": "email_campaign_* sends mail directly but cannot attach the invoice PDF; "
             "send_email_text matches 'email' yet consumes Summary, not the PDF."},
    {"id": "t04", "text": "Void the latest invoice for Sharma Traders",
     "entity": "Sharma Traders", "start": "CompanyName", "goal": "VoidedInvoice",
     "chain": ["lookup_customer", "list_invoices", "get_invoice", "void_invoice"],
     "role": "finance_admin",
     "trap": "void_invoice needs the payments:admin scope: a support_agent run must be REFUSED "
             "by permission-aware traversal even though the chain exists."},
    {"id": "t05", "text": "Create a customer for priya@example.com and find her charges",
     "entity": "Priya Sharma", "start": "EmailAddr", "goal": "Charge",
     "chain": ["create_customer", "find_charge"], "role": "support_agent",
     "trap": "lookup_customer matches 'customer' but starts from CompanyName, not an email."},
    # --- github chains
    {"id": "t06", "text": "Open a bug issue on the launch repo",
     "entity": "repo_launch", "start": "RepoName", "goal": "Issue",
     "chain": ["search_repo", "create_issue"], "role": "dev_agent",
     "trap": "open_pr matches 'open' but produces a PullRequest, not an Issue."},
    {"id": "t07", "text": "Merge the open pull request on the launch repo",
     "entity": "repo_launch", "start": "RepoName", "goal": "Merged",
     "chain": ["search_repo", "open_pr", "merge_pr"], "role": "dev_admin",
     "trap": "merge_pr needs github:admin; a dev_agent run must be refused at the scope checkpoint."},
    {"id": "t08", "text": "Invite the finance contact of Acme Corp to the launch repo",
     "entity": "Acme Corp", "start": "CompanyName", "goal": "Invited",
     "chain": ["lookup_customer", "find_contact", "search_repo", "invite_collaborator"],
     "role": "dev_admin",
     "trap": "invite needs an EmailAddr produced by a CRM chain AND a Repo from a github chain: "
             "two branches must join; single-path vector picks never assemble both."},
    # --- calendar / chat chains
    {"id": "t09", "text": "Schedule the eng team standup and announce it in the team chat",
     "entity": "eng_team", "start": "TeamName", "goal": "Message",
     "chain": ["find_team", "find_slot", "create_event", "post_message"], "role": "ops_agent",
     "trap": "notify_*_team posts a message but skips the calendar event the task requires first."},
    {"id": "t10", "text": "Cancel tomorrow's standup event for the eng team",
     "entity": "eng_team", "start": "TeamName", "goal": "Cancelled",
     "chain": ["find_team", "find_slot", "create_event", "cancel_event"], "role": "ops_agent",
     "trap": "cancel_event requires an Event produced by create_event in this graph model; "
             "word-matching alone cannot see that prerequisite."},
    # --- drive chains
    {"id": "t11", "text": "Find the March invoice file in Drive and share it with Acme's finance contact",
     "entity": "Acme Corp", "start": "CompanyName", "goal": "Shared",
     "chain": ["lookup_customer", "find_contact", "search_drive", "get_file", "share_file"],
     "role": "finance_agent",
     "trap": "share_file consumes FileRef AND EmailAddr from two different branches."},
    {"id": "t12", "text": "Summarize the onboarding doc from Drive",
     "entity": "hiring_q4", "start": "DocText", "goal": "Summary",
     "chain": ["search_drive", "summarize_doc"], "role": "ops_agent",
     "trap": "generate_*_summary tools produce Summary from raw DocText without the Drive file; "
             "they skip the file the task is about."},
    {"id": "t13", "text": "Sign the invoice PDF for Acme Corp",
     "entity": "Acme Corp", "start": "CompanyName", "goal": "SignedPdf",
     "chain": ["lookup_customer", "list_invoices", "get_invoice", "invoice_pdf", "sign_pdf"],
     "role": "finance_admin",
     "trap": "sign_pdf needs misc:admin scope; a finance_agent run must be refused."},
    # --- support chains
    {"id": "t14", "text": "Escalate ticket 881 to the senior support queue",
     "entity": "ticket_881", "start": "TicketRef", "goal": "Escalated",
     "chain": ["get_ticket", "escalate_ticket"], "role": "support_agent",
     "trap": "close_ticket matches 'ticket' strongly but produces Closed, the opposite outcome."},
    {"id": "t15", "text": "Close ticket 881 after resolution",
     "entity": "ticket_881", "start": "TicketRef", "goal": "Closed",
     "chain": ["get_ticket", "close_ticket"], "role": "support_agent",
     "trap": "escalate_ticket is the near-twin; only the goal type separates them."},
    # --- hr chains
    {"id": "t16", "text": "Onboard Priya Sharma: create her employee record and assign a laptop",
     "entity": "Priya Sharma", "start": "EmailAddr", "goal": "LaptopAssigned",
     "chain": ["create_employee", "assign_laptop"], "role": "hr_agent",
     "trap": "book_onboarding matches 'onboard' but produces Onboarding, not the laptop assignment."},
    {"id": "t17", "text": "Book the onboarding session for Priya Sharma",
     "entity": "Priya Sharma", "start": "EmailAddr", "goal": "Onboarding",
     "chain": ["create_employee", "book_onboarding"], "role": "hr_agent",
     "trap": "assign_laptop is the near-twin distractor for the same first step."},
    # --- crm chains
    {"id": "t18", "text": "Update the Acme Corp deal after the pricing call",
     "entity": "Acme Corp", "start": "CompanyName", "goal": "DealUpdated",
     "chain": ["find_deal", "update_deal"], "role": "sales_agent",
     "trap": "update_*_settings tools match 'update' but act on settings, not the Deal type."},
    # --- mail chains
    {"id": "t19", "text": "Find the thread about the Acme invoice and archive it",
     "entity": "Acme Corp", "start": "DocText", "goal": "Archived",
     "chain": ["search_mail", "archive_thread"], "role": "ops_agent",
     "trap": "archive_*_items matches 'archive' but consumes FileRef, not the mail list."},
    {"id": "t20", "text": "Email the summary of the onboarding doc to Priya Sharma",
     "entity": "Priya Sharma", "start": "DocText", "goal": "SentMail",
     "chain": ["search_drive", "summarize_doc", "send_email_text"], "role": "hr_agent",
     "trap": "send_email (PDF variant) is word-closer to 'email' but consumes InvoicePdf; "
             "the summary chain needs the text variant."},
]

# Roles and the scopes each role holds. REQUIRES_SCOPE edges in the graph use
# these same scope strings; traversal for a role may only pass checkpoints
# whose scope the role holds.
ROLES = {
    "support_agent": ["payments:read", "payments:write", "crm:read", "support:read", "support:write"],
    "finance_agent": ["payments:read", "crm:read", "mail:write", "drive:read", "drive:write"],
    "finance_admin": ["payments:read", "payments:admin", "crm:read", "mail:write", "drive:read", "misc:admin"],
    "dev_agent":     ["github:read", "github:write"],
    "dev_admin":     ["github:read", "github:write", "github:admin", "crm:read"],
    "ops_agent":     ["calendar:read", "calendar:write", "chat:read", "chat:write", "mail:read", "mail:write", "drive:read"],
    "hr_agent":      ["hr:write", "mail:write", "drive:read"],
    "sales_agent":   ["crm:read", "crm:write"],
    # Phase 7: roles for INGESTED real MCP catalogs (examples/real-mcp).
    # fs_reader deliberately lacks fs:write — the refusal case on real tools.
    "fs_agent":      ["fs:read", "fs:write"],
    "fs_reader":     ["fs:read"],
    "memory_agent":  ["memory:read", "memory:write"],
}

# Entities the agent may already have resolved (resolve_entity skips lookups).
ENTITIES = {
    "Sharma Traders": {"id": 301, "kind": "company", "ref": "CustomerRef"},
    "Acme Corp":      {"id": 302, "kind": "company", "ref": "CustomerRef"},
    "Priya Sharma":   {"id": 303, "kind": "person",  "ref": "EmailAddr"},
    "eng_team":       {"id": 306, "kind": "team",    "ref": "TeamRef"},
    "repo_launch":    {"id": 308, "kind": "repo",    "ref": "RepoName"},
    "ticket_881":     {"id": 309, "kind": "ticket",  "ref": "TicketRef"},
    "hiring_q4":      {"id": 311, "kind": "program", "ref": "DocText"},
}

if __name__ == "__main__":
    print(f"tasks={len(TASKS)} roles={len(ROLES)} entities={len(ENTITIES)}")
    refused = [t["id"] for t in TASKS if "REFUSED" in t["trap"] or "refused" in t["trap"]]
    print(f"permission-refusal tasks: {refused}")
