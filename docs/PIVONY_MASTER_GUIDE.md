# Pivony Platform — Master Kılavuz

**Versiyon:** 2026-05  
**Amaç:** Pivony Advisor eğitimi ve kurumsal referans dokümanı  
**Kaynak:** pivony.com ürün portföyü (pivony-website), platform kod tabanı (My Workspace, Aylık AI Insights), güncel ürün tanımları

> Bu doküman eski Notion Knowledge Center PDF'inin yerine geçer. Ürün bazlı yapılandırılmıştır; My Workspace, widget oluşturma ve periyodik aylık rapor akışları dahil edilmiştir.

---

## İçindekiler

1. [Platform Özeti](#1-platform-özeti)
2. [Ürün Portföyü ve Veri Ayrımı](#2-ürün-portföyü-ve-veri-ayrımı)
3. [Ürün 1: Voice of Customer (VoC)](#3-ürün-1-voice-of-customer-voc)
4. [Ürün 2: Market Intelligence](#4-ürün-2-market-intelligence)
5. [Ürün 3: Full Intelligence](#5-ürün-3-full-intelligence)
6. [Ürün 4: Pivony Capture](#6-ürün-4-pivony-capture)
7. [Ürün 5: Pivony Advisor](#7-ürün-5-pivony-advisor)
8. [Ürün 6: AI Ticket Triage](#8-ürün-6-ai-ticket-triage)
9. [Ürün 7: Engage](#9-ürün-7-engage)
10. [Ortak Yetenekler (Capabilities)](#10-ortak-yetenekler-capabilities)
11. [My Workspace — Widget Oluşturma](#11-my-workspace--widget-oluşturma)
12. [Raporlar, Export ve İndirmeler (Tam Rehber)](#12-raporlar-export-ve-indirmeler-tam-rehber)
13. [Dashboard ve Platform Kullanımı](#13-dashboard-ve-platform-kullanımı)
14. [Entegrasyonlar ve Görev Yönetimi](#14-entegrasyonlar-ve-görev-yönetimi)
15. [Planlar ve Özellik Matrisi](#15-planlar-ve-özellik-matrisi)
16. [Güvenlik, İzinler ve Destek](#16-güvenlik-izinler-ve-destek)
17. [Advisor Playbook'ları — Adım Adım Kullanım (SSS)](#17-advisor-playbookları--adım-adım-kullanım-sss)

---

## 1. Platform Özeti

### Pivony nedir?

Pivony, **iç veri** (müşterilerin size doğrudan söyledikleri) ile **dış veri** (App Store, sosyal medya, rakip sinyalleri) kaynaklarını birleştiren, kök neden analizi yapan ve **Agentic AI** ile otomatik aksiyon tetikleyen bir **Consumer Intelligence** platformudur.

**Ana değer önerisi:** "The full picture. Before they do." — Rakiplerinizden önce tam resmi görün.

### Platform döngüsü (Analyze → Understand → Act)

1. **Analyze** — Voice of Customer: Tickets · CRM · Surveys · Calls
2. **Understand** — Pivony Advisor: Kök neden · Sentiment · Segment analizi
3. **Act** — Pivony Engage: WhatsApp · Otomatik veya 1 tık onay · Anında teslim

### Yedi ürün

| # | Ürün | Veri tipi | Hedef kitle |
|---|------|-----------|-------------|
| 1 | Voice of Customer | İç veri (inside-out) | CX, CS, Support |
| 2 | Market Intelligence | Dış veri (outside-in) | CMO, Strategy, Marketing |
| 3 | Full Intelligence | İç + dış + Agentic AI | CEO, CDO, Enterprise CX |
| 4 | Pivony Capture | Widget · Transkript · Video | CX, Product, UX, Growth |
| 5 | Pivony Advisor | Tüm bağlı veri | Tüm plan kullanıcıları |
| 6 | AI Ticket Triage | Helpdesk ticketları | Support operasyonları |
| 7 | Engage | WhatsApp aksiyonları | CX, Operations |

**Not:** Advisor, AI Ticket Triage ve Engage ayrı plan kartı değildir; ilgili planla birlikte paketlenir.

### Temel farklılaştırıcılar

- **Yerel Türkçe NLU** — çeviri katmanı olmadan Türkçe analiz
- **VoC + Market Intelligence tek platformda**
- **Saniyeler içinde kök neden analizi**
- **Agentic AI** — sadece rapor değil, otomatik aksiyon
- **48–72 saat içinde canlıya alma** (tipik kurulum)
- **Müşteri verisiyle AI eğitimi yapılmaz** (No AI Training on Your Data)
- **KVKK/GDPR uyumlu PII masking**
- **100+ entegrasyon**

---

## 2. Ürün Portföyü ve Veri Ayrımı

### 2.1 İki kaynak, tek gerçek (Two Sources. One Truth)

| Tip | Ürün | Soru | Veri kaynakları |
|-----|------|------|-----------------|
| **İç veri (Internal / Inside-out)** | Voice of Customer | Müşteriler bize ne söylüyor? | Ticket, CRM, anket, çağrı merkezi, Capture widget |
| **Dış veri (External / Outside-in)** | Market Intelligence | Pazar ve rakipler ne diyor? | App Store, sosyal medya, forum, rakip sinyalleri |
| **Her ikisi** | Full Intelligence | 360° görünüm + otomasyon | İç + dış + Agentic AI |

### 2.2 Plan seçim rehberi

| Plan | Tagline | Alıcı profili |
|------|---------|---------------|
| **VoC** | Kendi müşterilerinizin sesi | CX Director, Customer Success, Support Lead |
| **Market** | Pazar ve rakipler | CMO, Strategy Director, Marketing |
| **Full** | Her ikisi + Agentic AI | CEO, CDO, Enterprise CX |
| **Capture** | Yazılı, sesli, video geri bildirim | CX, Product, UX, Growth |
| **Enterprise** | Sınırsız, SSO, dedicated analyst | Büyük programlar, regüle sektörler |

### 2.3 Capture Free Tier

- 100 yanıt/ay, yazılı widget, temel sentiment, sınırlı Highlights
- Pro: kök neden analizi, ses & video, VoC entegrasyonu

---

## 3. Ürün 1: Voice of Customer (VoC)

**URL:** pivony.com/products/voc  
**Badge:** Voice of Customer · Internal voice analysis  
**Veri yönü:** Inside-out

### 3.1 Konumlandırma

> "What Is Your Customer Feeling? Who, Where, Why?"

Müşteri geri bildirimini kargo verisi, satış kanalı ve segment bilgisiyle birleştirin. Saniyeler içinde kök neden analizi yapın; her mikro-segmentin ne yaşadığını görün.

### 3.2 Çözülen problemler

| Problem | Açıklama |
|---------|----------|
| Ortalama yanıltır | NPS 42 olabilir; VIP segmentte 18, online kanalda 67 |
| Geri bildirim tek başına anlamsız | "Kargo geç geldi" — hangi kargo firması? hangi bölge? VIP mi? |
| Güçlü yönler kaybolur | Ekipler şikayete odaklanır, Key Drivers görünmez |

### 3.3 Temel yetenekler

| Yetenek | Açıklama |
|---------|----------|
| **Auto Topic Detection (Gen AI)** | Manuel taksonomi gerekmez; yeni konular otomatik yüzeye çıkar |
| **Agentic Actions** | Kritik segmentte insight → Jira/Zendesk ticket, Slack alert, executive briefing |
| **Highlights** | "What's Going Great" / "Needs Improvement" — dönemsel otomatik özet |
| **Key Drivers Summary** | Performans, önem ağırlığı, negatiflik payı — istatistiksel sürücü analizi |
| **Micro-segmentation** | Kargo, kanal, segment (VIP/standart/yeni) ile geri bildirim birleştirme |
| **Root-cause analysis** | "Ürün bozuk" değil → "3. parti kargo gecikmesi, VIP segment, İstanbul bölgesi" |
| **KPI monitoring & anomaly alerts** | Segment bazlı anormal kayma → anında e-posta |
| **PII masking** | KVKK/GDPR uyumlu veri maskeleme |

### 3.4 Veri kaynakları

**Geri bildirim:**
- Zendesk / Freshdesk
- Salesforce CRM
- Intercom / canlı chat
- Çağrı merkezi kayıtları
- NPS anketleri
- CSV / Excel yükleme
- Pivony Capture widget

**Segment / operasyonel:**
- Kargo firması ve teslimat verisi
- Satış kanalı (online / mağaza / partner)
- Müşteri segmenti (VIP / standart / yeni)
- Sipariş kategorisi ve değeri
- Coğrafi bölge
- CRM segmentasyon verisi

### 3.5 VoC planında dahil özellikler

- Root-cause analysis
- Sentiment & intent analysis
- KPI monitoring & anomaly alerts
- PII masking (KVKK/GDPR)
- Jira / Slack / Asana entegrasyonu
- Native Turkish NLU
- Dosya yükleme veya API entegrasyonu

### 3.6 Referans: Etstur

500+ tesis genelinde misafir geri bildirimi; property-level segment analizi, Highlights ve mikro-segment görünürlüğü.

---

## 4. Ürün 2: Market Intelligence

**URL:** pivony.com/products/market-intelligence  
**Badge:** Market Intelligence · External voice analysis  
**Veri yönü:** Outside-in

### 4.1 Konumlandırma

> "Who's leading your category? What is the customer really saying? Monitor competitors in real time."

App Store yorumlarından sosyal medyaya — dış sesi tek yerde görün.

### 4.2 Çözülen problemler

| Problem | Açıklama |
|---------|----------|
| Rakip görünmezliği | App Store puan düşüşü aylar sonra fark edilir |
| Kampanya körlüğü | Sosyal medyada kampanya karşılığı gerçek zamanlı bilinmez |
| Eski strateji | Yılda iki kez pazar araştırması — veri bayat |

### 4.3 Temel yetenekler

| Yetenek | Açıklama |
|---------|----------|
| **Digital Experience VoC Score (DES)** | 0–5 dış marka algısı; rakiplerle yan yana karşılaştırma |
| **Competitive benchmarking** | Müşteri gözünden güçlü/zayıf yönler |
| **Trend & anomaly detection** | Konu patlaması, rakip düşüşü → gerçek zamanlı alert |
| **LiveBoard** | TV duvarında canlı pazar sinyalleri |
| **Conversation Landscape** | Büyüyen/küçülen konuların görsel haritası |
| **Multi-source analysis** | App Store, Google Play, Instagram, X, Reddit, Amazon, web yorumları |

### 4.4 Veri kaynakları

App Store · Google Play · Instagram · X (Twitter) · TikTok · Reddit · Amazon · YouTube · Web reviews

**Entegrasyon gerekmez** — sistem otomatik toplar.

### 4.5 İki kullanım senaryosu

1. **Marka & itibar koruması** — kriz erken tespiti, rakip kampanya takibi
2. **Pazar genişlemesi** — kategori benchmark, karşılanmamış ihtiyaç sinyalleri

### 4.6 Referans müşteriler

Allianz, Karaca, Papara, Akbank, Millenicom

---

## 5. Ürün 3: Full Intelligence

**URL:** pivony.com/products/full-intelligence  
**Badge:** Full Intelligence · 2026 · Agentic AI

### 5.1 Konumlandırma

> "Internal + external voice. One dashboard. Autonomous action."

Voice of Customer + Market Intelligence + Agentic AI. Kritik anlarda sistem otomatik devreye girer.

### 5.2 Köprü: İç + dış ses

| Kaynak | Etiket | Veri |
|--------|--------|------|
| İç | Internal voice | Tickets · CRM · Surveys · Calls |
| Dış | External voice | App Store · Social · Competitors |
| Birleşik | 360° unified view | Önceliklendirilmiş aksiyon tek dashboard'da |

> "Müşterilerinizi duyuyorsunuz — peki rakibinizin müşterileri ne diyor?"

### 5.3 Agentic AI ajanları

| Ajan | Rol |
|------|-----|
| **Frontline (Ön hat)** | Ses/metin analizi, sentiment, VIP service recovery |
| **Operational (Operasyon)** | Tekrarlayan şikayetler → mağaza/IT ticket, kronik iade eskalasyonu |
| **Strategic (Strateji)** | SLA takibi, CX direktörü alert, haftalık executive briefing |

### 5.4 Geleneksel vs Pivony Full Intelligence

| Kriter | Geleneksel platform | Pivony Full Intelligence |
|--------|---------------------|--------------------------|
| Veri işleme | Rapor üretir | Pattern recognition |
| Triage | İnsan yönetimli | Otonom önceliklendirme |
| Yürütme | Dashboard'da kalır | Workflow tetikler |
| Hız | Haftalık raporlar | Gerçek zamanlı |

### 5.5 Full plan özellikleri

- VoC planındaki her şey
- Market Intelligence planındaki her şey
- 360° unified dashboard
- Smart cross-source prioritization
- Agentic AI (autonomous action)
- Dedicated Customer Success lead
- Weekly executive briefing
- Custom onboarding journey
- Enterprise security: SSO/SAML, RBAC, PII masking, private cloud

### 5.6 Referans: Vodafone Turkey, Samsung

Vodafone: iç + dış ses birlikte CX süreçlerine entegre. Samsung: 360° consumer intelligence.

---

## 6. Ürün 4: Pivony Capture

**URL:** pivony.com/products/voice-capture  
**Badge:** Pivony Capture · 2026 · NEW

### 6.1 Konumlandırma

> "Collect Feedback. Let AI Understand. Let the System Act."

Yazılı, sesli veya video — müşteri tercih ettiği formatta anlatır. VoC AI anında analiz eder. Hotjar + Typeform + UserTesting tek platformda.

### 6.2 Üç geri bildirim modu

| Mod | Akış |
|-----|------|
| **Text (Yazılı)** | Widget → kullanıcı yazar → VoC AI → kök neden + aksiyon |
| **Voice (Sesli)** | ~2 dk kayıt → AI transkript → VoC analizi → aksiyon |
| **Video** | Kamera → konuşma + yüz ifadesi → VoC analizi → aksiyon |

### 6.3 Özellikler

- 3 format, tek platform
- Native Turkish speech (çeviri katmanı yok)
- Video + facial sentiment analysis
- Instant VoC AI
- Tek satır entegrasyon (~5 dakika)
- VoC dashboard, ticket ve CRM ile birleşme

### 6.4 Tetikleyici seçenekleri

Exit intent, time on page, scroll depth, manual, cart abandonment, after form submit, after purchase, error page

### 6.5 Rakip karşılaştırma (özet)

Pivony Capture; Hotjar, Typeform, UserTesting'e karşı: AI analizi, kök neden, otonom aksiyon, native Turkish NLU, VoC entegrasyonu ve anında sonuç sunar.

### 6.6 Entegrasyon örneği (HTML)

```html
<script
  src="https://cdn.pivony.com/capture.js"
  data-token="YOUR_TOKEN"
  data-modes="text,voice,video"
  data-position="bottom-right"
  data-trigger="exit-intent"
  data-question="How was your experience?"
  data-lang="en">
</script>
```

---

## 7. Ürün 5: Pivony Advisor

**URL:** pivony.com/products/pivony-advisor  
**Platform rotası:** `/console/advisor`  
**Eski ad:** CX-GPT (redirect: `/products/cx-gpt` → `/products/pivony-advisor`)

### 7.1 Konumlandırma

> "Talk to Your Data In Real Time"

Dashboard'ların ötesinde, tüm müşteri ve tüketici verinizle doğal dilde sohbet edin. ChatGPT genel tavsiye verir; Pivony Advisor **kendi verinizden** stratejik insight üretir.

### 7.2 Nasıl çalışır?

1. **Tüm veriyi bağlayın** — App Store, Zendesk, NPS, sosyal medya, çağrı merkezi
2. **Doğal dilde sorun** — SQL gerekmez: "Bu ay müşteri memnuniyeti neden düştü?"
3. **Aksiyon alın** — Jira, Asana, Trello görevleri insight'tan oluşturulur

### 7.3 Özellikler

| Özellik | Açıklama |
|---------|----------|
| Natural Language Analysis | Karmaşık filtreler ve segment karşılaştırmaları saniyeler içinde |
| Action Recommendations | Her insight sonrası ne yapılacağı + ilgili ekibe otomatik atama |
| Root Cause Analysis | Ne oldu değil, neden oldu |
| Competitor Comparison | Rakip geri bildirimleriyle gerçek zamanlı konumlandırma |

### 7.4 Plan bazlı Advisor kapsamı

| Plan | Advisor veri kapsamı |
|------|---------------------|
| VoC | VoC (iç) verisi |
| Market | Market (dış) verisi |
| Full | Full (iç + dış) |
| Enterprise | Full+ |

### 7.5 Örnek sorular

- "Bu çeyrek NPS'i düşüren en kritik 3 faktör nedir?"
- "Rakiplerimize kıyasla hangi kategorilerde öne çıkıyoruz?"
- "Hangi müşteri segmentinde churn riski var ve neden?"
- "Müşteri memnuniyetini en hızlı artıracak 5 aksiyon nedir?"
- "Markamız hakkında sosyal medyada en çok konuşulan konular neler?"

### 7.6 Teknik not (Advisor servisi)

Standalone `pivony-advisor` servisi Qdrant koleksiyonu `pivony_customer_knowledge` üzerinde RAG yapar. Bu master kılavuz Advisor eğitim verisinin kaynağıdır. Bilgi bağlamda yoksa Advisor "Bu bilgiye şu an sahip değilim" der — uydurmaz.

---

## 8. Ürün 6: AI Ticket Triage

**URL:** pivony.com/products/ai-ticket-triage

### 8.1 Konumlandırma

> "Every Support Ticket, Triaged in Seconds. By AI."

Gelen destek talebini okuma, konu ve aciliyet sınıflandırma, doğru ekibe yönlendirme — insan müdahalesi olmadan.

### 8.2 4 adımlı iş akışı

1. **Ingest** — Zendesk, Freshdesk, Intercom, Salesforce, e-posta
2. **Classify** — Konu, duygu, aciliyet (çok dilli)
3. **Route** — Doğru kuyruk, etiket, öncelik
4. **Learn** — Temsilci geri bildirimiyle sürekli iyileşme (~%85–92 doğruluk, ~2 hafta)

### 8.3 Otomatikleştirilebilir metrikler

Konu sınıflandırma, öncelik puanlama, ekip yönlendirme, etiket atama, hacim trend uyarıları, VIP + olumsuz sentiment eskalasyonu

### 8.4 AI vs Manuel

| Boyut | Manuel | AI |
|-------|--------|-----|
| Hız | Dakikalar/ticket | 1 saniyenin altı |
| Ölçek | Spike'ta bozulur | Lineer, her hacim |
| Öğrenme | Personel değişiminde sıfırlanır | Sürekli iyileşir |
| Dil | Temsilci dilleriyle sınırlı | Çok dilli, yerleşik |

### 8.5 Paketleme

Ayrı plan kartı değil; mevcut planla paketlenir. VoC triage verisini kök neden analizi ve raporlamaya besler.

---

## 9. Ürün 7: Engage

**URL:** pivony.com/products/engage

### 9.1 Konumlandırma

> "The Right Message. WhatsApp. Right Now."

Pivony insight'ı veya müşteri yolculuğu adımı tetikler → kişiselleştirilmiş WhatsApp mesajı → webhook ile yanıt takibi → döngü kapanır.

### 9.2 Akış

Trigger → AI Decision → Approval (otomatik veya 1 tık) → WhatsApp delivery → Webhook tracking

### 9.3 İki tetik modu

| Mod | Örnekler |
|-----|----------|
| **Insight-triggered** | NPS 0–6, negatif sentiment spike, VIP şikayet |
| **Process-triggered** | Sipariş kargolandı, teslimat dışında, başarısız teslimat, abonelik yenileme (REST API) |

### 9.4 Kullanım senaryoları

Kargo bildirimleri (%98 açılma vs %20 SMS), churn recovery, post-delivery CSAT, telafi/teklif, proaktif alertler

### 9.5 Enterprise mimari

On-prem veya cloud, REST API smart queue, dinamik Meta şablonları, webhook feedback loop, raporlama dashboard, %99.9 SLA + VPN

---

## 10. Ortak Yetenekler (Capabilities)

Bu yetenekler ürünler arası paylaşılır; pivony.com'da ayrı capability sayfaları vardır.

| Yetenek | URL | Özet |
|---------|-----|------|
| NPS Analysis | /nps-analysis | Segment, kanal, dönem bazlı NPS |
| Root Cause Analysis | /root-cause-analysis | Neden hareket ediyor — sadece ne değil |
| Competitor Analysis | /competitor-analysis | DES ile rakip benchmark |
| Sentiment Analysis | /sentiment-analysis | Pozitif/negatif ötesinde duygu taksonomisi |
| Customer Journey | /customer-journey | Onboarding → renewal touchpoint haritası |
| Key Driver Analysis | /key-driver-analysis | 50 şikayetten sadece 3'ü NPS'i hareket ettirir |
| KPI Monitoring | /kpi-monitoring | Haftalık rapor değil, gerçek zamanlı anomali |
| Micro-segmentation | /micro-segmentation | CRM, kargo, kanal, coğrafya birleştirme |

### Root Cause Analysis — 8/8 kontrol listesi

- Tüm geri bildirim kanalları bağlı
- Kargo, kanal, segment verisi birleştirilmiş
- Mikro-segment seviyesi (portföy ortalaması değil)
- Önceliklendirilmiş aksiyonlanabilir çıktı
- Gerçek zamanlı işleme
- Zendesk/Freshdesk/Salesforce entegrasyonu
- 48 saat içinde canlı
- Agentic AI: ticket/alert/briefing tetikler

---

## 11. My Workspace — Widget Oluşturma

**Ürün adı:** My Workspace  
**Platform rotası:** `/console/my-workspace`  
**Eski rota:** `/home` → otomatik yönlendirme  
**Sidebar etiketi:** "My Workspace" (dashboard_sidebar.11)

### 11.1 My Workspace nedir?

Kişiselleştirilmiş metrik dashboard'udur. Kullanıcılar **widget grupları** ve **widget'lar** oluşturarak KPI grafikleri, GenAI anlatıları, rekabet görünümleri ve hesap metriklerini tek sayfada takip eder.

**Aylık AI Insights raporları da aynı widget modelini kullanır** — otomatik oluşturulan gruplar `is_auto_report=true` ile işaretlenir.

### 11.2 Limitler ve izinler

| Kural | Değer |
|-------|-------|
| Maksimum widget / kullanıcı | **50** (tüm gruplar genelinde) |
| Grup silme | Grup boş olmalı (önce widget'lar silinir) |
| Düzenleme izni | `WorkspaceContentEditable` — read-only kullanıcılar sadece görüntüler |

### 11.3 Kullanıcı akışı

```
My Workspace aç
  → GET /api/welcome/groups/all (gruplar + widget'lar + workspace_limits)
  → Grup oluştur: POST /api/welcome/groupWidget/create { name }
  → "Add Metric" → Add Metric Wizard (çok adımlı)
  → POST /api/welcome/widget/add (her metrik için)
  → GenAI metrikleri: WelcomeJob status = pending → 30 sn polling
  → Görünür widget'lar: POST /api/welcome/widget/data
  → Grafik / tablo / Smart Narrative render
```

### 11.4 Add Metric Wizard adımları

| Adım | İçerik |
|------|--------|
| 1. Metric Type | Brand / Account / Competitor |
| 2. Group / Dashboard | Marka grubu ve dashboard seçimi |
| 3. Metrics | Metrik(ler) seçimi |
| 4. Pivot | Opsiyonel pivot kolonu ve değerleri |
| 5. Topics | Opsiyonel konu daraltma |
| 6. Date Range | Tarih aralığı |
| 7. Review & Create | Özet ve oluştur |

**Competitor metriklerinde ek adım:** Competition Type (Brand-based / Category-based / Time-based)

### 11.5 Widget tipleri (metric_type)

| Tip | API değeri | Açıklama |
|-----|------------|----------|
| Account Metrics | `account` (1) | Organizasyon aktivite metrikleri |
| Brand Metrics | `brand` (2) | Dashboard KPI'ları, GenAI anlatıları, sentiment/intent grafikleri |
| Competitor Metrics | `competitive` (3) | Kategori/marka/zaman rekabet grafikleri |

### 11.6 Representation type (görselleştirme)

| Değer | Tip |
|-------|-----|
| 1 | Chart (grafik) |
| 2 | List (liste) |
| 3 | Table (tablo) |
| 4 | Smart Narrative (GenAI anlatı) |

**Not:** Bazı GenAI metrikleri yalnızca Smart Narrative (4) veya yalnızca Table (3) olarak kullanılabilir.

### 11.7 Metrik kataloğu

#### KPI / grafik metrikleri

| ID | Ad | Açıklama |
|----|-----|----------|
| 8 | Review Statistics | Geri bildirim sayısı ve frekans |
| 9 | Average Rating | NPS, CSAT, VoC ortalama puan |
| 10 | Positive Sentiment Score | Saf pozitif geri bildirim yüzdesi |
| 11 | Sentiment Distribution | Pozitif/negatif/nötr/karışık dağılım |
| 12 | Intent Distribution | Konu bazında intent dağılımı |
| 14 | Sentiment per Topic | Konu bazında sentiment |
| 15 | Participation per Topic | Konu bazında katılım |
| 18 | Digital Experience Score | Dış marka algı skoru |
| 27 | Decision Analysis | Sistem karar hacmi |
| 28 | Hot Terms | Trend anahtar kelimeler |

#### GenAI metrikleri (AI kredisi tüketir)

| ID | Ad | Açıklama |
|----|-----|----------|
| 20 | Root Cause & Recommendations | Birincil sürücüler ve önerilen aksiyonlar |
| 21 | General Summary | Geri bildirimin genel metin özeti |
| 23 | Key Drivers Analysis | Deneyim skorlarını etkileyen faktörler, önceliklendirme |
| 25 | Highlights Summary | Kritik pozitif/negatif alıntılar |

**Aylık raporlarda da aynı GenAI metrik ID'leri kullanılır:** 20, 21, 23, 25.

GenAI widget oluşturulduğunda `WelcomeJob` `pending` kalır; `genai_widget_processor` işler. UI 30 saniyede bir poll eder. "Regenerate AI" ile yeniden kuyruğa alınabilir.

### 11.8 Widget oluşturma payload'ı

```json
{
  "metric_type": "brand | account | competitive",
  "metric_id": 20,
  "representation_type": 4,
  "widget_group_id": 123,
  "dashboard_ids": ["3057"],
  "group_ids": [64],
  "topics": [],
  "comparison_type": "brand | category | time",
  "sentiment": null,
  "pivot_key": "Vendor",
  "pivot_values": ["Brand A"],
  "topic_ids": ["topic-uuid"],
  "since": "2025-01-01",
  "until": "2025-01-31"
}
```

### 11.9 Competitor widget tipleri

| Tip | Görselleştirme |
|-----|----------------|
| Brand-based | Marka başına konu dağılımı (yatay stacked bar) |
| Category-based | Konu başına marka dağılımı (doughnut) |
| Time-based | Konu trendleri (çizgi grafik) |

### 11.10 Grup yönetimi

- **Create Metric Group** — ilişkili KPI'ları grupla
- **Rename group** — PUT `/api/welcome/groups/rename`
- **Delete group** — yalnızca boş gruplar silinebilir; içindeki widget'lar kalıcı silinir
- **Duplicate group name** — hata verir

### 11.11 PDF export

My Workspace PDF export akışının tam detayı için → **[Bölüm 12.5](#125-my-workspace-pdf-export-ad-hoc)**.

### 11.12 API endpoint özeti

| Endpoint | Method | Amaç |
|----------|--------|------|
| `/api/welcome/groups/all` | GET | Tüm gruplar + widget'lar + limitler |
| `/api/welcome/groupWidget/create` | POST | Grup oluştur |
| `/api/welcome/widget/add` | POST | Widget oluştur + job |
| `/api/welcome/widget/data` | POST | Widget KPI/GenAI verisi |
| `/api/welcome/groups/rename` | PUT | Grup adını değiştir |
| `/api/welcome/groups/delete` | DELETE | Boş grup sil |
| `/api/welcome/brands` | GET | Rekabet marka grupları |
| `/api/welcome/dashboards` | POST | Marka ID'leri için dashboard'lar |
| `/api/welcome/topics` | POST | Dashboard kapsamı için konular |

---

## 12. Raporlar, Export ve İndirmeler (Tam Rehber)

Platformda **PDF raporları** ile **dosya export'ları (CSV/XLSX)** farklı tablolarda ve farklı UI sekmelerinde yönetilir. Ayrıca **üç bağımsız üretim hattı** vardır:

1. **Reports & Downloads sihirbazı** — Dashboard PDF (ad hoc + periyodik)
2. **My Workspace PDF export** — Workspace widget'larından tek seferlik PDF
3. **Monthly AI Insights** — Otomatik aylık GenAI raporları (`AiReport` + ayrı PDF hattı)

---

### 12.0 Veri modeli: `ReportPdf.type` matrisi

Tüm PDF/export işleri `ReportPdf` tablosunda tutulur. **`type`** alanı rapor kategorisini belirler (`generation_type` ile karıştırılmamalı).

| `type` | UI etiketi | Nasıl oluşur | İndirme alanı | Nerede listelenir |
|--------|------------|--------------|---------------|-------------------|
| **1** | Dashboard Report | `POST report/create` (NewReport), varsayılan | `ReportLink` (PDF URL) | `/console/report` → **Reports** sekmesi |
| **2** | (Export) | Dashboard veri indirme API'leri | `CSVLink` (presigned URL) | `/console/report` → **Downloads** sekmesi |
| **3** USER | **My Workspace** | My Workspace → Generate PDF | `ReportLink` | Reports sekmesi |
| **3** SYSTEM | **Auto Report** (legacy) | Eski otomatik workspace PDF worker | `ReportLink` | Reports sekmesi |
| **4** | (listelenmez) | Monthly AI Insights worker | `AiReport.pdf_url` ← `ReportLink` kopyası | `/console/ai-services/reports` |

**Ek alanlar:** `generation_type` (ONE_TIME / PERIODICAL), `frequency` (WEEKLY / MONTHLY / QUARTERLY), `report_kind` (STANDARD / AI_ADVANCED), `report_source` (USER / SYSTEM), `widget_ids`, `progress_pct`, `completed_widgets`, `total_widgets`.

**Önemli ayrım:**

| Kavram | Anlam |
|--------|-------|
| `generation_type: ONE_TIME` | **Ad hoc** — tek seferlik, kullanıcı tarih aralığı seçer |
| `generation_type: PERIODICAL` | **Periyodik** — sistem belirli sıklıkta otomatik üretir |
| `report_kind: STANDARD` | Klasik dashboard PDF |
| `report_kind: AI_ADVANCED` | GenAI içerikli gelişmiş PDF (quota kontrolü yapılır) |

---

### 12.1 Merkez UI: Reports & Downloads

**Rota:** `/console/report`  
**Bileşen:** ReportsDownloads

| URL parametresi | Sekme | İçerik |
|-----------------|-------|--------|
| `?page=report` (varsayılan) | **Reports** | PDF rapor işleri (type 1, 3) |
| `?page=download` | **Downloads** | Veri export'ları (type 2) |

#### Reports sekmesi — listeleme

- **API:** `POST report/reports/list` — `{ user_id, sort, keywords? }`
- **Görünen rapor tipleri:**
  - **Dashboard Report** (type=1, org geneli)
  - **My Workspace** (type=3, `report_source=USER`, mevcut kullanıcı)
  - **Auto Report** (type=3, `report_source=SYSTEM`, org admin worker job'ları)
- **type=4** (yeni aylık AI PDF) bu listede **yer almaz** → AI Services UI kullanılır

#### Downloads sekmesi — listeleme

- **API:** `POST report/downloads/list`
- Dashboard'dan indirilen CSV/XLSX export satırları (type=2)
- type=3 workspace raporları bu sekmede **görünmez**

#### Ortak satır aksiyonları

| Aksiyon | Koşul | Davranış |
|---------|-------|----------|
| **Download** | Status = Ready | `window.open(ReportLink)` veya `CSVLink` |
| **Rename** | Reports | `POST report/rename` |
| **Delete** | Her iki sekme | `POST report/delete` |
| **Retry** | My Workspace Failed | `POST report/welcome/exports/{id}/retry` |
| **Details** | My Workspace | `GET report/welcome/exports/{id}/widgets` — widget listesi modal |
| **Open in Workspace** | Auto Report Ready | `/console/my-workspace?group_id={welcome_group_id}` |

#### Otomatik yenileme (polling)

My Workspace veya Auto Report satırı `Pending` / `Processing` ise Reports sekmesinde **5 saniyede bir** sessiz liste yenilemesi yapılır. Progress bar: `progress_pct`, `completed_widgets / total_widgets`.

#### Yeni rapor oluşturma

**"+ New Report"** → `NewReport.js` sihirbazı açılır (dashboard PDF). Legacy modal UI kodda var ama **kullanılmıyor**.

---

### 12.2 Ad hoc (tek seferlik) Dashboard PDF raporları

**Türkçe:** Ad hoc rapor = **One-time report**  
**UI:** `/console/report` → New Report → Generation Type: **One-time**

#### Sihirbaz adımları (ONE_TIME)

| # | Adım | Zorunlu | Açıklama |
|---|------|---------|----------|
| 1 | Generation Type | ✓ | **One-time** seç |
| 2 | Report Name | ✓ | Rapor adı |
| 3 | Report Type | ✓ | **Standard report** veya **Advanced AI report** |
| 4 | Group + Dashboards | ✓ | Marka grubu, bir veya birden fazla dashboard |
| 5 | Date Period | ○ | Tarih aralığı (varsayılan: son 7 gün) |
| 6 | Pivots | ○ | Pivot kolonu + değerleri (dashboard pivot varsa) |
| 7 | Report Scope | ✓ | Full-report veya Selected topics |
| 8 | Recipient emails | ○ | PDF alıcı e-postaları |

**AI Advanced seçilirse:** Oluşturmadan önce `subscriptions/check_quota_for_target_params` ile AI quota kontrolü yapılır.

#### API payload (ONE_TIME)

```json
{
  "generation_type": "ONE_TIME",
  "report_name": "Q1 Delivery Analysis",
  "report_kind": "STANDARD",
  "group_id": 64,
  "dashboard_ids": ["3057", "3058"],
  "since": "2025-01-01",
  "until": "2025-01-31",
  "pivot_key": "Region",
  "pivot_values": ["US", "EU"],
  "generate_individual_reports": true,
  "topic_ids": ["topic-uuid-1"],
  "recipient_emails": ["cx@company.com"]
}
```

- `type` gönderilmez → API varsayılan **type=1** (Dashboard Report)
- Pivot opsiyonel; `generate_individual_reports: true` → her pivot değeri için ayrı PDF
- `topic_ids` yalnızca scope = Selected topics ise gönderilir

#### Oluşturma sonrası

1. Başarı bildirimi
2. `/console/report` Reports sekmesinde yeni satır — Status: **Pending**
3. Worker (`ad_hoc_report` pipeline) işler → **Processing** → **Ready**
4. Ready olunca **Download** → `ReportLink` PDF

#### Duplicate kontrolü

Aynı kullanıcı + `group_id` + type=1 + tüm alanlar eşleşirse → `REPORT_ALREADY_EXISTS` hatası.

---

### 12.3 Periyodik Dashboard PDF raporları

**UI:** New Report → Generation Type: **Periodical**

#### Sihirbaz adımları (PERIODICAL)

ONE_TIME ile aynı, ancak **Date Period** yerine **Frequency** adımı:

| Frequency | İlk çalışmada analiz edilen dönem (API otomatik hesaplar) |
|-----------|-----------------------------------------------------------|
| **WEEKLY** | Geçen hafta (Pazartesi–Pazar) |
| **MONTHLY** | Geçen takvim ayı |
| **QUARTERLY** | Geçen çeyrek |

#### API payload (PERIODICAL)

```json
{
  "generation_type": "PERIODICAL",
  "frequency": "MONTHLY",
  "report_name": "Monthly Regional Report",
  "report_kind": "STANDARD",
  "group_id": 64,
  "dashboard_ids": ["3057"],
  "since": "2025-01-01",
  "until": "2025-01-31",
  "pivot_key": "Region",
  "pivot_values": ["US", "EU", "ASIA"],
  "generate_individual_reports": true
}
```

- `frequency` zorunlu: `WEEKLY` | `MONTHLY` | `QUARTERLY`
- Sistem belirtilen sıklıkta otomatik yeni PDF üretir
- Pivot + `generate_individual_reports` → her bölge/segment için ayrı periyodik PDF

#### Periyodik Welcome (My Workspace) PDF — API only pattern

Workspace grupları için periyodik PDF de tanımlanabilir:

```json
{
  "report_name": "Weekly Welcome Report",
  "type": 3,
  "generation_type": "PERIODICAL",
  "frequency": "WEEKLY",
  "report_kind": "STANDARD",
  "pivot_key": "Accompany",
  "pivot_values": ["FAMILY", "COUPLE"]
}
```

`group_id` gerekmez (type=3). UI'da bu akış doğrudan NewReport'tan değil; API veya otomasyon ile kullanılır.

---

### 12.4 Dashboard veri export'ları (Downloads sekmesi)

**type=2** — PDF değil, **CSV/XLSX** dosya indirmeleri.

#### Tetikleyici noktalar (Dashboard içinden)

| Kullanıcı aksiyonu | API | Sonuç |
|--------------------|-----|-------|
| Dashboard header "Download file" | `POST dashboards/file_download` | Anında Ready, `CSVLink` |
| Filtrelenmiş review export | `POST dashboards/v2/get_download_link` | Progress → Ready |
| Custom topics unmatched / volumetric | `dashboards/v2/custom_topics/download_*` | Export satırı |
| Root cause download | `dashboards/root-cause/download` | Export satırı |
| Topic sequence download | `dashboards/topic/sequence/download` | Export satırı |

#### Kullanıcı akışı

1. Dashboard'da export aksiyonu
2. Bildirim: "Exports sayfasına gidin"
3. `/console/report?page=download`
4. Satır Status: `Ready` veya `InProgress` → **Download** → `CSVLink` (presigned URL)
5. Silme: `POST report/delete`

**Not:** Export satırları Reports sekmesinde **görünmez**; yalnızca Downloads sekmesinde.

---

### 12.5 My Workspace PDF export (ad hoc)

**Tek seferlik** workspace PDF — periyodik değil (kullanıcı tarih aralığı seçer).

#### Kullanıcı akışı

1. `/console/my-workspace` aç
2. **Generate PDF report** (PDF export modal)
3. Dahil edilecek **metric group(s)** seç (varsayılan: tüm gruplar)
4. Onayla
5. `POST report/create`:

```json
{
  "report_name": "Workspace PDF — Weekly Performance KPIs · AI summaries",
  "type": 3,
  "report_type": 3,
  "welcome_group_ids": [101, 102],
  "since": "2025-04-01",
  "until": "2025-04-30"
}
```

- `since` / `until`: URL parametrelerinden veya dashboard KPI tarih helper'ından (`getWelcomeKpiSinceUntil`)
- Rapor adı otomatik: base + seçili grup isimleri

6. Başarı toast + link → `/console/report?page=report`
7. Satır tipi: **My Workspace**, widget progress bar ile
8. Ready → Download PDF

#### API davranışı

- `welcome_group_ids` yoksa → kullanıcının **tüm** workspace gruplarındaki widget'lar dahil
- Aynı kullanıcı için zaten **Pending** type=3 varsa → bloklanır
- `widget_ids` kaydedilir; mastermind / `generate_dynamic_widget_report` pipeline PDF üretir

#### Yardımcı endpoint'ler

| Endpoint | Amaç |
|----------|------|
| `GET report/welcome/exports` | Son 20 export |
| `GET report/welcome/exports/{id}/widgets` | Detay modal widget listesi |
| `POST report/welcome/exports/{id}/retry` | Failed → Pending reset |

#### My Workspace vs Monthly AI

| | My Workspace PDF (type=3 USER) | Monthly AI Insights |
|--|----------------------------------|---------------------|
| Tetikleyici | Kullanıcı manuel | Scheduler / Run Now |
| Tarih | Kullanıcı seçer | Sistem (önceki ay) |
| Grup | Mevcut workspace grupları | Otomatik `is_auto_report` grup |
| Liste | `/console/report` | `/console/ai-services/reports` |

---

### 12.6 Monthly AI Insights (otomatik periyodik GenAI raporları)

**Birincil modern aylık rapor sistemi.** Dashboard NewReport PERIODICAL'dan **farklıdır**.

| UI | Rota |
|----|------|
| Monthly Report Settings | `/console/ai-services/auto-refresh` |
| Monthly AI Insights listesi | `/console/ai-services/reports` |
| Rapor detay + düzenleme | `/console/ai-services/reports/:reportId` |

#### Ayarlar akışı

1. Brand group + dashboard seç (My Workspace brand widget ile aynı)
2. Pivot alanı + vendor/pivot değerleri (her vendor = ayrı rapor satırı)
3. Metrikler: GenAI {20,21,23,25} + opsiyonel KPI grafikleri
4. Konular (varsa en az 1 zorunlu)
5. Zamanlama: ayın 1–28 veya son gün + saat (timezone → UTC)
6. Aktif / Paused
7. Pay-per-use overage (300 kredi/ay üzeri token faturalama)
8. Save Settings → `POST welcome/ai-services/config`

#### Vendor başına ayrı rapor

Her seçilen pivot değeri (ör. vendor/marka) için **ayrı `AiReport` satırı** oluşur. Ay listesinde her biri ayrı kart/satır olarak görünür.

#### Zamanlama vs analiz dönemi

| Zamanlama | Analiz edilen feedback |
|-----------|------------------------|
| Ayın 1. günü (varsayılan) | **Önceki takvim ayı** |
| Ayın son günü (day 31) | **Mevcut ay** |

Zamanlama günü ≠ analiz edilen ay (kullanıcıya açıkça anlatılmalı).

#### AI kredisi

`GenAI metrik sayısı (20,21,23,25) × vendor sayısı` = aylık kredi. KPI grafik metrikleri kredi tüketmez. Quota yetersiz + pay-per-use kapalı → Run Now bloklanır.

#### Rapor lifecycle

```
processing → provisioned → finalizing → ready | failed
```

| UI status | Anlam |
|-----------|-------|
| Queued | Kuyrukta |
| Processing | GenAI widget job'ları çalışıyor |
| Preparing (provisioned) | Otomatik workspace grubu + widget'lar oluşturuluyor |
| Generating PDF (finalizing) | type=4 ReportPdf PDF üretiliyor |
| Ready | Görüntüle + indir |
| Failed | Hata |

#### Worker pipeline

```
Scheduler / Run Now
  → AiReport (processing) per vendor
  → provision-workspace-for-report (WelcomeWidgetGroup + widgets + jobs)
  → genai_widget_processor (widget insights MongoDB)
  → finalize-auto-report → ReportPdf type=4 Pending
  → PDF worker → ReportLink
  → mark-auto-report-ready → AiReport.pdf_url, status=ready
```

#### PDF indirme yeri

- **Birincil:** `/console/ai-services/reports` → `pdf_url` ile indir
- Detay sayfasında **Regenerate PDF** → widget düzenlemelerinden sonra

#### Rapor detayında düzenleme

- Root cause / insight satırları düzenlenebilir (`PATCH widget-insight-items`)
- Root cause silinebilir
- Düzenleme sonrası **Regenerate PDF** zorunlu: `POST welcome/ai-services/reports/{id}/regenerate-pdf`

#### Rapor silme (cascade)

`DELETE welcome/ai-services/reports/{id}`:
1. MongoDB widget-insights
2. Welcome widget'lar + job'lar
3. Otomatik workspace grubu
4. ReportPdf type=4
5. AiReport satırı

#### Manuel tetikleme

- `POST welcome/ai-services/run-now` — mevcut ay için
- Mevcut ay raporu varsa önce silinmeli
- UI: i18n'de "Generate Now" tanımlı; settings sayfasında görünürlük deployment'a bağlı

#### GenAI tab yapısı (rapor detay)

Metrik 20, 21, 23, 25 için:
- **General** sekmesi (ay/genel özet)
- Seçilen her konu kategorisi için ayrı sekme

#### Özel tarih aralığı

Aylık raporda tarih seçeneği **yok**. Özel dönem → **My Workspace** widget'ları + My Workspace PDF export.

---

### 12.7 Auto Report (legacy type=3 SYSTEM)

Eski otomatik workspace PDF worker'ının ürettiği satırlar. Reports sekmesinde **Auto Report** etiketiyle görünür.

- `report_source = SYSTEM`
- Org admin kullanıcısına bağlı worker job
- Ready olunca PDF indir + **Open in Workspace** deep link
- Yeni Monthly AI Insights **type=4** kullanır; type=3 SYSTEM satırları legacy kurulumlarda kalabilir

---

### 12.8 Durum (status) sözlüğü

#### ReportPdf (Reports + Downloads)

| Status | Reports (PDF) | Downloads (CSV) |
|--------|---------------|-----------------|
| Pending | Kuyrukta | — |
| Processing | Üretiliyor | — |
| Progress | — | Export işleniyor |
| Ready | İndirilebilir | İndirilebilir |
| Error / Expired | Başarısız / süresi dolmuş | Başarısız |

My Workspace (type=3): ek olarak `progress_pct`, `completed_widgets`, `total_widgets`.

#### AiReport (Monthly AI)

`processing` → `provisioned` → `finalizing` → `ready` | `failed`

---

### 12.9 Karşılaştırma tablosu — hangi raporu ne zaman?

| İhtiyaç | Kullanılacak akış | Periyodik mi? | İndirme yeri |
|---------|-------------------|---------------|--------------|
| Dashboard PDF, tek seferlik tarih | New Report → One-time | Hayır (ad hoc) | `/console/report` Reports |
| Dashboard PDF, haftalık/aylık otomatik | New Report → Periodical | Evet | `/console/report` Reports |
| Workspace widget PDF, istediğim tarih | My Workspace → Generate PDF | Hayır (ad hoc) | `/console/report` Reports |
| Aylık GenAI insight (vendor bazlı) | AI Services → Auto-refresh | Evet (aylık) | `/console/ai-services/reports` |
| Dashboard review CSV/XLSX | Dashboard export aksiyonu | Hayır | `/console/report` Downloads |
| Özel tarih GenAI analizi | My Workspace widget + tarih | Hayır | Widget UI (PDF opsiyonel) |

---

### 12.10 API endpoint özeti

#### Report PDF (reportpdf blueprint)

| Endpoint | Method | Amaç |
|----------|--------|------|
| `report/create` | POST | Dashboard PDF (type=1), Workspace PDF (type=3) |
| `report/reports/list` | POST | Reports sekmesi listesi |
| `report/downloads/list` | POST | Downloads sekmesi listesi |
| `report/rename` | POST | Rapor adı değiştir |
| `report/delete` | POST | Rapor/export sil |
| `report/pivots` | GET/POST | NewReport pivot kolonları |
| `report/welcome/exports` | GET | Son workspace export'ları |
| `report/welcome/exports/{id}/widgets` | GET | Workspace PDF widget detayı |
| `report/welcome/exports/{id}/retry` | POST | Failed workspace PDF retry |

#### AI Services (welcome blueprint)

| Endpoint | Method | Amaç |
|----------|--------|------|
| `welcome/ai-services/config` | GET/POST | Aylık rapor ayarları |
| `welcome/ai-services/pivot-options` | GET | Pivot vendor listesi |
| `welcome/ai-services/reports` | GET | AiReport listesi (filtre, sayfalama) |
| `welcome/ai-services/reports/{id}` | GET/DELETE | Detay / cascade sil |
| `welcome/ai-services/run-now` | POST | Manuel aylık tetikleme |
| `welcome/ai-services/reports/{id}/regenerate-pdf` | POST | PDF yeniden üret |
| `welcome/ai-services/reports/{id}/widget-insight-items` | PATCH | Insight düzenle |
| `welcome/ai-services/reports/{id}/widget-insight-items/delete` | POST | Root cause sil |

#### Dashboard export

| Endpoint | Amaç |
|----------|------|
| `dashboards/file_download` | Hızlı dosya indirme |
| `dashboards/v2/get_download_link` | Filtrelenmiş review export |
| `dashboards/v2/custom_topics/download_*` | Custom topic export |
| `dashboards/root-cause/download` | Root cause export |

---

### 12.11 Legacy UI notu

`/console/reportt` — eski report listesi (`report/list`, farklı create payload). Modern akış **`/console/report`** + NewReport sihirbazıdır.

---


## 13. Dashboard ve Platform Kullanımı

### 13.1 Dashboard oluşturma

**Rota:** All Dashboards → New Dashboard

1. Platform seçin (veri kaynağı)
2. Dil, konu sayısı, zaman aralığı belirleyin
3. Pivony **27 dilde** dashboard üretebilir

**Video:** https://www.youtube.com/watch?v=3N7T8eDFcfM

### 13.2 Dashboard keşfi

Dashboard dört bölümden oluşur:

1. **Data Overview** — istatistikler, metin arama, tarih filtresi
2. **AI Topics** — otomatik konu keşfi
3. **Custom Topics** — kullanıcı tanımlı konular
4. **Insight Notes** — yapışkan notlar, kalıcı gözlemler

**Data Overview filtreleri:**
- Filtered Data (review sayısı)
- Hot Terms (1–4 keyword pair)
- Top Topics (kategori kesişim/birleşim)
- Platforms (doughnut, interaktif)
- Intent Analysis

Dashboard **dynamic** yapılabilir (güncel sonuçlar). **Share Dashboard** ile link paylaşımı.

### 13.3 My Dashboards

Tüm dashboard'lara sol üst "All Dashboards" bölümünden erişilir.

### 13.4 Alerts (KPI uyarıları)

Gerçek zamanlı KPI takibi. Anormal kayma → e-posta/Slack bildirimi. `/console/alerts` veya Welcome sayfasından erişim.

### 13.5 Saved Search, Topic Library, Custom Topics

- **Saved Search** — kayıtlı filtre kombinasyonları
- **Topic Library** — konu kütüphanesi
- **Custom Topics Creation / Custom Topic Follow** — özel konu oluşturma ve takip

### 13.6 Industry Analysis, Advanced Reporting, KPI View

- **Industry Analysis** — sektör karşılaştırması
- **Advanced Reporting** — gelişmiş raporlama
- **KPI View** — KPI odaklı görünüm
- **Dashboard Journey** — müşteri yolculuğu haritası
- **Dashboard Download** — dashboard PDF export

### 13.7 AskPivony (platform içi)

Welcome footer ve yardım menüsünden erişilen AI asistan. Pivony Advisor (`/console/advisor`) ile ilişkili; Advisor tam sayfa deneyim sunar.

---

## 14. Entegrasyonlar ve Görev Yönetimi

### 14.1 Veri kaynağı entegrasyonları (Owned Data)

| Platform | Tür |
|----------|-----|
| Zendesk Tickets | Destek ticketları |
| Zendesk Live Chat | Canlı chat |
| Facebook & Instagram | Sosyal medya |
| Facebook & Instagram Ad | Reklam yorumları |
| Twitter / X Professional | Sosyal medya |
| Instagram Hashtag Search | Hashtag arama |
| Mobile App Stores | App Store / Google Play |
| E-commerce websites | E-ticaret yorumları |
| Email marketing | E-posta geri bildirimi |
| Survey Platforms | Anket platformları |
| SikayetVar | Şikayet platformu |
| Custom File Upload | CSV/Excel |
| Jira, Trello, ClickUp | Görev yönetimi (aksiyon) |

**Zendesk Tickets kurulumu:** subdomain, ticket email, API token gerekir.

### 14.2 Görev yönetimi entegrasyonları

| Araç | Kullanım |
|------|----------|
| Jira | Insight'tan otomatik ticket |
| Trello | Görev kartı oluşturma |
| ClickUp | Görev atama |

### 14.3 Bildirim entegrasyonları

- **Slack** — alert ve insight bildirimleri
- **On-platform notifications** — platform içi bildirim
- **Get Notified** — özelleştirilebilir bildirim kuralları

### 14.4 Kullanıcı davet etme

**Admin gerekli.**

1. Settings → Teams → New Team
2. Team adı → Add
3. Invite users → e-posta + erişim seviyesi
   - **Read-only:** sadece görüntüleme
   - **Read & write:** insight oluşturma
4. Send invites → pending → kullanıcı e-postadan aktivasyon
5. Read/write için admin **team quota** günceller (dashboard sayısı)

### 14.5 Settings sayfası

- Dil, timezone, tema
- Bildirim tercihleri
- Entegrasyon hesapları (Instagram, Twitter, Facebook, Zendesk, vb.)

---

## 15. Planlar ve Özellik Matrisi

### 15.1 Plan karşılaştırma (özet)

| Özellik | Free | VoC | Market | Full | Capture Pro | Enterprise |
|---------|------|-----|--------|------|-------------|------------|
| Root-cause analysis | — | ✓ | — | ✓ | ✓ | ✓ |
| Sentiment analysis | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| KPI monitoring & alerts | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| PII masking | — | ✓ | — | ✓ | ✓ | ✓ |
| Jira / Slack / Asana | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Native Turkish NLU | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Digital VoC Score | — | — | ✓ | ✓ | — | ✓ |
| Competitor benchmarking | — | — | ✓ | ✓ | — | ✓ |
| LiveBoard | — | — | ✓ | ✓ | — | ✓ |
| 360° Unified Dashboard | — | — | — | ✓ | — | ✓ |
| Agentic AI | — | — | — | ✓ | — | ✓ |
| Executive Briefing | — | — | — | ✓ | — | ✓ |
| Dedicated CS manager | — | — | — | ✓ | — | ✓ |
| Pivony Advisor kapsamı | — | VoC | Market | Full | — | Full+ |
| SSO / SAML / RBAC | — | — | — | — | — | ✓ |

### 15.2 Rakip karşılaştırma (VS hub)

pivony.com/vs — Qualtrics, Medallia, Artiwise, Pisano, AlternaCX, ChatGPT, Claude, Gemini

**Ortak Pivony farkları:**
- Native Turkish NLU
- Cross-brand competitor benchmarking
- Saniyeler içinde kök neden
- Agentic AI aksiyon alır
- 48 saat canlı
- VoC + Market tek platformda

---

## 16. Güvenlik, İzinler ve Destek

### 16.1 Güvenlik

- AES-256 şifreleme
- GDPR & KVKK uyumu
- **Müşteri verisiyle AI eğitimi yapılmaz**
- ISO 27001 altyapı
- PII masking (VoC, Full, Capture, Enterprise)
- Enterprise: SSO/SAML, RBAC, on-prem/VPC

### 16.2 Destek kaynakları

| Kaynak | URL |
|--------|-----|
| Learning Center (kurslar) | https://learning.pivony.com/ |
| Knowledge Center (Notion — eski) | https://pivony.notion.site/... |
| Tutorials | https://www.pivony.com/tutorials |
| Blogs | https://www.pivony.com/blogs |
| Help Center | https://www.pivony.com/knowledge-center |
| Destek e-posta | support@pivony.com |

**Not:** Bu master kılavuz Knowledge Center'ın güncel yerine geçer.

### 16.3 Platform rotaları — hızlı referans

| Sayfa | Rota |
|-------|------|
| My Workspace | `/console/my-workspace` |
| Pivony Advisor | `/console/advisor` |
| Monthly Report Settings | `/console/ai-services/auto-refresh` |
| Monthly AI Insights | `/console/ai-services/reports` |
| Reports & Downloads | `/console/report` |
| All Dashboards | Sidebar → Dashboards |
| Settings | `/console/settings` |
| Alerts | Alerts bölümü |

---

## 17. Advisor Playbook'ları — Adım Adım Kullanım (SSS)

Bu bölüm Advisor'ın en sık aldığı sorulara **platform rotaları ve adım adım** yanıt verir. Tam metin ayrıca `PIVONY_ADVISOR_PLAYBOOKS.md` dosyasında chunk-friendly formatta tutulur.

### 17.1 Dış veriyi nasıl analiz ederim? (Market Intelligence)

**Plan:** Market Intelligence veya Full Intelligence

1. `/settings/plan` — plan kontrolü
2. `/settings/integrations` — Meta/social OAuth (opsiyonel)
3. `/console/myDashboards` → **New Dashboard** → `/console/source` — **public platform** (App Store, Play, Instagram, X, vb.)
4. `/console/journey/:id` — dashboard Ready olana kadar bekle
5. `/console/industryTopics` — Start → brand group → dashboards → categories → **Generate Charts**
6. `/console/my-workspace` → **Competitor Metrics** widget (brand/category/time/VoC Score)
7. DES için Brand Metric **18** (Digital Experience Score)
8. `/console/global_executive` → **Present** (TV sunumu)
9. Opsiyonel: `/console/ai-services/auto-refresh` — aylık otomatik rapor

**Entegrasyon gerekmez** for App Store, social, Reddit — sistem otomatik toplar.

### 17.2 İç veriyi nasıl analiz ederim? (Voice of Customer)

**Plan:** VoC veya Full Intelligence

1. `/settings/integrations` — Zendesk, CSV, CRM kaynakları bağla
2. `/console/source` — **owned data**: CSV (platform 3), Zendesk Tickets (7), Live Chat (8)
3. `/console/DashboardData/:id` — Overview, filtreler, Hot Terms, Top Topics
4. `/console/top-problems/:id` — **AI Insights** / root cause generate
5. `/console/customTopics/:id` veya `/console/topicLibrary` — custom topics
6. `/console/combined-view/:id` — Key Driver Analysis haritası
7. `/console/alerts` — KPI alert
8. `/console/my-workspace` — Brand Metrics + GenAI (20,21,23,25)
9. `/console/advisor` — doğal dilde sor

### 17.3 Full Intelligence — ikisi birlikte

VoC playbook (17.2) + Market playbook (17.1) + aynı My Workspace'te brand + competitive widget'lar + Advisor Full kapsamı.

### 17.4 Diğer sık sorular (özet)

| Soru | Kısa yanıt |
|------|------------|
| My Workspace widget? | `/console/my-workspace` → Add Metric Wizard → `welcome/widget/add` |
| Ad hoc PDF rapor? | `/console/report` → New Report → One-time |
| Periyodik PDF? | New Report → Periodical → WEEKLY/MONTHLY/QUARTERLY |
| Aylık AI Insights? | `/console/ai-services/auto-refresh` → reports list |
| CSV export? | Dashboard export → `/console/report?page=download` |
| Workspace PDF? | My Workspace → Generate PDF → `/console/report` |
| Kullanıcı davet? | `/settings/teams` + `/settings/team/invite` |
| Zendesk? | `/settings/integrations` → subdomain + token → dashboard wizard |

Detaylı adımlar: `docs/PIVONY_ADVISOR_PLAYBOOKS.md`

---

## Ek: Sektör çözümleri

pivony.com/solutions altında:

- Retail & Fashion
- E-commerce
- Telecom
- Finance & Insurance
- Tourism & Hospitality

---

## Ek: Referans müşteriler

Vodafone Turkey, Samsung, Allianz, Karaca, Papara, Akbank, Millenicom, Etstur

---

*Bu doküman Pivony Advisor RAG koleksiyonu (`pivony_customer_knowledge`) için birincil eğitim kaynağıdır. Güncelleme: ürün veya platform değişikliklerinde pivony-website locale dosyaları ve pivony-api-dev/api/welcome.py referans alınmalıdır.*
