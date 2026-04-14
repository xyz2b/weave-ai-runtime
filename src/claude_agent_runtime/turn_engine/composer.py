from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..contracts import MessageAttachment, RuntimeMessage, TurnContext
from ..definitions import AgentDefinition


@dataclass(frozen=True, slots=True)
class PromptComposition:
    system_prompt: str
    turn_context: TurnContext
    messages: tuple[RuntimeMessage, ...]


class PromptComposer:
    def compose(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        available_tools: Sequence[str],
        available_skills: Sequence[str],
        base_system_prompt: str,
        memory_fragments: Sequence[str] = (),
        hook_context: Sequence[str] = (),
        attachments: Sequence[MessageAttachment] = (),
        runtime_context: dict[str, Any] | None = None,
    ) -> PromptComposition:
        sections: list[str] = [base_system_prompt.strip(), agent.prompt.strip()]
        if memory_fragments:
            sections.append("Memory:\n" + "\n".join(memory_fragments))
        if hook_context:
            sections.append("Hooks:\n" + "\n".join(hook_context))
        if attachments:
            attachment_lines = [f"- {attachment.name}: {attachment.path}" for attachment in attachments]
            sections.append("Attachments:\n" + "\n".join(attachment_lines))
        if runtime_context:
            runtime_lines = [f"- {key}: {value}" for key, value in sorted(runtime_context.items())]
            sections.append("Runtime Context:\n" + "\n".join(runtime_lines))

        turn_context = TurnContext(
            session_id=session_id,
            turn_id=turn_id,
            agent_name=agent.name,
            cwd=cwd,
            messages=tuple(messages),
            available_tools=tuple(available_tools),
            available_skills=tuple(available_skills),
            memory_fragments=tuple(memory_fragments),
            attachments=tuple(attachments),
            metadata=runtime_context or {},
        )

        return PromptComposition(
            system_prompt="\n\n".join(section for section in sections if section),
            turn_context=turn_context,
            messages=tuple(messages),
        )

