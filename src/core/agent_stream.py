"""Streaming advisor agent with Gemini thinking tokens (Vertex AI)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

from google import genai
from google.genai import types
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient

from core.agent import (
    EMPTY_AGENT_REPLY,
    _build_tools,
    _extract_dashboard_picker,
    _finalize_agent_reply,
    _message_text,
    _resolve_dashboard_picker_fallback,
    _to_langchain_messages,
)
from core.agent_state import hard_context_prompt_block, parse_dashboard_id, resolve_hard_agent_state
from core.chart_specs import charts_from_tool_result, merge_chart_lists
from core.llm_resilience import (
    GENERIC_LLM_ERROR_MESSAGE,
    LlmTurnFailed,
    collect_stream_turn,
    is_incomplete_advisor_reply,
    make_rate_limit_retry_status,
)
from core.tool_routing import (
    blocked_tool_result,
    filter_tools_for_state,
    invalid_dashboard_scope_message,
    repeated_tool_failure_result,
    sanitize_function_calls,
    tool_result_indicates_failure,
    validated_tool_invoke,
)
from core.config import (
    AGENT_MAX_TOOL_ITERATIONS,
    DEFAULT_SECTOR,
    GCP_LOCATION,
    GCP_PROJECT,
    ADVISOR_LLM_MODEL,
    LLM_TEMPERATURE,
    sector_slugify,
)
from core.prompts import build_agent_system_prompt

logger = logging.getLogger(__name__)

_genai_client: genai.Client | None = None


def _extract_tool_user_message(result: str) -> str | None:
    """Return user_message from a structured tool JSON payload, if present."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    user_message = payload.get("user_message")
    if isinstance(user_message, str) and user_message.strip():
        return user_message.strip()
    return None


def _stream_failure_message(
    fallback: str,
    last_tool_user_message: str | None,
) -> str:
    """Prefer the most specific tool/API error over a generic LLM failure."""
    return last_tool_user_message or fallback


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True,
            project=GCP_PROJECT,
            location=GCP_LOCATION,
        )
    return _genai_client


def _tool_declarations(tools: list[Any]) -> list[types.Tool]:
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools:
        schema = tool.args_schema.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            if isinstance(prop, dict):
                prop.pop("title", None)
        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters=schema,
            )
        )
    return [types.Tool(function_declarations=declarations)]


def _langchain_to_genai_contents(messages: list[BaseMessage]) -> list[types.Content]:
    contents: list[types.Content] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=str(message.content or ""))],
                )
            )
        elif isinstance(message, AIMessage):
            parts: list[types.Part] = []
            text = _message_text(message)
            if text:
                parts.append(types.Part(text=text))
            for call in getattr(message, "tool_calls", None) or []:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            name=call.get("name") or "",
                            args=call.get("args") or {},
                        )
                    )
                )
            if parts:
                contents.append(types.Content(role="model", parts=parts))
        elif isinstance(message, ToolMessage):
            name = message.name or message.tool_call_id or "tool"
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=name,
                                response={"result": str(message.content or "")},
                            )
                        )
                    ],
                )
            )
    return contents


def _merge_function_calls(
    existing: dict[str, types.FunctionCall],
    part: types.Part,
) -> None:
    fc = part.function_call
    if fc is None:
        return
    key = fc.id or fc.name or "call"
    if key not in existing:
        existing[key] = types.FunctionCall(
            id=fc.id,
            name=fc.name,
            args=dict(fc.args or {}),
        )
        return
    cur = existing[key]
    if fc.name:
        cur.name = fc.name
    if fc.args:
        merged = dict(cur.args or {})
        merged.update(dict(fc.args))
        cur.args = merged


def _stream_model_turn(
    *,
    client: genai.Client,
    model: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    emit_content: bool,
) -> Iterator[dict[str, Any]]:
    """Stream one model turn; return (model_content, function_calls) via StopIteration."""
    content_parts: list[str] = []
    function_calls: dict[str, types.FunctionCall] = {}

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    ):
        if not chunk.candidates:
            continue
        for part in chunk.candidates[0].content.parts or []:
            if getattr(part, "thought", None) and part.text:
                yield {"type": "thought", "delta": part.text}
            elif part.text and not part.function_call:
                content_parts.append(part.text)
                if emit_content:
                    yield {"type": "content", "delta": part.text}
            if part.function_call:
                _merge_function_calls(function_calls, part)

    model_parts: list[types.Part] = []
    full_text = "".join(content_parts)
    if full_text:
        model_parts.append(types.Part(text=full_text))
    for fc in function_calls.values():
        model_parts.append(types.Part(function_call=fc))

    return (
        types.Content(role="model", parts=model_parts),
        list(function_calls.values()),
    )


