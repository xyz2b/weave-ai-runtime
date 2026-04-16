from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..contracts import MessageAttachment, RuntimeMessage, TurnContext
from ..definitions import AgentDefinition


@dataclass(frozen=True, slots=True)
class ContextAssembly:
    system_prompt: str
    turn_context: TurnContext
    messages: tuple[RuntimeMessage, ...]


PromptComposition = ContextAssembly


class ContextAssembler:
    def assemble(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        available_tools: Sequence[str],
        available_skills: Sequence[str],
        available_agents: Sequence[AgentDefinition] = (),
        base_system_prompt: str,
        memory_fragments: Sequence[str] = (),
        hook_context: Sequence[str] = (),
        compaction_fragments: Sequence[str] = (),
        compaction_summary: dict[str, Any] | None = None,
        compaction_boundary: dict[str, Any] | None = None,
        compaction_continuation: dict[str, Any] | None = None,
        attachments: Sequence[MessageAttachment] = (),
        runtime_context: dict[str, Any] | None = None,
    ) -> ContextAssembly:
        sections: list[str] = [base_system_prompt.strip(), agent.prompt.strip()]
        if available_agents:
            agent_lines = [
                f"- {definition.name}: {definition.description}"
                for definition in available_agents
            ]
            sections.append("Agents:\n" + "\n".join(agent_lines))
        if memory_fragments:
            sections.append("Memory:\n" + "\n".join(memory_fragments))
        if hook_context:
            sections.append("Hooks:\n" + "\n".join(hook_context))
        if compaction_fragments:
            sections.append("Compaction:\n" + "\n".join(compaction_fragments))
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
            available_agents=tuple(definition.name for definition in available_agents),
            memory_fragments=tuple(memory_fragments),
            hook_context=tuple(hook_context),
            compaction_fragments=tuple(compaction_fragments),
            compaction_summary=dict(compaction_summary) if compaction_summary is not None else None,
            compaction_boundary=dict(compaction_boundary) if compaction_boundary is not None else None,
            compaction_continuation=(
                dict(compaction_continuation) if compaction_continuation is not None else None
            ),
            attachments=tuple(attachments),
            metadata=runtime_context or {},
        )

        return ContextAssembly(
            system_prompt="\n\n".join(section for section in sections if section),
            turn_context=turn_context,
            messages=tuple(messages),
        )

    def compose(
        self,
        **kwargs: Any,
    ) -> PromptComposition:
        return self.assemble(**kwargs)


class PromptComposer(ContextAssembler):
    pass
