"""CrewAI task definitions for the quality loop."""

from __future__ import annotations

import os

from crewai import Agent, Task


def _coding_brief(sector: str | None = None) -> str:
    from quality_loop.prompt_config import read_prompt

    resolved = (sector or os.environ.get("QUALITY_LOOP_SECTOR") or "default").strip() or "default"
    return read_prompt("coding_agent", resolved)["content"]


def create_tasks(
    cx_director: Agent | None,
    qa_agent: Agent,
    coding_agent: Agent | None,
    sector: str | None = None,
) -> tuple[Task | None, Task, Task | None]:
    conversation_task = None
    if cx_director is not None:
        conversation_task = Task(
            description=(
                "Pivony Advisor ile tam bir analiz konuşması gerçekleştir.\n\n"
                "Adımlar:\n"
                "1. create_advisor_session tool'u ile yeni session oluştur "
                "(user_id/user_email GEÇME — sunucu .env'deki gerçek kullanıcıyı kullanır)\n"
                "2. pivony_advisor_chat tool'u ile mesaj gönder, yanıt al\n"
                "3. En az 6, en fazla 10 tur konuş\n"
                "4. Her turda bir önceki yanıta göre daha derine in\n"
                "5. Şu senaryoları mutlaka test et:\n"
                "   - Dashboard seç (picker gelirse dashboard_id ile kilitle), sonra detay sor\n"
                "   - Yorum örnekleri iste (list_reviews tetikle)\n"
                "   - Konu trend analizi iste (get_topic_trends)\n"
                "   - Duygu dağılımı sor (get_pivony_metrics)\n"
                "   - Kök neden analizi iste (get_root_causes)\n\n"
                "API: POST /v1/chat/completions (PIVONY_ADVISOR_URL). "
                "Session history quality_loop/outputs/sessions/ altında tutulur.\n\n"
                "Output: session_id ve konuşmanın özeti."
            ),
            expected_output=(
                "JSON formatında:\n"
                "{\n"
                "  'session_id': '<id>',\n"
                "  'turn_count': <int>,\n"
                "  'conversation_summary': [\n"
                "    {'turn': 1, 'user': '...', 'advisor_summary': '...', 'tools_used': [...]},\n"
                "    ...\n"
                "  ],\n"
                "  'notable_issues': ['Gözlemlenen sorunların listesi']\n"
                "}"
            ),
            agent=cx_director,
        )

    qa_description = (
        "Verilen session_id ile konuşmayı oku ve Pivony Advisor performansını değerlendir.\n\n"
        "Adımlar:\n"
        "1. fetch_conversation ile konuşmayı oku\n"
        "2. fetch_advisor_logs ile aynı session için advisor-dev loglarını oku:\n"
        "   - logs/history.log (gerçek API request/response audit)\n"
        "   - logs/advisor.log (ERROR, traceback, rate limit, tool hataları)\n"
        "   Bu adım ZORUNLU — advisor yüzey yanıtı root cause'u gizleyebilir.\n"
        "3. Her advisor yanıtını rubric'e göre değerlendir; log kanıtını evidence'a ekle\n"
        "4. Özellikle şunlara bak:\n"
        "   - Dashboard seçildikten sonra bağlam korunuyor mu?\n"
        "   - tool_actions doğru mu? reasoning'de hata var mı?\n"
        "   - org_wide kullanımı seçili dashboard varken tetikleniyor mu?\n"
        "   - Kullanıcıya hatalı yönlendirme var mı?\n"
        "   - advisor.log'da session zaman penceresinde exception / 429 / API error var mı?\n"
        "   - history.log'da dashboard_picker veya tool failure advisor yanıtında görünmüyor mu?\n"
        "5. Her sorunu dosya/fonksiyon bazında fix önerisiyle raporla\n"
        "6. message_index YALNIZCA fetch_conversation.messages[] içindeki message_index alanından seç; "
        "log veya başka session içeriğinden indeks türetme\n"
    )
    if conversation_task is not None:
        qa_description += "\nCX Director çıktısındaki session_id'yi kullan."

    qa_task = Task(
        description=qa_description,
        expected_output=(
            "config/qa_rubric.txt'deki JSON formatında tam değerlendirme raporu. "
            "Her issue için: severity, category, message_index, description, evidence, fix_hint. "
            "fix_hint mutlaka hangi dosyada ne değişmeli diye belirtmeli."
        ),
        agent=qa_agent,
        context=[conversation_task] if conversation_task else [],
    )

    coding_task = None
    if coding_agent is not None:
        coding_task = Task(
            description=(
                "QA Agent'ın raporundaki sorunları düzelt (önce pivony-advisor, brief'teki geniş scope varsa onu da uygula).\n\n"
                "Adımlar:\n"
                "1. list_project_files ile proje yapısını gör\n"
                "2. QA raporundaki fix_hint'lere göre read_project_file ile dosyaları oku\n"
                "3. Sorunu tam olarak anla\n"
                "4. Fix'i yaz — minimal, odaklı\n"
                "5. apply_fix_and_deploy ile dosyayı güncelle (yalnızca PIVONY_REPO_ROOT altı; git/deploy env flag'leri gerekir)\n"
                "6. Kritik severity sorunlardan başla\n\n"
                "ÖNEMLİ:\n"
                "- Dosyayı değiştirmeden önce MUTLAKA oku\n"
                "- new_content dosyanın TAM güncel içeriği olmalı\n"
                "- new_content HAM metin olmalı; karakterleri manuel escape etme (framework JSON encoding yapar)\n"
                "- apply_fix_and_deploy geçersiz Python syntax'ında yazmayı reddeder (deploy_status: syntax_error)\n"
                "- api/ prefix read-only keşif içindir; yazma yalnızca advisor dosyalarına\n\n"
                "--- Coding Agent Brief ---\n"
                f"{_coding_brief(sector)}"
            ),
            expected_output=(
                "JSON formatında:\n"
                "{\n"
                "  'fixes_applied': [\n"
                "    {\n"
                "      'file': 'src/... veya pivony-mcp/src/...',\n"
                "      'repo': 'pivony-advisor veya pivony-mcp (write/extra-write repo slug)',\n"
                "      'qa_issue_index': 0,\n"
                "      'issue_fixed': '...',\n"
                "      'deploy_status': 'file_written_and_valid|syntax_error|success|skipped|failed'\n"
                "    }\n"
                "  ],\n"
                "  'fixes_skipped': [\n"
                "    {'file': 'N/A', 'repo': null, 'qa_issue_index': 1, 'issue': '...', 'reason': '...'}\n"
                "  ],\n"
                "  'next_test_scenarios': ['...']\n"
                "}\n"
                "qa_issue_index: QA raporundaki issues[] dizisinin 0-tabanlı indeksi."
            ),
            agent=coding_agent,
            context=[qa_task],
        )

    return conversation_task, qa_task, coding_task


