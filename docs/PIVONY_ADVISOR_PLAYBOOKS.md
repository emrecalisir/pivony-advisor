# Pivony Advisor — Playbook'lar (SSS)

Bu bölüm Advisor eğitimi için optimize edilmiştir. Her başlık kullanıcıların sorduğu sorularla aynı formatta yazılmıştır.

---

## SORU: Dış veriyi nasıl analiz ederim?

**Kısa cevap:** Market Intelligence planı ile public/social dashboard'lar oluştur, Competitor Analysis sayfasında karşılaştır, My Workspace'te rakip widget'ları ekle.

**Ürün:** Market Intelligence (Outside-in / dış veri)  
**Plan gerekli:** Market Intelligence veya Full Intelligence

### Adım 1 — Plan ve erişimi doğrula

1. `/settings/plan` — Market Intelligence veya Full Intelligence aktif mi kontrol et
2. `/console/industryTopics` (Competitor Analysis) kilitliyse plan yükseltmesi gerekir

### Adım 2 — Public veri kaynaklarını bağla (opsiyonel ama önerilir)

1. `/settings/integrations` aç
2. Filtre: **Data source**
3. Meta (Facebook/Instagram), LinkedIn, Twitter/X vb. OAuth ile bağla
4. Not: App Store, Google Play, Reddit gibi kaynaklar için çoğu durumda ayrı entegrasyon gerekmez — dashboard wizard URL/keyword ile toplar

### Adım 3 — Rekabet dashboard'u oluştur

1. `/console/myDashboards` → **New Dashboard**
2. `/console/source` wizard:
   - **Data source:** Public platform seç (Google Play, App Store, Instagram, X/Twitter, E-commerce, vb.) — Zendesk/CSV değil
   - Dil, ülke, konu sayısı (10–50), tarih aralığı belirle
   - Submit → dashboard oluşturma başlar
3. İlerlemeyi `/console/journey/:id` üzerinden takip et
4. Dashboard **Ready** olunca analize geç

### Adım 4 — Competitor Analysis (Industry Analysis)

1. `/console/industryTopics` aç (sidebar: **Competitor Analysis**)
2. **Start** → brand **group** seç (`GET industry_analysis/groups`)
3. Gruptaki **dashboard'ları** seç
4. **Categories** (üst seviye konular) seç
5. **Generate Charts** — karşılaştırmalı grafikler oluşur
6. Filtreler: tarih, sentiment, stream, kategori (URL tabanlı)

**API özeti:** `industry_analysis/dashboards`, `industry_analysis/categories`, `industry_analysis/saveSources`, `industry_analysis/v2/loadCharts`

### Adım 5 — Digital Experience Score (DES) görüntüle

- My Workspace → Add Metric → **Brand Metrics** → metrik **Digital Experience Score** (metric ID **18**)
- Veya Competitor Analysis VoC chart (C4): `industry_analysis/v2/loadCharts/voc`
- DES: 0–5 dış marka algısı; rakiplerle yan yana

### Adım 6 — My Workspace'te rakip widget'ları

1. `/console/my-workspace` → **Add Metric**
2. Metric Type: **Competitor Metrics**
3. Brand group(lar) + dashboard(lar) seç
4. Comparison Type:
   - **Brand-based** — marka başına konu dağılımı (stacked bar)
   - **Category-based** — konu başına marka dağılımı (doughnut)
   - **Time-based** — zaman trendi (line)
   - **VoC Score** — DES karşılaştırması
5. Topics, sentiment, date range → **Create**

### Adım 7 — Executive sunum (LiveBoard eşdeğeri)

1. `/console/global_executive` (**KPI Views**)
2. Team seç, grafikleri yapılandır
3. **Present** → `/global_executive/presentation` — TV/duvar sunumu

### Adım 8 — Aylık otomatik rapor (opsiyonel)

1. `/console/ai-services/auto-refresh` — brand group + dashboard (workspace ile aynı akış)
2. Pivot vendor, metrikler, konular, zamanlama
3. Sonuçlar: `/console/ai-services/reports`

### Dış veri kaynakları (entegrasyon gerektirmez)

App Store · Google Play · Instagram · X · TikTok · Reddit · Amazon · YouTube · Web reviews

---

## SORU: İç veriyi nasıl analiz ederim?

**Kısa cevap:** Entegrasyonları bağla, owned-data dashboard oluştur, Overview/AI Insights/Custom Topics ile analiz et, alert ve workspace widget ekle.

**Ürün:** Voice of Customer (Inside-out / iç veri)  
**Plan gerekli:** VoC veya Full Intelligence

