# Advisor — Boş Balon Fix (Frontend Handoff)

Lokal Cursor agent için hazırlanmış rehber. Cloud agent bu repoya (`pivony-web-platform-dev`) erişemez; fix **frontend** tarafında yapılmalı.

---

## Sorun

Kullanıcı mesaj gönderince UI **hemen boş bir assistant balonu** render ediyor. Birkaç saniye sonra altta **"Düşünüyor…"** / **"Veri toplanıyor: get_pivony_metrics…"** paneli geliyor. Kullanıcı deneyimi: "önce boş cevap, sonra düşünme".

**İstenen:** Mesaj gönderildiğinde boş balon **hiç görünmesin**; yalnızca thinking/tool status UI gösterilsin; assistant balonu **ilk dolu `content` event'inde** oluşsun.

---

## Mimari

```
pivony-web-platform (React)
    → pivony-api (SSE proxy, cx_gpt chat)
        → pivony-advisor POST /v1/chat/completions?stream=true
```

Backend kasıtlı olarak mesaj gönderilir gönderilmez boş `content` göndermez. Boş balon **%99 frontend optimistic placeholder**.

---

## Backend (zaten yapıldı — pivony-advisor)

**Branch:** `development`  
**Commit:** `38698a8` (`fix(stream): emit thinking status first and skip empty content deltas`)

### SSE sözleşmesi (sıra)

| Sıra | Event | Açıklama |
|------|--------|----------|
| 1 | `{"type":"status","phase":"thinking","detail":"model","suppress_content_bubble":true}` | Stream'in **ilk byte'ı** — client boş balon göstermemeli |
| 2 | `{"type":"thought","delta":"..."}` | Gemini thinking token'ları → "Düşünüyor…" paneli |
| 3 | `{"type":"status","phase":"tool","detail":"get_pivony_metrics"}` | Tool çağrısı → "Veri toplanıyor: …" |
| 4 | `{"type":"content","delta":"..."}` | **Yalnızca final cevap** (boş delta gönderilmez) |
| 5 | `{"type":"done","content":"...","pivony_*":...}` | Tur biter |
| — | `{"type":"content","delta":"...","replace":true}` | Hata / retry mesajı (var olan balonu değiştirir) |

Kaynak dosyalar:
- `src/core/llm_resilience.py` → `make_thinking_status()`
- `src/api/main.py` → `_stream_chat_events()` ilk satırda yield
- `src/core/agent_stream.py` → `emit_content=False` tool loop'ta; boş content filtrelenir

**Frontend fix backend deploy'una bağlı değil** ama `suppress_content_bubble` flag'ini dinlemek en temiz çözüm.

---

## Repo ve path

| Repo | Lokal path (örnek) |
|------|---------------------|
| Frontend (fix burada) | `/Users/emrecalisir/masterrr/pivony-web-platform-dev` |
| API proxy (opsiyonel kontrol) | `pivony-api-dev` |
| Advisor backend (referans) | `pivony-advisor` branch `development` |

---

## Agent görev tanımı (kopyala-yapıştır)

```
# Görev: Advisor chat'te boş assistant balonunu kaldır

Repo: pivony-web-platform-dev
Path: /Users/emrecalisir/masterrr/pivony-web-platform-dev

## Sorun
Kullanıcı mesaj gönderince boş assistant balonu görünüyor, sonra "Düşünüyor…" geliyor.

## Kural
- Sadece pivony-web-platform-dev'de değişiklik yap
- pivony-advisor backend'e dokunma (thinking status zaten var)
- Minimal diff; mevcut thinking/tool UI'ı koru

## Fix
1. Mesaj gönderilirken `{ role: "assistant", content: "" }` placeholder EKLEME
2. SSE'de `type: "status", phase: "thinking", suppress_content_bubble: true` gelince yalnızca thinking UI göster
3. Assistant balonunu ilk `type: "content"` event'inde `delta.trim()` dolu olduğunda oluştur
4. `thought` ve `status(phase:tool)` event'leri content balonunu tetiklemesin
5. `replace: true` content event'lerinde mevcut balonu güncelle (hata mesajları)

## Doğrulama
- Mesaj gönder → boş beyaz balon YOK
- "Düşünüyor…" ve "Veri toplanıyor" görünür
- Final cevap gelince tek assistant balonu dolu görünür
```

---

## Dosya keşfi

Repo root'ta çalıştır:

```bash
cd /Users/emrecalisir/masterrr/pivony-web-platform-dev

# Advisor chat / SSE handler
rg -l "Düşünüyor|Veri toplanıyor|thought|pivony_dashboard|chat/completions" \
  --glob '*.{js,jsx,ts,tsx}'

# Boş assistant placeholder
rg -n "assistant.*content.*['\"]['\"]|content:\s*['\"]['\"]|role:\s*['\"]assistant['\"]" \
  --glob '*.{js,jsx,ts,tsx}'

# SSE event type switch
rg -n "type.*thought|type.*content|type.*status|phase.*tool" \
  --glob '*.{js,jsx,ts,tsx}'

# Bilinen scope util (QA rubric referansı)
rg -n "advisorAnalyticsScope" --glob '*.{js,jsx,ts,tsx}'
```