def _collect_turn_with_rate_limit_status(
    turn_factory: Callable[[], Iterator[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any, list[Any]]:
    """Run collect_stream_turn; emit at most one retry status SSE event on 429 backoff."""
    status_events: list[dict[str, Any]] = []

    def on_rate_limit_retry(attempt: int, max_attempts: int, _wait: float) -> None:
        if status_events:
            return
        status_events.append(make_rate_limit_retry_status(attempt, max_attempts))

    events, model_content, function_calls = collect_stream_turn(
        turn_factory,
        on_rate_limit_retry=on_rate_limit_retry,
    )
    return status_events, events, model_content, function_calls


def _yield_llm_failure(
    exc: LlmTurnFailed,
    current_picker: dict | None,
    current_charts: list[dict[str, Any]],
    dashboard_selection: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Single replaceable error bubble after automatic retries are exhausted."""
    yield {
        "type": "content",
        "delta": exc.user_message,
        "replace": True,
    }
    yield {
        "type": "done",
        "content": exc.user_message,
        "dashboard_picker": current_picker,
        "dashboard_selection": dashboard_selection,
        "charts": current_charts,
    }


def _model_content_for_executed_calls(
    model_content: types.Content,
    executable_calls: list[Any],
) -> types.Content:
    """Keep only function-call parts that will receive a matching FunctionResponse."""
    text_parts = [
        p for p in (model_content.parts or []) if getattr(p, "text", None)
    ]
    fc_parts = [
        types.Part(function_call=fc)
        for fc in executable_calls
    ]
    return types.Content(role="model", parts=[*text_parts, *fc_parts])


def _scope_locked_tool_nudge(_hard: Any) -> types.Content:
    """User nudge when the model proposed only suppressed tool calls (e.g. list_dashboards)."""
    if _hard.has_dashboard:
        text = (
            f"Dashboard scope is already locked to id={_hard.dashboard_id}. "
            "Do not call list_dashboards. Use analysis tools such as get_pivony_metrics "
            "or get_trends with the locked dashboard."
        )
    elif _hard.org_wide:
        text = (
            "Organization-wide scope is already established. Do not call list_dashboards. "
            "Use get_pivony_metrics with org_wide=true."
        )
    else:
        text = (
            "Do not repeat list_dashboards without user intent. "
            "Ask the user to pick a dashboard or proceed with an analysis tool."
        )
    return types.Content(role="user", parts=[types.Part(text=text)])


def _yield_turn_events(
    status_events: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Emit retry status once, then model events (replace waiting text on first content)."""
    replace_pending = bool(status_events)
    for event in status_events:
        yield event
    for event in events:
        if (
            replace_pending
            and event.get("type") == "content"
            and event.get("delta")
        ):
            yield {**event, "replace": True}
            replace_pending = False
        else:
            yield event


def stream_advisor_agent(
    *,
    turns: list[tuple[str, str]],
    sector_slug: str = DEFAULT_SECTOR,
    extra_system_prompt: str | None = None,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    advisor_mode: str,
    user_id: str | None = None,
    page_context: dict | None = None,
    max_iterations: int | None = None,
    llm: Any | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Run the tool-calling loop and yield streaming events:
      - {"type": "thought", "delta": str}
      - {"type": "content", "delta": str}  (final answer only)
      - {"type": "chart", "chart": dict}  (Welcome-compatible chart payload)
      - {"type": "done", "content": str, "dashboard_picker": dict | None,
        "dashboard_selection": dict | None, "charts": list}
    """
    if llm is not None:
        logger.debug(
            "stream_advisor_agent: llm kwarg ignored (streaming uses Vertex genai client)"
        )
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    _hard = resolve_hard_agent_state(turns, page_context)
    tools = filter_tools_for_state(
        _build_tools(
            sector_slug=slug,
            embeddings=embeddings,
            client=client,
            advisor_mode=advisor_mode,
            user_id=user_id,
            page_context=page_context,
            turns=turns,
            hard_state=_hard,
        ),
        _hard,
    )
    tool_map = {tool.name: tool for tool in tools}
    genai_client = _get_genai_client()

    scope_hint = hard_context_prompt_block(_hard)
    system_prompt = build_agent_system_prompt(
        slug, extra_system_prompt, advisor_mode=advisor_mode
    )
    if scope_hint:
        system_prompt = f"{system_prompt}\n\n{scope_hint}"
    lc_messages = _to_langchain_messages(system_prompt, turns)
    contents = _langchain_to_genai_contents(lc_messages[1:])

    base_config = types.GenerateContentConfig(
        system_instruction=types.Content(
            role="user",
            parts=[types.Part(text=system_prompt)],
        ),
        tools=_tool_declarations(tools),
        thinking_config=types.ThinkingConfig(include_thoughts=True),
        temperature=LLM_TEMPERATURE,
    )

    default_dash = _hard.dashboard_id
    if default_dash is None and isinstance(page_context, dict):
        default_dash = parse_dashboard_id(page_context.get("dashboard_id"))
    picker: dict | None = None
    tools_called: set[str] = set()
    failed_tools: set[str] = set()
    dashboard_selection = _hard.dashboard_selection_payload()
    limit = max_iterations or AGENT_MAX_TOOL_ITERATIONS
    final_text = ""
    charts: list[dict[str, Any]] = []

    try:
        yield from _run_agent_stream_loop(
            genai_client=genai_client,
            base_config=base_config,
            contents=contents,
            tool_map=tool_map,
            _hard=_hard,
            default_dash=default_dash,
            user_id=user_id,
            limit=limit,
            picker=picker,
            tools_called=tools_called,
            failed_tools=failed_tools,
            final_text=final_text,
            charts=charts,
            dashboard_selection=dashboard_selection,
        )
    except LlmTurnFailed as exc:
        logger.warning("Agent stream aborted: %s", exc.user_message)
        yield from _yield_llm_failure(exc, picker, charts, dashboard_selection)
        return


def _run_agent_stream_loop(
    *,
    genai_client: genai.Client,
    base_config: types.GenerateContentConfig,
    contents: list[types.Content],
    tool_map: dict[str, Any],
    _hard: Any,
    default_dash: int | None,
    user_id: str | None,
    limit: int,
    picker: dict | None,
    tools_called: set[str],
    failed_tools: set[str],
    final_text: str,
    charts: list[dict[str, Any]],
    dashboard_selection: dict[str, Any] | None,
) -> Iterator[dict[str, Any]]:
    last_tool_user_message: str | None = None
    for step in range(limit):
        try:
            status_events, events, model_content, function_calls = (
                _collect_turn_with_rate_limit_status(
                    lambda: _stream_model_turn(
                        client=genai_client,
                        model=ADVISOR_LLM_MODEL,
                        contents=contents,
                        config=base_config,
                        emit_content=False,
                    )
                )
            )
        except LlmTurnFailed as exc:
            if last_tool_user_message:
                raise LlmTurnFailed(last_tool_user_message) from exc
            raise
        for event in _yield_turn_events(status_events, events):
            yield event

        if not model_content.parts and not function_calls:
            logger.error("Agent stream: empty model turn after retries at step %s", step + 1)
            raise LlmTurnFailed(
                _stream_failure_message(GENERIC_LLM_ERROR_MESSAGE, last_tool_user_message)
            )

        if not model_content.parts:
            if tools_called:
                raise LlmTurnFailed(
                    _stream_failure_message(GENERIC_LLM_ERROR_MESSAGE, last_tool_user_message)
                )
            break

        # Store the original function calls from the model before sanitization
        raw_function_calls_from_model = list(function_calls)
        if not raw_function_calls_from_model:
            synthesis = "".join(
                p.text for p in model_content.parts if getattr(p, "text", None)
            ).strip()
            if synthesis:
                final_text = synthesis
                yield {"type": "content", "delta": synthesis}
                break
            raise LlmTurnFailed(
                _stream_failure_message(GENERIC_LLM_ERROR_MESSAGE, last_tool_user_message)
            )
        # Sanitize function calls: this list will contain only executable calls.
        function_calls_after_sanitization = sanitize_function_calls(function_calls, _hard)
        executable_ids = {id(fc) for fc in function_calls_after_sanitization}

        # Collect function responses here; only responses for actually executed/allowed calls will be added.
        responses_to_send_back = []
        num_suppressed_by_sanitization = 0

        for fc_model_output in raw_function_calls_from_model:
            name = fc_model_output.name or ""
            current_tool_id = id(fc_model_output)

            if name:
                tools_called.add(name)

            if current_tool_id not in executable_ids:
                # This call was suppressed by sanitize_function_calls. Do NOT generate a FunctionResponse for it.
                logger.info("Tool routing: suppressed tool call %s (id=%s). No response generated.", name, current_tool_id)
                num_suppressed_by_sanitization += 1
                continue # Skip to the next function call

            # If we reach here, the call was NOT suppressed by sanitize_function_calls.
            # Proceed to execute it or block it by other rules (e.g., blocked_tool_result).
            yield {"type": "status", "phase": "tool", "detail": name}
            args = dict(fc_model_output.args or {})
            tool = tool_map.get(name)
            result = None

            if blocked := blocked_tool_result(name, _hard) if name else None:
                result = blocked
            elif repeat := repeated_tool_failure_result(name, failed_tools) if name else None:
                result = repeat
            elif tool is None:
                result = f"Bilinmeyen araç: {name}"
            else:
                try:
                    result = validated_tool_invoke(tool, args, _hard, user_id=user_id)
                except Exception as exc:
                    logger.warning("Tool %s invocation failed: %s", name, exc)
                    result = f"Araç hatası ({name}): {exc}"
            
            if name and result is not None and tool_result_indicates_failure(str(result)):
                failed_tools.add(name)
            if result is not None:
                tool_user_message = _extract_tool_user_message(str(result))
                if tool_user_message:
                    last_tool_user_message = tool_user_message
            # Append the response for this processed (executed or blocked by _tool_routing) call.
            if result is not None:
                responses_to_send_back.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=name,
                                    response={"result": str(result)},
                                )
                            )
                        ],
                    )
                )

                # Update UI elements for the executed/blocked tool
                built = _extract_dashboard_picker(name, result, default_dash)
                if built:
                    picker = built
                    yield {"type": "dashboard_picker", "picker": picker}
                new_charts = charts_from_tool_result(name, result)
                if new_charts:
                    charts[:] = merge_chart_lists(charts, new_charts)
                    for chart in new_charts:
                        yield {"type": "chart", "chart": chart}

        # After processing all raw_function_calls, append model turn + responses.
        # Strip suppressed function calls from model_content so Gemini sees equal counts.
        if not function_calls_after_sanitization:
            invalid_msg = invalid_dashboard_scope_message(_hard)
            if invalid_msg:
                raise LlmTurnFailed(invalid_msg)
            logger.info(
                "Agent stream step %s: all %s proposed tool call(s) suppressed; nudging model.",
                step + 1,
                len(raw_function_calls_from_model),
            )
            contents.append(_scope_locked_tool_nudge(_hard))
            continue

        turn_model_content = _model_content_for_executed_calls(
            model_content,
            function_calls_after_sanitization,
        )
        contents.append(turn_model_content)
        contents.extend(responses_to_send_back)

        logger.info(
            "Agent stream step %s: model proposed %s calls, %s suppressed, %s responses generated and sent back.",
            step + 1,
            len(raw_function_calls_from_model),
            num_suppressed_by_sanitization,
            len(responses_to_send_back),
        )

    if picker is None:
        picker = _resolve_dashboard_picker_fallback(
            user_id=user_id,
            default_dashboard_id=default_dash,
            assistant_text=final_text,
            tools_called=tools_called,
            established_scope=_hard.as_established(),
        )
        if picker:
            yield {"type": "dashboard_picker", "picker": picker}

    if is_incomplete_advisor_reply(final_text):
        raise LlmTurnFailed(
            _stream_failure_message(GENERIC_LLM_ERROR_MESSAGE, last_tool_user_message)
        )

    answer = _finalize_agent_reply(final_text)
    yield {
        "type": "done",
        "content": answer,
        "dashboard_picker": picker,
        "dashboard_selection": dashboard_selection,
        "charts": charts,
    }


def stream_simple_completion(
    *,
    system_prompt: str,
    user_messages: list[tuple[str, str]],
) -> Iterator[dict[str, Any]]:
    """Non-agent fallback: stream a single Gemini completion with thinking tokens."""
    genai_client = _get_genai_client()
    contents: list[types.Content] = []
    for role, text in user_messages:
        if role == "user":
            contents.append(
                types.Content(role="user", parts=[types.Part(text=text)])
            )
        elif role == "assistant":
            contents.append(
                types.Content(role="model", parts=[types.Part(text=text)])
            )

    config = types.GenerateContentConfig(
        system_instruction=types.Content(
            role="user",
            parts=[types.Part(text=system_prompt)],
        ),
        thinking_config=types.ThinkingConfig(include_thoughts=True),
        temperature=LLM_TEMPERATURE,
    )

    try:
        status_events, turn_events, model_content, _ = (
            _collect_turn_with_rate_limit_status(
                lambda: _stream_model_turn(
                    client=genai_client,
                    model=ADVISOR_LLM_MODEL,
                    contents=contents,
                    config=config,
                    emit_content=True,
                )
            )
        )
    except LlmTurnFailed as exc:
        yield from _yield_llm_failure(exc, None, [], None)
        return

    for event in _yield_turn_events(status_events, turn_events):
        yield event

    final_text = "".join(p.text for p in model_content.parts if p.text).strip()
    answer = _finalize_agent_reply(final_text or EMPTY_AGENT_REPLY)
    yield {
        "type": "done",
        "content": answer,
        "dashboard_picker": None,
        "dashboard_selection": None,
        "charts": [],
    }
