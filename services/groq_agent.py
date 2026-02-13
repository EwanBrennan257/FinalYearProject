# Imports required libraries for API calls
from groq import Groq
from typing import List, Dict, Any, Optional
import os

# Model name to use
MODEL_NAME = "llama-3.3-70b-versatile"  # Updated version

# System prompt from your Modelfile
SYSTEM_PROMPT = """You are a photography assistant for a web app.

Core behavior:
- Prioritize practical, accurate advice for photography (camera settings, lighting, composition, gear, workflow).
- Ask 1–2 clarifying questions when needed (camera type, lighting, subject motion, desired look).
- When giving settings, provide a starting point and explain tradeoffs (ISO vs noise, shutter vs motion blur, aperture vs depth of field).
- Use short headings and bullet points. Avoid long essays unless asked.
- If you're uncertain, say so and suggest how to test or verify.

Gear recommendations:
- Give general categories and features to look for, not specific models or exact prices.
- Focus on what features matter for their use case (weather sealing, sensor size, autofocus, etc).
- Suggest they research current models in their budget.
- Example: "Look for cameras with weather sealing and good autofocus" not "Buy the Sony A7IV for $2,499"
"""

# Few-shot examples from your Modelfile
FEW_SHOT_EXAMPLES = [
    {
        "role": "user",
        "content": "I'm shooting indoors at night and my photos are blurry. What should I do?"
    },
    {
        "role": "assistant",
        "content": """Start with this checklist:
- Shutter speed: If people are moving, try 1/125s (or faster). If it's still, 1/60s can work.
- Aperture: Use the widest you have (e.g., f/1.8–f/2.8) to let in more light.
- ISO: Increase until exposure is correct (often ISO 1600–6400 indoors).
- Stabilization: Turn on IBIS/OIS if available; brace your stance.
Quick question: are you using a phone, DSLR/mirrorless, or a compact?"""
    },
    {
        "role": "user",
        "content": "What's the exposure triangle in simple terms?"
    },
    {
        "role": "assistant",
        "content": """Exposure is controlled by:
- Aperture (f-number): brightness + depth of field
- Shutter speed: brightness + motion blur
- ISO: brightness + noise
Rule of thumb: pick shutter for motion, aperture for the look (background blur), then raise ISO to get the exposure."""
    },
    {
        "role": "user",
        "content": "What's the best camera for outdoor photography?"
    },
    {
        "role": "assistant",
        "content": """For outdoor photography, look for these features:
- Weather sealing: protects against rain, dust, and temperature changes
- Good dynamic range: handles bright skies and dark shadows
- Battery life: cold weather drains batteries faster
- Sensor size: Full-frame or APS-C both work well

What's your budget range and what will you mainly shoot (landscapes, wildlife, sports)?"""
    }
]

class GroqAgent:
    # Agent class for interacting with Groq API
    # Handles chat requests, streaming responses
    def __init__(self, model: str = MODEL_NAME):
        self.model = model  # Name of the model we're using
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        # Initialize agent with API key from environment
        
    def _prepare_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Prepend system prompt and few-shot examples to user messages"""
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        full_messages.extend(FEW_SHOT_EXAMPLES)
        full_messages.extend(messages)
        return full_messages
        
    # Send a chat request to Groq and get a response
    # messages has list of messages with role and content keys
    # stream is whether response should be streamed   
    # Returns dictionary containing success (if it worked), message (the response) and error (Error message)
    def chat(self, messages: List[Dict[str, str]], stream: bool = False) -> Dict[str, Any]:
        try:
            # Prepare messages with system prompt and examples
            full_messages = self._prepare_messages(messages)
            
            # Make API call to Groq with parameters from your Modelfile
            response = self.client.chat.completions.create(
                model=self.model,  # What model to use
                messages=full_messages,  # Conversation history with system prompt
                stream=stream,  # Whether to stream response
                temperature=0.3,  # From your Modelfile - more factual / less rambly
                top_p=0.9,  # From your Modelfile
                max_tokens=8192  # Similar to num_ctx from your Modelfile
            )
            
            if stream:  # Handle streaming vs complete response
                # Return the response object for streaming
                return {"success": True, "response": response}
            else:
                # Parse complete response
                assistant_message = response.choices[0].message.content
                # Return structured success response
                return {
                    "success": True,
                    "message": assistant_message,
                    "model": self.model,
                    "done": True
                }
        # Handles API errors        
        except Exception as e:
            return {
                "success": False,
                "error": f"API request failed: {str(e)}"
            }
    
    # Stream responses from Groq in real time chunks
    # Args: messages are lists of conversation messages
    # Yields: string chunks of the response as they are generated by Groq
    def chat_stream(self, messages: List[Dict[str, str]]):
        try:
            # Prepare messages with system prompt and examples
            full_messages = self._prepare_messages(messages)
            
            # Make API call with streaming enabled
            response = self.client.chat.completions.create(
                model=self.model,  # Model being used
                messages=full_messages,  # Conversation history with system prompt
                stream=True,  # Enables streaming mode
                temperature=0.3,  # From your Modelfile
                top_p=0.9,  # From your Modelfile
                max_tokens=8192  # Similar to num_ctx
            )
            
            # Iterate over response chunks as they come
            for chunk in response:
                if chunk.choices[0].delta.content:  # Skip empty chunks
                    content = chunk.choices[0].delta.content
                    yield content  # Generator pattern sends chunk back
                    
        # If any error occurs during streaming error message                
        except Exception as e:
            yield f"\n\n[Error: {str(e)}]"
    
    def is_model_available(self) -> bool:
        # Check to see if API key is configured and working
        # Return true if we can connect, if not false
        try:
            # Make a simple test request
            test_response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            return True
        # If any error occurs assume model is not available    
        except Exception:
            return False
    
    def get_model_info(self) -> Optional[Dict[str, Any]]:
        # Get information about the model
        # Return dictionary with model details or None if fails
        try:
            return {
                "name": self.model,
                "provider": "Groq",
                "api_configured": bool(os.getenv("GROQ_API_KEY"))
            }
        except Exception:  # Return None if any error occurs
            return None


# Helper function for simple one-off questions
def ask_photography_question(question: str) -> str:
    # Function for asking single photography question
    # Creates agent, sends question and returns answer as string
    # Args: question - user's photography question as string
    # Returns: Assistant answer or error message
    agent = GroqAgent()  # Create new agent
    messages = [{"role": "user", "content": question}]  # Format question as a message list
    result = agent.chat(messages)  # Send question to model and get response
    
    if result["success"]:  # Check if result was successful
        return result["message"]  # Return the assistant's message content
    else:  # Return formatted error message
        return f"Error: {result['error']}"