def create_analyze_tasks(
    session_id: str, qa_agent: Agent, coding_agent: Agent | None, sector: str | None = None
) -> tuple[Task, Task | None]:
    """QA + coding only, for an existing session id."""
    import json

    qa_task = Task(
        description=(
            f"Mevcut session_id: {session_id}\n\n"
            "1. fetch_conversation ile konuşmayı oku (messages[].message_index ve message_count)\n"
            "2. fetch_advisor_logs ile logs/history.log ve logs/advisor.log incele\n"
            "3. Rubric'e göre JSON rapor üret; evidence alanına log satırlarını ekle\n"
            "4. message_index sadece fetch_conversation.messages[] indeksleri; log başka session ise cite etme"
        ),
        expected_output="qa_rubric.txt JSON formatında tam rapor.",
        agent=qa_agent,
    )
    coding_task = None
    if coding_agent is not None:
        coding_task = Task(
            description=(
                "QA raporundaki kritik sorunları düzelt. Önce dosyaları oku, sonra apply_fix_and_deploy.\n\n"
                "--- Coding Agent Brief ---\n"
                f"{_coding_brief(sector)}"
            ),
            expected_output=(
                "fixes_applied / fixes_skipped JSON; her fix'te repo, qa_issue_index, "
                "file, issue_fixed/deploy_status zorunlu."
            ),
            agent=coding_agent,
            context=[qa_task],
        )
    return qa_task, coding_task