Muhtemel dizinler (projeye göre değişir):
- `src/pages/console/advisor/` veya `src/containers/Advisor/`
- `src/components/AdvisorChat/` / `CxGpt/` / `Advisor/`
- `util/advisorAnalyticsScope.js` (scope — bu fix'ten bağımsız)

---

## Uygulama pattern'i

### 1) Mesaj gönderme — placeholder kaldır

```javascript
// ❌ YANLIŞ — boş balon sebebi
const onSend = (text) => {
  setMessages((prev) => [
    ...prev,
    { role: "user", content: text },
    { role: "assistant", content: "" }, // ← KALDIR
  ]);
  startStream(text);
};

// ✅ DOĞRU — thinking state, assistant yok
const onSend = (text) => {
  setMessages((prev) => [...prev, { role: "user", content: text }]);
  setStreamPhase("thinking"); // veya isStreaming=true
  setStreamingContent("");  // henüz balon yok
  startStream(text);
};
```

### 2) SSE handler — event ayrımı

```javascript
function handleAdvisorSseEvent(event) {
  switch (event.type) {
    case "status":
      if (event.phase === "thinking" || event.suppress_content_bubble) {
        setStreamPhase("thinking");
        return; // content balonu oluşturma
      }
      if (event.phase === "tool") {
        setStreamPhase("tool");
        setActiveTool(event.detail || event.tool || "");
        return;
      }
      if (event.phase === "retry") {
        setStreamPhase("retry");
        setStatusMessage(event.message || "");
        return;
      }
      break;

    case "thought":
      setStreamPhase("thinking");
      appendThought(event.delta || "");
      return; // content balonu yok

    case "content": {
      const delta = (event.delta || "").trim();
      if (!delta) return;

      setStreamPhase("answering");
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (event.replace || last?.role !== "assistant") {
          // İlk dolu content → assistant balonu burada doğar
          if (last?.role === "assistant" && event.replace) {
            return [...prev.slice(0, -1), { ...last, content: delta }];
          }
          return [...prev, { role: "assistant", content: delta }];
        }
        return [
          ...prev.slice(0, -1),
          { ...last, content: last.content + (event.delta || "") },
        ];
      });
      return;
    }

    case "done":
      setStreamPhase("idle");
      setActiveTool("");
      // done.content varsa finalize et (stream content zaten geldiyse no-op)
      break;

    default:
      break;
  }
}
```

### 3) Render — balon koşullu

```jsx
{/* Thinking panel — streamPhase !== 'idle' iken */}
{(streamPhase === "thinking" || streamPhase === "tool" || streamPhase === "retry") && (
  <AdvisorThinkingPanel
    phase={streamPhase}
    tool={activeTool}
    thoughts={thoughtBuffer}
    message={statusMessage}
  />
)}

{/* Mesaj listesi — assistant satırı yalnızca content doluysa */}
{messages.map((msg, i) => (
  <ChatBubble key={i} role={msg.role} content={msg.content} />
))}
```

**Kritik:** Thinking panel ile assistant balonu **aynı DOM slot'unu paylaşmamalı**. Ekran görüntüsündeki sorun genelde: üstte boş `ChatBubble`, altta ayrı thinking panel.

### 4) pivony-api proxy (opsiyonel kontrol)

API katmanı SSE event'lerini **olduğu gibi** iletmeli; araya boş `content` chunk eklememeli. Şüphelenirsen:

```bash
rg -n "content.*''|delta.*''|assistant.*empty" pivony-api-dev --glob '*.py'
```

---

## Test checklist

- [ ] Kullanıcı mesajı gönder → **boş assistant balonu görünmüyor**
- [ ] Hemen "Düşünüyor…" (thought stream) görünüyor
- [ ] Tool çağrısında "Veri toplanıyor: get_pivony_metrics" görünüyor
- [ ] Final cevap gelince **tek** dolu assistant balonu
- [ ] Hata durumunda (`replace: true`) anlamlı hata metni, boş balon yok
- [ ] İkinci mesaj (follow-up) aynı davranış
- [ ] Dashboard picker / chart event'leri content balonunu erken tetiklemiyor

---

## Scope dışı

| Repo | Neden |
|------|--------|
| `pivony-advisor` | Backend fix zaten merge (`38698a8`) |
| `pivony-api` | Proxy boş chunk eklemiyorsa dokunma |
| `pivony-mcp` | İlgisiz |

---

## Commit önerisi

```
fix(advisor-ui): defer assistant bubble until first content SSE event

Do not append empty assistant messages on send. Honor
status(phase=thinking, suppress_content_bubble) from advisor stream;
show thinking/tool panels only until non-empty content delta arrives.
```

---

## Referanslar

- QA rubric web path: `util/advisorAnalyticsScope.js`
- Advisor handoff: `pivony-advisor/docs/ADVISOR_AGENTIC_HANDOFF.md`
- Backend thinking status: `pivony-advisor/src/core/llm_resilience.py` → `make_thinking_status()`
