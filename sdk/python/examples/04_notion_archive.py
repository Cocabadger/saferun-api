"""Archive a Notion page."""
from saferun import SafeRunClient

client = SafeRunClient(api_key="YOUR_API_KEY")
result = client.archive_notion_page(
    page_id="NOTION_PAGE_ID",
    notion_token="NOTION_TOKEN",
)
print("Change ID:", result.change_id)
print("Needs approval:", result.needs_approval)
