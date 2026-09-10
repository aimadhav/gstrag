"""Discover official CBIC notification links; ingestion is delegated to the shared pipeline."""
import re
import sys
import httpx

CBIC_URL = "https://taxinformation.cbic.gov.in/"

def find_notification_links(html: str, base: str = CBIC_URL) -> list[str]:
    links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
    return [x if x.startswith("http") else base.rstrip("/") + "/" + x.lstrip("/") for x in links if "notif" in x.lower() or x.lower().endswith(".pdf")]

def check_notifications() -> list[str]:
    response = httpx.get(CBIC_URL, timeout=20, follow_redirects=True)
    response.raise_for_status()
    return find_notification_links(response.text)

if __name__ == "__main__":
    print("\n".join(check_notifications()))
