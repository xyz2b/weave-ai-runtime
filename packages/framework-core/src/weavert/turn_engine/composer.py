from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..contracts import (
    MessageAttachment,
    PromptContextEnvelope,
    RuntimeMessage,
    TurnContext,
    prompt_context_from_legacy_runtime_context,
)
from ..definitions import InvocationCapabilityView
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
        available_invocations: Sequence[InvocationCapabilityView] = (),
        base_system_prompt: str,
        memory_fragments: Sequence[str] = (),
        hook_context: Sequence[str] = (),
        compaction_fragments: Sequence[str] = (),
        compaction_summary: dict[str, Any] | None = None,
        compaction_boundary: dict[str, Any] | None = None,
        compaction_continuation: dict[str, Any] | None = None,
        attachments: Sequence[MessageAttachment] = (),
        prompt_context: PromptContextEnvelope | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> ContextAssembly:
        resolved_prompt_context = prompt_context or prompt_context_from_legacy_runtime_context(
            runtime_context,
            memory_fragments=tuple(memory_fragments),
            hook_fragments=tuple(hook_context),
            compaction_fragments=tuple(compaction_fragments),
            attachments=tuple(attachments),
            compaction_summary=compaction_summary,
            compaction_boundary=compaction_boundary,
            compaction_continuation=compaction_continuation,
        )
        sections: list[str] = [base_system_prompt.strip(), agent.prompt.strip()]
        if available_agents:
            agent_lines = [
                f"- {definition.name}: {definition.description}"
                for definition in available_agents
            ]
            sections.append("Agents:\n" + "\n".join(agent_lines))
        if resolved_prompt_context.memory_fragments:
            sections.append("Memory:\n" + "\n".join(resolved_prompt_context.memory_fragments))
        if resolved_prompt_context.hook_fragments:
            sections.append("Hooks:\n" + "\n".join(resolved_prompt_context.hook_fragments))
        if resolved_prompt_context.compaction_fragments:
            sections.append("Compaction:\n" + "\n".join(resolved_prompt_context.compaction_fragments))
        if resolved_prompt_context.attachments:
            attachment_lines = [
                f"- {attachment.name}: {attachment.path}"
                for attachment in resolved_prompt_context.attachments
            ]
            sections.append("Attachments:\n" + "\n".join(attachment_lines))
        if resolved_prompt_context.session_hints:
            hint_lines = [
                f"- {key}: {value}"
                for key, value in sorted(resolved_prompt_context.session_hints.items())
            ]
            sections.append("Session Hints:\n" + "\n".join(hint_lines))
        if resolved_prompt_context.extensions:
            extension_lines = [
                f"- {key}: {value}"
                for key, value in sorted(resolved_prompt_context.extensions.items())
            ]
            sections.append("Context Extensions:\n" + "\n".join(extension_lines))

        turn_context = TurnContext(
            session_id=session_id,
            turn_id=turn_id,
            agent_name=agent.name,
            cwd=cwd,
            messages=tuple(messages),
            available_tools=tuple(available_tools),
            available_skills=tuple(available_skills),
            available_agents=tuple(definition.name for definition in available_agents),
            available_invocations=tuple(available_invocations),
            memory_fragments=resolved_prompt_context.memory_fragments,
            hook_context=resolved_prompt_context.hook_fragments,
            compaction_fragments=resolved_prompt_context.compaction_fragments,
            compaction_summary=resolved_prompt_context.compaction_summary,
            compaction_boundary=resolved_prompt_context.compaction_boundary,
            compaction_continuation=resolved_prompt_context.compaction_continuation,
            attachments=resolved_prompt_context.attachments,
            prompt_context=resolved_prompt_context,
            metadata=resolved_prompt_context.compat_metadata(),
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
