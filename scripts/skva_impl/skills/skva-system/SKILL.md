try:
    result = await agent.run()
except TokenLimitError:
    report.phase_error(node_id, "E_TOKEN_BUDGET", "Context too large")
    summarize_and_retry()