### Adım 1 — Veri kaynağını bağla

1. `/settings/integrations` → **Data source**
2. Kaynağa göre:

| Kaynak | Ayarlar sayfası alanları | API |
|--------|--------------------------|-----|
| **Zendesk Tickets** | Subdomain, email, API token | `users/add_zendesk_tickets_keys` |
| **Zendesk Live Chat** | Email, live chat token | `users/add_zendesk_livechat_keys` |
| **CSV / Customer Data** | Wizard'da dosya yükle | `dashboards/create/simple` veya `advanced` |
| **Meta, Slack, Jira** | OAuth / API key | integrations sayfası |

### Adım 2 — Dashboard oluştur (iç veri)

1. `/console/myDashboards` → **New Dashboard** → `/console/source`
2. **Owned data** platformu seç:
   - **Customer Data / CSV** (platform 3) — `.csv` veya `.xls` yükle, feedback kolonu map et, opsiyonel pivot kolonları
   - **Zendesk Tickets** (platform 7) — analiz tipi (Tickets/CSAT), dil, tarih, konu sayısı
   - **Zendesk Live Chat** (platform 8) — dil, tarih, konular
3. Simple veya Advanced analysis tipi (plana bağlı)
4. Submit → `/console/journey/:id` ile pipeline takibi
5. E-posta bildirimi gelince dashboard **Ready**

### Adım 3 — Dashboard'u keşfet (Overview)

1. `/console/DashboardData/:id` — **Data Overview**
2. Tarih aralığı seç (üst takvim)
3. Bölümler:
   - **Filtered Data** — review sayısı
   - **Hot Terms** — sık keyword çiftleri
   - **Top Topics** — konu dağılımı (kesişim/birleşim)
   - **Platforms** — kanal dağılımı
   - **Intent Analysis** — niyet sınıflandırması
4. Metin arama ile review filtrele

### Adım 4 — AI Topics ve Custom Topics

- **AI Topics:** `/console/Dashboard/:id` — otomatik keşfedilen konular (bubble view)
- **Custom Topics:** `/console/customTopics/:id` veya `/console/topicLibrary` — kural tanımla, **Run Topics**
- **Unified Topics Map (KDA):** `/console/combined-view/:id` — Key Driver Analysis haritası

### Adım 5 — Root Cause / AI Insights

1. `/console/top-problems/:id` (sidebar: **AI insights**)
2. **Generate AI Insights** — quota kontrolü (`advanced_ai`)
3. Tablo: Root Cause, Recommendation, Status, pivot bazlı sekmeler
4. API: `dashboards/gen-insights`, `dashboards/root-cause`, `dashboards/root-cause/reviews`
5. Export: `/console/report` — Custom Reports

### Adım 6 — Alert kur (KPI anomali)

1. `/console/alerts` → yeni alert
2. Veya KPI Views'tan grafik üzerinde **Add Alert**
3. Eşik, frekans (günlük/haftalık), karşılaştırma tipi
4. API: `notice/alerts/create`

### Adım 7 — My Workspace brand widget'ları (iç veri KPI + GenAI)

1. `/console/my-workspace` → **Add Metric** → **Brand Metrics**
2. Brand group + dashboard seç
3. Metrik seç:
   - KPI: Sentiment Distribution (11), Intent (12), Average Rating (9), vb.
   - GenAI: Root Cause (20), General Summary (21), Key Drivers (23), Highlights (25)
4. Pivot, topics, date range → Create
5. GenAI metriklerde ~30 sn polling; sonuç Smart Narrative veya Table

### Adım 8 — Pivony Advisor ile sor

1. `/console/advisor`
2. Örnek: "Son 30 günde en çok şikayet edilen konular neler?" (VoC kapsamı)

### İç veri kaynakları özeti

Tickets · CRM · Surveys · Call center · NPS · CSV upload · Capture widget · Zendesk · Intercom · Salesforce

---

## SORU: Full Intelligence ile hem iç hem dış veriyi nasıl birlikte analiz ederim?

1. **Full Intelligence** planı aktif olmalı
2. **İç veri:** yukarıdaki VoC playbook (Adım 1–8)
3. **Dış veri:** Market Intelligence playbook (Adım 1–8)
4. **My Workspace:** aynı sayfada brand (iç) + competitive (dış) widget'lar
5. **Monthly AI Insights:** tek dashboard scope'ta GenAI metrikleri
6. **Agentic AI:** VIP recovery, otomatik ticket, executive briefing (Full plan)
7. **Advisor:** Full kapsamda iç + dış veriye soru sor

