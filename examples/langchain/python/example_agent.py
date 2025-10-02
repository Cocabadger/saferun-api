"""Example LangChain agent using SafeRun tool."""
from langchain.agents import initialize_agent, AgentType
from langchain.chat_models import ChatOpenAI

from saferun import SafeRunClient
from .saferun_tools import archive_repo_tool

client = SafeRunClient(api_key='YOUR_API_KEY')
llm = ChatOpenAI(model_name='gpt-4o-mini')

agent = initialize_agent(
    tools=[archive_repo_tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
)

if __name__ == '__main__':
    response = agent.run('Archive the repo owner/repo safely')
    print(response)
