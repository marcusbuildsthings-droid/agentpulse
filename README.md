# AgentPulse: Real-time Monitoring for Your AI Agents

![AgentPulse Dashboard Screenshot](https://raw.githubusercontent.com/marcusbuildsthings-droid/agentops/main/docs/agentpulse-dashboard-screenshot.png)

**Stop flying blind with your AI agents. Understand, debug, and optimize their behavior in real-time.**

AgentPulse is an open-source, lightweight, and affordable monitoring dashboard built specifically for indie AI agent developers. Get instant visibility into your agent's thoughts, actions, tool calls, and performance – all without the enterprise price tag.

## ✨ Key Features

*   **Real-time Tracing:** See every step, thought, and action your agent takes as it happens.
*   **Tool Call Visibility:** Understand which tools your agent is using, with what inputs, and their outputs.
*   **Error Detection & Debugging:** Quickly pinpoint where and why your agent is failing.
*   **Performance Metrics:** Gain insights into agent latency, cost, and overall efficiency.
*   **Lightweight Python SDK:** Integrate with your existing agent framework in minutes.
*   **Designed for Indie Builders:** Powerful features without the overwhelming complexity or cost of enterprise solutions.

## 💡 Why AgentPulse?

Existing AI agent monitoring solutions are often expensive ($79-$249/month) and over-engineered for individual developers and small teams. AgentPulse cuts through the noise, providing essential observability at a fraction of the cost.

**Built by an AI Agent, for AI Agents:** A significant portion of AgentPulse's development was orchestrated and executed by an AI agent, ensuring it addresses the core needs of the agentic paradigm directly.

## 🚀 Quick Install & Usage

Get your agents monitored in under 5 minutes!

1.  **Install the SDK:**
    ```bash
    pip install agentpulse-sdk
    ```

2.  **Get Your API Key:**
    Sign up on the [AgentPulse Dashboard](https://agentpulse-dashboard.pages.dev/) and grab your API key from the settings.

3.  **Initialize & Monitor Your Agent:**
    ```python
    import agentpulse
    import os

    # Initialize AgentPulse (recommended: use environment variable)
    agentpulse.init(api_key=os.getenv("AGENTPULSE_API_KEY"))

    @agentpulse.tool()
    def search_web(query: str):
        return f"Results for '{query}'"

    @agentpulse.step(name="research_agent")
    def run_research_agent(topic: str):
        agentpulse.log_info(f"Starting research on: {topic}")
        results = search_web(f"latest {topic} breakthroughs")
        agentpulse.log_observation(f"Observed: {results}")
        return f"Research completed for {topic}"

    if __name__ == "__main__":
        run_research_agent("AI ethics")
    ```

4.  **View Your Traces:**
    Open your [AgentPulse Dashboard](https://agentpulse-dashboard.pages.dev/) and see your agent's activity unfold in real-time!

## 📊 Live Demo

Want to see AgentPulse in action without signing up? Click the link below and append `?demo` to the URL!

[**AgentPulse Live Demo**](https://agentpulse-dashboard.pages.dev/?demo)

## 💲 Pricing

AgentPulse offers transparent, indie-friendly pricing.

*   **Free Tier:** Get started with essential monitoring for free.
*   **Pro Plan:** Unlock full features for just **$15/month**.

Compare that to competitors charging $79-$249/month!

## 🤝 Contribute

AgentPulse is open-source! We welcome contributions, bug reports, and feature requests. Check out our [GitHub Issues](https://github.com/marcusbuildsthings-droid/agentops/issues) and join the community.

*   **GitHub Repository:** [https://github.com/marcusbuildsthings-droid/agentops](https://github.com/marcusbuildsthings-droid/agentops)
*   **Landing Page:** [https://marcusbuildsthings-droid.github.io/agentops/](https://marcusbuildsthings-droid.github.io/agentops/)

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
