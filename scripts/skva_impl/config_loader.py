globals:
  max_retries: 3
  timeout: 300

methods:
  agile_dev:
    phases:
      - planning
      - implementation
      - review
      - testing

    roles:
      planning:
        analyst:
          model: gpt-4o
          provider: openai
          instructions: >
            Analyze user requirements and break them into tasks.
          temperature: 0.5
          max_tokens: 2000

      implementation:
        coder:
          model: claude-3-opus
          provider: anthropic
          instructions: >
            Write clean, tested code based on the plan.
          temperature: 0.2
          max_tokens: 3000
          retry_count: 2

      review:
        reviewer:
          model: gpt-4o
          provider: openai
          instructions: >
            Review code for quality, security, and style.
