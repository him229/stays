"""ChatGPT MCP setup — instructions only.

ChatGPT (Desktop + web) supports ONLY remote HTTPS MCP endpoints that
implement OAuth 2.1 + Dynamic Client Registration (RFC 7591). Local
stdio servers cannot be registered, and there is no local config file
to edit. This module emits copy-pasteable instructions + a deep-link
into the ChatGPT Connectors settings page.

Confirmed 2025-12 against:
- https://developers.openai.com/apps-sdk/deploy/connect-chatgpt
- https://help.openai.com/en/articles/11487775-connectors-in-chatgpt
- https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Settings URL — use the stable settings root rather than a fragment that
# OpenAI has renamed in the past ("Connectors" -> "Apps & Connectors" -> "Apps").
# Users navigate to Settings -> Apps & Connectors themselves.
SETTINGS_URL = "https://chatgpt.com/#settings"


@dataclass
class ChatGPTInstructions:
    settings_url: str = SETTINGS_URL
    messages: list[str] = field(default_factory=list)


def build() -> ChatGPTInstructions:
    out = ChatGPTInstructions()
    out.messages = [
        "ChatGPT requires a *public HTTPS* MCP endpoint implementing OAuth 2.1 +",
        "Dynamic Client Registration (RFC 7591). The local `stays mcp-http`",
        "server (plain HTTP on 127.0.0.1) CANNOT be registered with ChatGPT",
        "directly.",
        "",
        "To set up a ChatGPT connector for `stays`:",
        "",
        "  1. Expose `stays mcp-http` over public HTTPS. Easiest options:",
        "        a) cloudflared tunnel:",
        "              cloudflared tunnel --url http://127.0.0.1:8000",
        "        b) ngrok:",
        "              ngrok http 8000",
        "     Note: `stays mcp-http` does NOT currently implement OAuth 2.1 +",
        "     DCR. A production-safe ChatGPT connector would need that layer",
        "     added in front of the tunnel. Out of scope for v0.1.",
        "",
        "  2. Ensure you are on a paid ChatGPT plan that includes Developer",
        "     Mode (as of Dec 2025: Plus, Pro, Business, Enterprise, or Edu;",
        "     workspace plans may require an admin to enable it for Teams /",
        "     Enterprise). Then toggle Developer Mode ON:",
        "        Settings → Apps & Connectors → Advanced → Developer Mode.",
        "",
        "  3. Still in that panel, click 'Create' → paste the public HTTPS URL",
        "     (https://<your-tunnel>/mcp) + a name and description.",
        "",
        f"     Settings root: {SETTINGS_URL}",
        "     (Navigate to 'Apps & Connectors' from there — the exact",
        "     tab label has changed more than once and may differ.)",
        "",
        "  4. Complete the OAuth enrollment flow when prompted.",
    ]
    return out
