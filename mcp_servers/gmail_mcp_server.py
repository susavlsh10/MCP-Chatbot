import asyncio
import json
import os
from typing import Any, Sequence
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

class GmailMCPServer:
    def __init__(self):
        self.gmail_service = None
        
    async def authenticate_gmail(self):
        """Authenticate with Gmail API"""
        creds = None
        token_file = os.getenv('GMAIL_TOKEN_FILE', 'token.json')
        credentials_file = os.getenv('GMAIL_CREDENTIALS_FILE', 'credentials.json')
        
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
                # creds = flow.run_local_server(port=8080, open_browser=False)
                # print("If browser didn't open automatically, copy this URL to your browser:")
            
            with open(token_file, 'w') as token:
                token.write(creds.to_json())
                
        self.gmail_service = build('gmail', 'v1', credentials=creds)
    
    def create_message(self, to: str, subject: str, body: str, from_email: str = None):
        """Create a message for an email"""
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
        if from_email:
            message['from'] = from_email
            
        message.attach(MIMEText(body, 'plain'))
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {'raw': raw_message}
    
    async def send_email(self, to: str, subject: str, body: str) -> str:
        """Send an email via Gmail"""
        try:
            if not self.gmail_service:
                print("DEBUG: Authenticating with Gmail...")
                await self.authenticate_gmail()
                print("DEBUG: Gmail authentication complete")
                
            message = self.create_message(to, subject, body)
            sent_message = self.gmail_service.users().messages().send(
                userId='me', body=message
            ).execute()
            
            return f"Email sent successfully! Message ID: {sent_message['id']}"
        except Exception as e:
            return f"Failed to send email: {str(e)}"

async def main():
    server = Server("gmail-mcp-server")
    gmail_server = GmailMCPServer()
    
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="send_email",
                description="Send an email via Gmail",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address"
                        },
                        "subject": {
                            "type": "string", 
                            "description": "Email subject line"
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body content"
                        }
                    },
                    "required": ["to", "subject", "body"]
                }
            )
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
        print(f"DEBUG: Gmail server received tool call: {name} with args: {arguments}")
        if name == "send_email":
            result = await gmail_server.send_email(
                to=arguments["to"],
                subject=arguments["subject"], 
                body=arguments["body"]
            )
            return [TextContent(type="text", text=result)]
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())