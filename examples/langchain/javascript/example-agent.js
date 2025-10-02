import { ChatOpenAI } from 'langchain/chat_models/openai';
import { initializeAgentExecutorWithOptions } from 'langchain/agents';
import { safeArchiveRepo } from './saferun-tools.js';

const llm = new ChatOpenAI({ modelName: 'gpt-4o-mini' });

const tools = [{
  name: 'SafeArchiveRepo',
  description: 'Archive a GitHub repository with SafeRun approval',
  func: safeArchiveRepo,
}];

const executor = await initializeAgentExecutorWithOptions(tools, llm, { agentType: 'chat-zero-shot-react-description' });
const result = await executor.invoke({ input: 'Archive owner/repo safely' });
console.log(result.output);