---

## SORU: My Workspace widget nasıl oluşturulur?

1. `/console/my-workspace`
2. **Create Metric Group** (opsiyonel, gruplama için)
3. **Add Metric** → Add Metric Wizard:
   - Step 1: Metric Type — Brand / Account / Competitor
   - Step 2: Group + Dashboard
   - Step 3: Metrics
   - Step 4: Pivot (opsiyonel)
   - Step 5: Topics (opsiyonel)
   - Step 6: Date Range
   - Step 7: Review & Create
4. API: `POST welcome/groupWidget/create`, `POST welcome/widget/add`
5. Limit: **50 widget** / kullanıcı
6. GenAI metrikler (20,21,23,25): job pending → polling → ready

---

## SORU: Ad hoc rapor nasıl oluşturulur?

1. `/console/report` → **New Report**
2. Generation Type: **One-time**
3. Report Type: Standard veya Advanced AI
4. Group + Dashboard(s), tarih aralığı, pivot, scope, e-posta alıcıları
5. İndir: Reports sekmesi → Ready → Download

---

## SORU: Periyodik (aylık/haftalık) dashboard raporu nasıl oluşturulur?

1. `/console/report` → **New Report**
2. Generation Type: **Periodical**
3. Frequency: WEEKLY / MONTHLY / QUARTERLY
4. Geri kalan adımlar ad hoc ile aynı
5. Sistem otomatik tekrarlar

---

## SORU: Aylık AI Insights (otomatik GenAI raporu) nasıl ayarlanır?

1. `/console/ai-services/auto-refresh`
2. Brand group + dashboard
3. Pivot + vendor değerleri (her vendor = ayrı rapor)
4. Metrikler: GenAI 20,21,23,25 + opsiyonel KPI
5. Konular + zamanlama (ayın 1'i veya son günü)
6. Save → `/console/ai-services/reports` — indir
7. Özel tarih aralığı yok → custom analiz için My Workspace kullan

---

## SORU: Dashboard verisini CSV olarak nasıl indiririm?

1. Dashboard içinde export/download aksiyonu
2. `/console/report?page=download` — **Downloads** sekmesi
3. Ready satır → CSVLink ile indir
4. API örnekleri: `dashboards/file_download`, `dashboards/v2/get_download_link`

---

## SORU: My Workspace PDF nasıl export edilir?

1. `/console/my-workspace` → **Generate PDF report**
2. Grup(lar) seç → onayla
3. `/console/report?page=report` — **My Workspace** satırı → Download

---

## SORU: Kullanıcı nasıl davet edilir?

1. Admin: `/settings/teams` → team oluştur
2. `/settings/users` veya `/settings/team/invite` → e-posta + read-only veya read-write
3. Team quota: dashboard sayısı ata
4. Davet linki: `/signup?invitationId={id}`

---

## SORU: Zendesk entegrasyonu nasıl yapılır?

1. `/settings/integrations`
2. **Zendesk Tickets:** subdomain + ticket email + API token → kaydet
3. **Zendesk Live Chat:** email + chat token
4. Sonra `/console/source` → Zendesk platformu ile dashboard oluştur

---

## SORU: Capture widget nasıl kullanılır?

1. Pivony Capture planı / Pro
2. Tek satır script: `cdn.pivony.com/capture.js` — text, voice, video modları
3. Veriler VoC dashboard ile birleşir
4. `/settings/integrations` veya Capture admin panelinden token al

---

## SORU: Pivony Advisor ne yapabilir?

- Doğal dilde VoC/Market verisine soru sor
- Root cause, segment, rakip karşılaştırma
- Plan kapsamı: VoC plan → iç veri; Market plan → dış veri; Full → ikisi
- Rota: `/console/advisor`
- Jira/Asana/Trello görev önerisi (entegrasyon varsa)

---

## Hızlı rota indeksi

| Ne yapmak istiyorum | Rota |
|---------------------|------|
| İç veri dashboard oluştur | `/console/source` |
| Dış veri karşılaştır | `/console/industryTopics` |
| Widget ekle | `/console/my-workspace` |
| AI Insights (root cause) | `/console/top-problems/:id` |
| Alert | `/console/alerts` |
| KPI TV sunumu | `/global_executive/presentation` |
| Rapor PDF | `/console/report` |
| Aylık AI rapor | `/console/ai-services/auto-refresh` |
| Entegrasyon | `/settings/integrations` |
| Advisor | `/console/advisor` |
