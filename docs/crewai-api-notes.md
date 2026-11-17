# CrewAI API notes (introspected from the installed version)

Checked on 2026-11-17 with `crewai==1.15.41`, `crewai-tools==1.15.41`, Python 3.13.6.
CrewAI requires `>=3.10,<3.14`.

## Core classes (pydantic fields confirmed present)
- `Agent`: role, goal, backstory, tools, llm (str | BaseLLM), allow_delegation, max_iter, max_rpm,
  verbose, step_callback, max_execution_time
- `Task`: description, expected_output, agent, context, output_pydantic, output_file, callback,
  guardrail / guardrails, create_directory
- `Crew`: agents, tasks, process, memory, verbose, step_callback, task_callback, max_rpm,
  output_log_file, manager_llm, tracing
- `Process`: sequential, hierarchical
- `LLM(model: str, is_litellm=False, **kwargs)`

## Tools
- `SerperDevTool`: fields n_results, country, location, locale, search_type, save_file;
  args schema `{search_query}`
- `ScrapeWebsiteTool`: fields website_url, cookies, headers; args schema `{website_url}`
- `FileWriterTool._run(filename, content, directory="./", overwrite=False)`
- `BaseTool` fields include `max_usage_count` (usable as a per-run cap) and `cache_function`.

## Event bus (`crewai.events`)
Used for live progress and cost logging instead of parsing agent text:
- `ToolUsageStartedEvent`: tool_name, tool_args, agent_role, task_name → "Searching: …" / "Reading: …"
- `TaskCompletedEvent`: output, task → "Stage N complete"
- `LLMCallCompletedEvent`: model, usage, from_agent → token/cost log (terminal only)

## Search provider
SerpApi (serpapi.com) via a custom `BaseTool` (`SerpApiSearchTool` in `tools.py`), not
`SerperDevTool`. Uses organic results, Google Maps `local_results` (rating, reviews, price range)
and `knowledge_graph`. Free plan: 250 searches/month, so runs are capped at 15 searches and
responses are cached in `.cache/search/`.
