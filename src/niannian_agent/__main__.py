from .agent import Agent
from .birthdae import BirthdaeToolGatewayClient, birthdae_contact_skill
from .import_task_skill import import_task_skill
from .config import Settings
from .http_api import create_server, serve
from .llm import DashScopeClient
from .state import PersistentStateStore
from .runtime_skills import register_runtime_tools


def main() -> None:
    settings = Settings()
    secret = __import__("os").environ.get("AGENT_TOKEN_SECRET", "")
    if not secret:
        raise RuntimeError("AGENT_TOKEN_SECRET is required")
    client = BirthdaeToolGatewayClient(settings.birthdae_agent_tool_url)
    def build_skills(token: str):
        return register_runtime_tools(birthdae_contact_skill(client, token).extend(import_task_skill(client, token)))

    tools = build_skills("")
    agent = Agent(DashScopeClient(settings), tools, settings=settings, skill_factory=build_skills, state_store_factory=lambda token: PersistentStateStore(client, token))
    serve(create_server(agent, secret), int(__import__("os").environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
