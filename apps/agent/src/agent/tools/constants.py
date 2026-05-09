"""Shared constants for Conduut agent tools."""

_AUTH_TO_CREDENTIAL_TYPE = {
    "basicauth": "httpBasicAuth",
    "headerauth": "httpHeaderAuth",
    "jwtauth": "jwtAuth",
}

_OPTIONAL_CREDENTIAL_NODE_TYPES = {
    "n8n-nodes-base.respondToWebhook",
}

_MANUAL_TRIGGER_TYPE = "n8n-nodes-base.manualTrigger"
_WEBHOOK_TRIGGER_TYPE = "n8n-nodes-base.webhook"
_GOOGLE_GMAIL_CONNECTION_ID = "google_gmail"
_GOOGLE_GMAIL_CREDENTIAL_TYPE = "gmailOAuth2"
_GOOGLE_SHEETS_CONNECTION_ID = "google_sheets"
_GOOGLE_SHEETS_CREDENTIAL_TYPE = "googleSheetsOAuth2Api"
_GMAIL_MANAGED_OPERATIONS = {
    "label": {"get", "getall"},
    "message": {"create", "get", "getall", "reply", "send"},
    "thread": {"get", "getall", "reply"},
}
