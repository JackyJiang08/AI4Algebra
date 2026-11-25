Objective: Develop AI4Algebra in Python, ultimately capable of solving Algebra problems. Help me complete the requirements document now.

Input:

The current directory is a uv Python project.
Output:

Generate the requirements document: docs/proposal.md
Steps:

I do not have any prior knowledge about Algebra.
Help me confirm the requirements by asking questions.
Do not guess my intentions.
You must ask me about anything that is unclear.

Objective: Generate a detailed design document based on the requirements document.

Input: Requirements document: docs/proposal.md

Output: Detailed design document: docs/detailed-design.md

Steps:

Write the detailed design document based on the content of the requirements document, structured according to the modules defined within it.
Keep the modules as independent from each other as possible so that they can be tested independently.
Do not guess my intentions. You must ask me about anything that is unclear.

Objective: Break down the smallest executable tasks for each module.

Input: Requirements document: docs/proposal.md Detailed design: docs/detailed-design.md

Output: Task lists:

docs/tasks/<module-name>.md (one for each module)
docs/tasks/progress.md (overall progress)
Steps:

Based on the requirements document and detailed design.
Generate the smallest tasks for Vibe Coding for each module.
Each module corresponds to a <module-name>.md file.
Use a checklist to indicate whether sub-tasks are completed.
In progress.md, use a checklist to indicate whether the module has been completed.

Objective: Generate a Prompt for Vibe Coding.

Input:

Requirements document: docs/proposal.md
Detailed design: docs/detailed-design.md
Task breakdown: docs/tasks
Output:

docs/prompt.md
Steps:

Read the input information to understand the project currently being implemented.
Generate docs/prompt.md as the starting Prompt for Vibe Coding.
The Main Agent is used to track the overall progress.
The Main Agent generates Sub-Agents to implement each module and complete testing.
The entire process will have no human intervention.
The code must have complete pytest unit tests.
And pass mypy and ruff checks.
During the prompt generation process, if there is anything unclear, you must ask me.