# AgentPulse Quickstart Guide: 5-Minute Setup

Welcome to AgentPulse! This guide will get you up and running with real-time monitoring for your AI agents in under 5 minutes.

## 1. Install the SDK

First, install the AgentPulse Python SDK using pip:

```bash
pip install agentpulse-sdk
```

## 2. Get Your API Key

1.  Go to the AgentPulse Dashboard: [https://agentpulse-dashboard.pages.dev/](https://agentpulse-dashboard.pages.dev/)
2.  Sign up or log in. It's quick and easy.
3.  Once logged in, navigate to your "Settings" or "API Keys" section.
4.  Copy your personal API Key. Keep this secure!

## 3. Initialize AgentPulse in Your Agent Code

Import `agentpulse` and initialize it with your API key. We recommend setting your API key as an environment variable (`AGENTPULSE_API_KEY`) for security.

```python
import agentpulse
import os

# Option 1: Load from environment variable (recommended)
agentpulse.init(api_key=os.getenv("AGENTPULSE_API_KEY"))

# Option 2: Directly pass the API key (less secure for production)
# agentpulse.init(api_key="YOUR_AGENTPULSE_API_KEY")

print("AgentPulse initialized!")
```

## 4. Monitor Your Agent's Actions

AgentPulse integrates seamlessly with your agent's operations. Here are the key decorators and functions to use:

### `@agentpulse.step()` for Agent Steps

Decorate your agent's main "step" or "run" function to automatically log each iteration.

```python
@agentpulse.step(name="my_agent_loop")
def agent_step(task: str):
    # Your agent's logic for a single step
    print(f"Agent is working on: {task}")
    # ... (agent's reasoning, tool calls, etc.)
    agentpulse.log_info(f"Completed task segment for: {task}")
    return "result"

# Example usage
agent_step("research latest AI trends")
```

### `@agentpulse.tool()` for Tool Calls

Decorate functions that your agent calls as "tools" to automatically track their execution, inputs, and outputs.

```python
@agentpulse.tool()
def web_search(query: str):
    print(f"Searching the web for: {query}")
    # Simulate a web search
    return f"Found results for '{query}'"

@agentpulse.step(name="research_task")
def research_agent_step(topic: str):
    agentpulse.log_info(f"Starting research on {topic}")
    search_results = web_search(topic)
    agentpulse.log_info(f"Search complete: {search_results}")
    return search_results

research_agent_step("quantum computing advancements")
```

### `agentpulse.log_info()`, `log_error()`, `log_observation()`

Use these functions within your agent's logic for custom logging, observations, and error reporting.

```python
import agentpulse
import os

agentpulse.init(api_key=os.getenv("AGENTPULSE_API_KEY"))

@agentpulse.step(name="complex_task")
def run_complex_task():
    agentpulse.log_info("Beginning complex calculation.")
    try:
        # Simulate a task that might fail
        result = 10 / 0  # This will raise an error
        agentpulse.log_observation(f"Intermediate result: {result}")
    except Exception as e:
        agentpulse.log_error(f"Calculation failed: {e}")
        # Optionally, re-raise or handle the error
        raise

run_complex_task()
```

## 5. View Your Traces

As soon as your agent runs, open your AgentPulse Dashboard:

[https://agentpulse-dashboard.pages.dev/](https://agentpulse-dashboard.pages.dev/)

You'll see your agent's steps, tool calls, logs, and errors appearing in real-time. Click on any trace to dive deep into its execution details.

That's it! You're now monitoring your AI agents with AgentPulse. Happy building!