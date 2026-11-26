"""Theseus Interactive Tools: Tools for human-in-the-loop interaction."""

import logging
from pydantic import BaseModel, Field
from theseus_engine.tools.core.base_tools import BaseTool, ToolExecutionContext, ToolResult

log = logging.getLogger(__name__)


class AskUserInput(BaseModel):
    """Input for asking the user a question."""

    question: str = Field(description="The question or clarification needed from the user.")


class AskUserTool(BaseTool):
    """Asks the interactive user a question and waits for their response."""

    name = "ask_user"
    description = "Ask the human user for more information, clarification, or a decision. Use this when you are stuck or need missing data."
    input_model = AskUserInput
    permission_level = 1

    async def execute(self, arguments: AskUserInput, context: ToolExecutionContext) -> ToolResult:
        # 질문 함수는 런타임이 metadata["ask_user_prompt"]로 넣습니다(질문 문자열 하나를 받아 답을 돌려줌).
        # 승인용 permission_prompt(tool_name, reason)는 시그니처와 용도가 달라 쓰지 않습니다(#59).
        prompt_func = context.metadata.get("ask_user_prompt")

        if not callable(prompt_func):
            return ToolResult(
                output=(
                    "Interactive prompt is not available in the current environment. "
                    "Ask the user your question directly in your reply instead, then end your turn."
                ),
                is_error=True,
            )

        try:
            response = await prompt_func(f"\n[AI Question]: {arguments.question}\nYour Answer: ")
            answer = str(response).strip()

            if not answer:
                return ToolResult(output="(User provided an empty response)")

            return ToolResult(output=f"User's response: {answer}")
        except Exception as e:
            log.error("AskUserTool failed: %s", e)
            return ToolResult(output=f"Failed to get user response: {e}", is_error=True)
