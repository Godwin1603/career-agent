from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send"
]

CLIENT_SECRET_FILE = Path("secrets/gmail-client.json")

flow = InstalledAppFlow.from_client_secrets_file(
    CLIENT_SECRET_FILE,
    SCOPES,
)

credentials = flow.run_local_server(port=0)

print("\n========== SAVE THESE ==========\n")

print("CLIENT_ID:")
print(credentials.client_id)

print("\nCLIENT_SECRET:")
print(credentials.client_secret)

print("\nREFRESH_TOKEN:")
print(credentials.refresh_token)

print("\nTOKEN_URI:")
print(credentials.token_uri)