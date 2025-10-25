# MCP Chatbot Project

A Model Context Protocol (MCP) chatbot that integrates with multiple services including Gmail, Google Calendar, PDF processing, web search, and pizza ordering.

## Installation

### Prerequisites
- Python 3.10+
- [uv package manager](https://github.com/astral-sh/uv)

### Setup Environment
```bash
# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate
```

## Google API Credentials Setup

### 1. Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Gmail API and Google Calendar API

### 2. Create OAuth 2.0 Credentials
1. Go to **Credentials** > **Create Credentials** > **OAuth 2.0 Client ID**
2. Set application type to **Desktop Application**
3. Download the JSON file and save as:
   ```
   gmail/client_secret_[YOUR_CLIENT_ID].apps.googleusercontent.com.json
   ```

### 3. Update Configuration
Update `server_config.json` with your credential file name:
```json
"GMAIL_CREDENTIALS_FILE": "gmail/client_secret_[YOUR_CLIENT_ID].apps.googleusercontent.com.json"
```

### 4. Environment Variables
Create `.env` file with your API keys:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

## Running the Chatbot

```bash
uv run mcp_chatbot.py
```

### First Run Authentication
- Gmail and Calendar servers will open browser for OAuth consent
- Tokens will be saved to `gmail/gmail_token.json` and `gmail/token.json`
- Subsequent runs will use saved tokens

## Available Commands

| Command | Description |
|---------|-------------|
| `clear` | Clear conversation history |
| `quit`  | Exit the chatbot |

## MCP Servers

The chatbot connects to 5 specialized servers:

1. **Gmail** - Send and manage emails
2. **Google Calendar** - Schedule meetings and events  
3. **PDF Processor** - Read and answer questions about PDFs
4. **Gemini Search** - Real-time web search
5. **Dominos** - Order pizza

## Development

### Inspect MCP Servers
```bash
npx @modelcontextprotocol/inspector uv run mcp_servers/google_calendar_server.py
```

### Pizza Server

To avoid leaking sensitive information to APIs, use the script register_user.py to add private information like address and payment information. 

### Add New Servers
1. Create server in `mcp_servers/` directory
2. Add configuration to `server_config.json`
3. Restart chatbot to load new tools

## Troubleshooting

- **Authentication errors**: Delete token files and re-authenticate
- **Server connection issues**: Check `mcp_chatbot.log` for details
- **Missing dependencies**: Run `uv sync --upgrade`