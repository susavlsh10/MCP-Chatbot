from dotenv import load_dotenv
from anthropic import Anthropic

from google import genai
from google.genai import types as genai_types

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from typing import List, Dict, TypedDict
from contextlib import AsyncExitStack
import json
import asyncio
import logging
from datetime import datetime

load_dotenv()

# Set up logging for tool calls
logging.basicConfig(
    filename='mcp_chatbot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)

def clean_schema(schema): # Cleans the schema by keeping only allowed keys
    allowed_keys = {"type", "properties", "required", "description", "title", "default", "enum"}
    return {k: v for k, v in schema.items() if k in allowed_keys}

class ToolDefinition(TypedDict):
    name: str
    description: str
    input_schema: dict

class MCP_ChatBot:

    def __init__(self):
        # Initialize session and client objects
        self.sessions: List[ClientSession] = [] # new
        self.exit_stack = AsyncExitStack() # new
        # self.anthropic = Anthropic()
        self.gemini_client = genai.Client()
        self.gemini_tools = None
        self.model_name = "gemini-2.5-flash"
        self.available_tools: List[ToolDefinition] = [] # new
        self.tool_to_session: Dict[str, ClientSession] = {} # new
        self.google_search_tool = genai_types.Tool(google_search=genai_types.GoogleSearch())
        # Add persistent conversation history
        self.conversation_history: List[genai_types.Content] = []

    async def connect_to_server(self, server_name: str, server_config: dict) -> None:
        """Connect to a single MCP server."""
        try:
            server_params = StdioServerParameters(**server_config)
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            ) # new
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            ) # new
            await session.initialize()
            self.sessions.append(session)
            
            # List available tools for this session
            response = await session.list_tools()
            tools = response.tools
            print(f"\nConnected to {server_name} with tools:", [t.name for t in tools])
            logging.info(f"Connected to {server_name} with {len(tools)} tools: {[t.name for t in tools]}")
            
            for tool in tools: # new
                self.tool_to_session[tool.name] = session
                self.available_tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                })
        except Exception as e:
            print(f"Failed to connect to {server_name}: {e}")

    async def connect_to_servers(self): # new
        """Connect to all configured MCP servers."""
        try:
            with open("server_config.json", "r") as file:
                data = json.load(file)
            
            servers = data.get("mcpServers", {})
            
            for server_name, server_config in servers.items():
                await self.connect_to_server(server_name, server_config)
        except Exception as e:
            print(f"Error loading server configuration: {e}")
            raise
    

    async def process_query_gemini(self, prompt: str) -> str:
        # Only add date context for the first message
        if not self.conversation_history:
            today_date = datetime.now().strftime("%Y-%m-%d")
            overall_prompt = f"Today's date is {today_date}. You are a helpful personal assistant. If you are uncertain, ask for clarification from the user. If you do not know the answer and it can be found online, consider searching for the information online using the tools available. \n\n{prompt}"
            user_content = genai_types.Content(role="user", parts=[genai_types.Part(text=overall_prompt)])
        else:
            user_content = genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)])
        
        # Add user message to conversation history
        self.conversation_history.append(user_content)
        
        # Use the full conversation history for context
        contents = self.conversation_history.copy()

        if not self.gemini_tools:
            mcp_tools = self.available_tools
            tools = genai_types.Tool(function_declarations=[
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": clean_schema(tool.get("input_schema", {}))
                }
                for tool in mcp_tools
            ])
            self.gemini_tools = tools

        else:
            tools = self.gemini_tools

        response = await self.gemini_client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                temperature=0,
                tools=[tools],
            ),
        )
        
        # Add assistant response to history immediately
        self.conversation_history.append(response.candidates[0].content)
        
        turn_count = 0
        max_tool_turns = 10
        while response.function_calls and turn_count < max_tool_turns:
            turn_count += 1
            tool_response_parts: List[genai_types.Part] = []
            for fc_part in response.function_calls:
                tool_name = fc_part.name
                args = fc_part.args or {}
                logging.info(f"Invoking MCP tool '{tool_name}' with arguments: {args}")
                tool_response: dict
                try:
                    session = self.tool_to_session[tool_name]
                    tool_result = await session.call_tool(tool_name, args)
                    logging.info(f"Tool '{tool_name}' executed successfully.")
                    if tool_result.isError:
                        tool_response = {"error": tool_result.content[0].text}
                        logging.warning(f"Tool '{tool_name}' returned error: {tool_result.content[0].text}")
                    else:
                        tool_response = {"result": tool_result.content[0].text}
                        logging.info(f"Tool '{tool_name}' returned result (length: {len(tool_result.content[0].text)} chars)")
                        logging.info(f"Tool '{tool_name}' full result: {tool_result.content[0].text}")
                except Exception as e:
                    tool_response = {"error":  f"Tool execution failed: {type(e).__name__}: {e}"}
                    logging.error(f"Tool '{tool_name}' execution failed: {type(e).__name__}: {e}")
                
                tool_response_parts.append(
                    genai_types.Part.from_function_response(
                        name=tool_name, response=tool_response
                    )
                )
            
            # Add tool responses to conversation history
            tool_content = genai_types.Content(role="user", parts=tool_response_parts)
            self.conversation_history.append(tool_content)
            
            logging.info(f"Added {len(tool_response_parts)} tool response(s) to the conversation.")
            logging.info("Requesting updated response from Gemini...")
            
            response = await self.gemini_client.aio.models.generate_content(
                model=self.model_name,
                contents=self.conversation_history,
                config=genai_types.GenerateContentConfig(
                    temperature=1.0,
                    tools=[tools],
                ),
            )
            
            # Add the new assistant response to history
            self.conversation_history.append(response.candidates[0].content)
            
        if turn_count >= max_tool_turns and response.function_calls:
            logging.warning(f"Stopped after {max_tool_turns} tool calls to avoid infinite loops.")
        logging.info("All tool calls complete. Displaying Gemini's final response.")
        
        # Extract and print the text content from the response
        final_text = ""
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    final_text += part.text
        
        if final_text:
            print(final_text)
        else:
            print("No text response received from Gemini.")
        
        return response

    def clear_history(self):
        """Clear the conversation history"""
        self.conversation_history = []
        print("Conversation history cleared.")

    async def process_query(self, query):
        messages = [{'role':'user', 'content':query}]
        response = self.anthropic.messages.create(max_tokens = 2024,
                                      model = 'claude-3-7-sonnet-20250219', 
                                      tools = self.available_tools,
                                      messages = messages)
        
        process_query = True
        while process_query:
            assistant_content = []
            for content in response.content:
                if content.type =='text':
                    print(content.text)
                    assistant_content.append(content)
                    if(len(response.content) == 1):
                        process_query= False
                elif content.type == 'tool_use':
                    assistant_content.append(content)
                    messages.append({'role':'assistant', 'content':assistant_content})
                    tool_id = content.id
                    tool_args = content.input
                    tool_name = content.name
                    
    
                    print(f"Calling tool {tool_name} with args {tool_args}")
                    
                    # Call a tool
                    session = self.tool_to_session[tool_name] # new
                    result = await session.call_tool(tool_name, arguments=tool_args)
                    messages.append({"role": "user", 
                                      "content": [
                                          {
                                              "type": "tool_result",
                                              "tool_use_id":tool_id,
                                              "content": result.content
                                          }
                                      ]
                                    })
                    response = self.anthropic.messages.create(max_tokens = 2024,
                                      model = 'claude-3-7-sonnet-20250219', 
                                      tools = self.available_tools,
                                      messages = messages) 
                    
                    if(len(response.content) == 1 and response.content[0].type == "text"):
                        print(response.content[0].text)
                        process_query= False

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Chatbot Started!")
        print("Type your queries, 'clear' to reset history, or 'quit' to exit.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
        
                if query.lower() == 'quit':
                    break
                elif query.lower() == 'clear':
                    self.clear_history()
                    continue
                    
                # await self.process_query(query)
                await self.process_query_gemini(query)
                print("\n")
                    
            except Exception as e:
                print(f"\nError: {str(e)}")
    
    async def cleanup(self): # new
        """Cleanly close all resources using AsyncExitStack."""
        await self.exit_stack.aclose()


async def main():
    chatbot = MCP_ChatBot()
    try:
        # the mcp clients and sessions are not initialized using "with"
        # like in the previous lesson
        # so the cleanup should be manually handled
        await chatbot.connect_to_servers() # new! 
        await chatbot.chat_loop()
    finally:
        await chatbot.cleanup() #new! 


if __name__ == "__main__":
    asyncio.run(main())
