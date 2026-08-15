export type Lang = "tr" | "en";

const en = {
  "app.name": "Castle Benchmark",
  "app.subtitle": "Agent operations · protocol v1.1",
  "app.title": "Castle Benchmark · Agent Operations",

  "language.switch": "Language",

  "connection.localReady": "Local core ready",
  "connection.connected": "Benchmark service connected",
  "connection.unreachable": "Service unreachable",

  "matchState.idle": "Idle — create a lobby to begin.",
  "matchState.waiting": "Waiting for agents — assign controllers, then start.",
  "matchState.running": "Running — follow the map or take over a colony.",
  "matchState.finished": "Finished — review the report or load a replay.",

  "setup.title": "Set up the operation",
  "setup.subtitle": "The lobby and the running match share the same secure shell.",
  "setup.scenario": "Scenario",
  "setup.seed": "Seed",
  "setup.colonies": "Colonies",
  "setup.deadline": "Turn length (seconds)",
  "setup.orchestratorLabel": "Orchestrator capability",
  "setup.orchestratorHelp": "The server's orchestrator secret (CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN). Used only for the create-session request; cleared and never stored after submit.",
  "setup.createButton": "Create agent lobby",
  "setup.quickPlay": "Quick play, single colony",
  "setup.replayImport": "Replay snapshots.jsonl",

  "replay.prev": "Previous replay turn",
  "replay.scrub": "Replay turn",
  "replay.next": "Next replay turn",

  "map.region": "Game field",
  "map.unknownBiome": "UNKNOWN BIOME",
  "map.fogActive": "FOG: ACTIVE",
  "map.spectator": "SPECTATOR · WHOLE WORLD",
  "map.replay": "REPLAY · {index}/{total}",
  "map.turnLabel": "TURN {turn} · {colony}",
  "map.canvasLabel": "Isometric colony map",
  "map.placeholder": "Waiting for the map core",
  "map.viewControls": "Map view",
  "map.panUp": "Pan map up",
  "map.panLeft": "Pan map left",
  "map.reset": "Reset map view",
  "map.panRight": "Pan map right",
  "map.panDown": "Pan map down",
  "map.zoomOut": "Zoom map out",
  "map.zoomIn": "Zoom map in",
  "map.keyResource": "Resource",
  "map.keyColony": "Colony",

  "intel.title": "Agent inspector",
  "intel.subtitle": "Decision, observation and cost attribution follow a single selection.",

  "ledger.title": "Colony observation",
  "ledger.empty": "No active colony yet.",
  "ledger.population": "Population",
  "ledger.populationValue": "{population} / {housing} housing",

  "selection.title": "Selected cell",
  "selection.hint": "Select a cell on the map.",

  "humanControls.title": "Human control",

  "actions.wait": "Wait",
  "actions.gather": "Gather",
  "actions.build": "Build",
  "actions.policy": "Apply policy",
  "actions.diplomacy": "Make contact",
  "actions.trade": "Propose trade",
  "actions.raid": "Raid",

  "buildChoice.label": "Structure",

  "structures.headquarters": "Headquarters",
  "structures.house": "House",
  "structures.well": "Well",
  "structures.farm": "Farm",
  "structures.warehouse": "Warehouse",
  "structures.market": "Market",
  "structures.lumberCamp": "Lumber camp",
  "structures.quarry": "Quarry",
  "structures.mine": "Mine",
  "structures.workshop": "Workshop",
  "structures.clinic": "Clinic",
  "structures.barracks": "Barracks",
  "structures.watchtower": "Watchtower",
  "structures.wall": "Wall",
  "structures.gate": "Gate",

  "metrics.title": "Benchmark metrics",
  "metrics.aria": "Benchmark metric comparison",
  "metrics.empty": "Run report not ready yet.",
  "metrics.empty2": "Raw run report not available.",
  "metrics.generation": "generation {n}",
  "metrics.provenance.simulationRaw": "Measured by the simulation itself.",
  "metrics.provenance.serverMeasured": "Measured by the server.",
  "metrics.provenance.adapterReported": "Reported by the agent's own adapter (self-reported).",
  "metrics.provenance.unavailable": "Not computed — the engine reports no raw axis for this.",
  "metrics.survival": "Survival",
  "metrics.growth": "Growth · population trajectory",
  "metrics.prosperity": "Prosperity · raw resources",
  "metrics.diplomacy": "Diplomacy · trade / aggression",
  "metrics.resilience": "Resilience",
  "metrics.actionValidity": "Action validity · invalid actions",
  "metrics.timeouts": "Timeouts / reconnects",
  "metrics.mcpCalls": "MCP calls",
  "metrics.tokens": "Tokens / cumulative latency",

  "metrics.name.inputTokens": "Input tokens",
  "metrics.name.outputTokens": "Output tokens",
  "metrics.name.latency": "Latency",
  "metrics.name.mcpCalls": "MCP calls",
  "metrics.name.timeouts": "Timeouts",
  "metrics.name.reconnects": "Reconnects",
  "metrics.name.turns": "Turns",
  "metrics.name.population": "Population",
  "metrics.name.initialPopulation": "Initial population",
  "metrics.name.peakPopulation": "Peak population",
  "metrics.name.housing": "Housing",
  "metrics.name.trade": "Trade",
  "metrics.name.aggression": "Aggression",
  "metrics.name.invalidActions": "Invalid actions",

  "events.title": "Local notifications",
  "events.clear": "Clear",
  "events.empty": "The match has not started.",

  "footer.waiting": "Waiting for a sanitized operations snapshot.",
  "footer.note": "Deterministic · replayable · seed-controlled",

  "roster.title": "Agent roster",
  "roster.empty": "No sanitized controller snapshot yet.",
  "roster.baseline": "Baseline",
  "roster.human": "Human operator",
  "roster.external": "External agent",
  "roster.latencyAria": "Adapter-reported cumulative latency {value}",

  "state.unassigned": "Unassigned",
  "state.ready": "Ready",
  "state.pairing": "Pairing",
  "state.connected": "Connected",
  "state.thinking": "Thinking",
  "state.submitted": "Submitted",
  "state.timedOut": "Timed out",
  "state.disconnected": "Disconnected",
  "state.takenOver": "Taken over",

  "event.turnOpened": "Turn opened",
  "event.controllerSubmitted": "Decision submitted",
  "event.turnResolved": "Turn resolved",
  "event.metricUpdated": "Metrics updated",
  "event.presenceChanged": "Presence changed",
  "event.controllerConnected": "Controller connected",
  "event.controllerDisconnected": "Controller disconnected",
  "event.controllerReady": "Controller ready",
  "event.controllerTimedOut": "Controller timed out",
  "event.controllerReplaced": "Controller replaced",
  "event.controllerClaimed": "Controller claimed",
  "event.heartbeatRejected": "Heartbeat rejected",
  "event.pairingRejected": "Pairing rejected",
  "event.matchCompleted": "Match completed",

  "tab.decision": "Decision",
  "tab.resources": "Resources",
  "tab.diplomacy": "Diplomacy",
  "tab.cost": "Cost",

  "timeline.title": "Service log",
  "timeline.aria": "Ordered service events",
  "timeline.tenure": "Tenure",
  "timeline.turn": "Turn {turn}",
  "timeline.empty": "No ordered service events yet.",

  "decisions.title": "Decision feed",
  "decisions.aria": "Submitted actions as they resolve",
  "decisions.accepted": "accepted",
  "decisions.rejected": "rejected · {detail}",
  "decisions.empty": "No resolved decisions yet.",

  "inspector.none": "No agent selected",
  "inspector.turn": "Turn",
  "inspector.state": "State",
  "inspector.controller": "Controller",
  "inspector.source": "Source",
  "inspector.sourceValue": "Authoritative colony observation",
  "inspector.detail": "Detail",
  "inspector.detailValue": "Select a visible world cell or load a replay frame.",
  "inspector.rawAxes": "Raw axes",
  "inspector.rawAxesValue": "Trade and aggression",
  "inspector.composite": "Composite score",
  "inspector.compositeValue": "Unavailable — not inferred",
  "inspector.provider": "Provider",
  "inspector.model": "Model",
  "inspector.latency": "Latency",
  "inspector.attribution": "Attribution",
  "inspector.attributionValue": "Reported by the agent unless marked server-measured",

  "lobby.title": "Agent lobby · {scenario}",
  "lobby.controller": "Controller",
  "lobby.baseline": "Baseline",
  "lobby.apply": "Apply assignment",
  "lobby.pair": "Generate pairing code",
  "lobby.takeOver": "Take over as human",
  "lobby.baselineFallback": "Use baseline fallback",
  "lobby.rotateExternal": "Rotate external pairing",
  "lobby.colony": "Colony {id}",
  "lobby.fallbackAria": "Fallback or replacement for {id}",
  "lobby.allReady": "All slots ready — start explicitly when prepared",
  "lobby.oneWaiting": "{count} slot waiting",
  "lobby.manyWaiting": "{count} slots waiting",
  "lobby.start": "Start match",
  "lobby.running": "Match running",
  "lobby.refresh": "Refresh lobby status",
  "lobby.humanReady": "Human controller ready",
  "lobby.baselineReady": "Baseline ready — {kind}",
  "lobby.disconnected": "Disconnected — choose a fallback or pair again",
  "lobby.externalReady": "External agent ready",
  "lobby.claimed": "Claimed — waiting for ready heartbeat",
  "lobby.expired": "Pairing expired",
  "lobby.pairingActive": "Pairing code active",
  "lobby.unassigned": "External agent unassigned",
  "lobby.human": "Human",
  "lobby.deterministicBaseline": "Deterministic baseline",
  "lobby.externalMCP": "External MCP agent",
  "lobby.policyOneHuman": "This browser can manage only one human slot",
  "lobby.startNotReady": "All lobby slots must be ready before starting",
  "lobby.clipboardUnavailable": "Clipboard access is unavailable",
  "lobby.noSession": "No active lobby session",

  "pairing.title": "Pair external agent · {colony}",
  "pairing.expires": "Expires in {duration}",
  "pairing.provider": "Agent provider",
  "pairing.copyCode": "Copy code",
  "pairing.copyEndpoint": "Copy endpoint",
  "pairing.copyConfig": "Copy provider instructions",
  "pairing.aria": "Pairing grant for {colony}",
  "pairing.step1": "Connect this agent runtime to the MCP endpoint above.",
  "pairing.step2": "Call benchmark.claim_slot with:",
  "pairing.step3": "Keep the returned capability only inside the agent runtime.",
  "pairing.step4": "Call benchmark.heartbeat with status ready before the operator starts the match.",
  "pairing.step5": "During the match, use benchmark.observe, benchmark.submit_actions, and benchmark.record_usage.",

  "ops.announcement.waiting": "Operations room waiting for a sanitized snapshot.",
  "ops.announcement.loading": "Loading sanitized operations snapshot.",
  "ops.announcement.connecting": "Operations live feed connecting.",
  "ops.announcement.connected": "Operations live feed connected.",
  "ops.announcement.disconnected": "Operations live feed disconnected; retained data remains visible.",
  "ops.announcement.reconnectLimit": "Operations live reconnect limit reached; retained data remains visible.",
  "ops.announcement.turn": "Turn {turn}. {count} controllers in the operations roster.",
  "ops.announcement.metricsUpdated": "Raw benchmark metrics updated.",

  "ui.draftCreated": "Draft session created. Configure every slot, pair external agents, then start explicitly.",
  "ui.devQuickPlay": "Development quick play started with one human colony.",
  "ui.matchStarted": "Match started. Baselines and turn deadlines are server-owned.",
  "ui.spectatorNote": "No human slot was handed off; monitoring the connected agents as a spectator.",
  "ui.devNoOps": "Development quick play does not expose the session operations stream.",
  "ui.replayMode": "Replay mode uses imported authoritative frames.",
  "ui.replayLoaded": "{count} replay turns loaded; view is omniscient.",
  "ui.replayNoFrames": "No completed snapshot in the replay file",
  "ui.replayNoColony": "Replay colony not found",
  "ui.missingElement": "Missing UI element: {selector}",
  "ui.devCapabilityMissing": "Development quick-play human capability is missing",
  "ui.waitingFor": "Waiting for server/controllers: {waiting}",
  "ui.matchComplete": "Match complete: {reason}",
  "ui.noColonyInRange": "No other colony in diplomacy range.",
  "ui.diplomacyMessage": "Open line established.",
  "ui.tradeMessage": "Wood for provisions.",
  "ui.selectCellFirst": "Select a cell on the map first.",
  "ui.turnResolved": "Turn resolved without events.",

  "resources.food": "Food",
  "resources.water": "Water",
  "resources.wood": "Wood",
  "resources.stone": "Stone",
  "resources.ore": "Ore",
  "resources.tools": "Tools",
  "resources.influence": "Influence",

  "biome.grassland": "grassland",
  "biome.desert": "desert",
  "biome.snow": "snow",

  "cell.water": "water",
  "cell.buildable": "buildable",
  "cell.blocked": "blocked",
  "cell.noResource": "no resource",
  "cell.housing": "{housing} housing",

  "action.wait": "wait",
  "action.gather": "gather ({x}, {y})",
  "action.build": "build {structure} ({x}, {y})",
  "action.diplomacy": "{op} {target}",
  "action.tradeOffer": "trade offer to {target}",
  "action.tradeRespond.accept": "accept",
  "action.tradeRespond.decline": "decline",
  "action.tradeRespond.offer": "offer {id}",
  "action.raid": "raid {target}",
  "action.setPolicy": "policy {policy} = {value}",
  "action.scout": "scout ({x}, {y})",
  "action.contact": "contact",
} as const;

export type TranslationKey = keyof typeof en;

const tr: Record<TranslationKey, string> = {
  "app.name": "Castle Benchmark",
  "app.subtitle": "Ajan operasyonları · protokol v1.1",
  "app.title": "Castle Benchmark · Ajan Operasyonları",

  "language.switch": "Dil",

  "connection.localReady": "Yerel çekirdek hazır",
  "connection.connected": "Benchmark servisi bağlı",
  "connection.unreachable": "Servise ulaşılamadı",

  "matchState.idle": "Boşta — başlamak için bir lobby oluştur.",
  "matchState.waiting": "Ajanlar bekleniyor — kontrolcüleri ata, sonra başlat.",
  "matchState.running": "Sürüyor — haritayı izle veya bir koloninin kontrolünü devral.",
  "matchState.finished": "Bitti — raporu incele veya bir replay yükle.",

  "setup.title": "Operasyonu kur",
  "setup.subtitle": "Lobby ve çalışan karşılaşma aynı güvenli kabuğu paylaşır.",
  "setup.scenario": "Senaryo",
  "setup.seed": "Seed",
  "setup.colonies": "Koloni",
  "setup.deadline": "Tur süresi (saniye)",
  "setup.orchestratorLabel": "Orkestratör yetkisi",
  "setup.orchestratorHelp": "Sunucunun orkestratör anahtarı (CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN). Yalnız session oluşturma isteğinde kullanılır; gönderimden sonra alan silinir ve depolanmaz.",
  "setup.createButton": "Agent lobby oluştur",
  "setup.quickPlay": "Tek kolonili hızlı oyun",
  "setup.replayImport": "Replay snapshots.jsonl",

  "replay.prev": "Önceki replay turu",
  "replay.scrub": "Replay turu",
  "replay.next": "Sonraki replay turu",

  "map.region": "Oyun alanı",
  "map.unknownBiome": "BİLİNMEYEN BİYOM",
  "map.fogActive": "SİS: AKTİF",
  "map.spectator": "SPECTATOR · TÜM DÜNYA",
  "map.replay": "REPLAY · {index}/{total}",
  "map.turnLabel": "TUR {turn} · {colony}",
  "map.canvasLabel": "İzometrik koloni haritası",
  "map.placeholder": "Harita çekirdeği bekliyor",
  "map.viewControls": "Harita görünümü",
  "map.panUp": "Haritayı yukarı kaydır",
  "map.panLeft": "Haritayı sola kaydır",
  "map.reset": "Harita görünümünü sıfırla",
  "map.panRight": "Haritayı sağa kaydır",
  "map.panDown": "Haritayı aşağı kaydır",
  "map.zoomOut": "Haritayı uzaklaştır",
  "map.zoomIn": "Haritayı yakınlaştır",
  "map.keyResource": "Kaynak",
  "map.keyColony": "Koloni",

  "intel.title": "Ajan incelemesi",
  "intel.subtitle": "Karar, gözlem ve maliyet atfı tek seçime bağlıdır.",

  "ledger.title": "Koloni gözlemi",
  "ledger.empty": "Henüz aktif koloni yok.",
  "ledger.population": "Nüfus",
  "ledger.populationValue": "{population} / {housing} konut",

  "selection.title": "Seçili hücre",
  "selection.hint": "Haritada bir hücre seç.",

  "humanControls.title": "İnsan kontrolü",

  "actions.wait": "Bekle",
  "actions.gather": "Topla",
  "actions.build": "İnşa et",
  "actions.policy": "Politika uygula",
  "actions.diplomacy": "Temas kur",
  "actions.trade": "Ticaret öner",
  "actions.raid": "Baskın yap",

  "buildChoice.label": "Yapı",

  "structures.headquarters": "Karargâh",
  "structures.house": "Ev",
  "structures.well": "Kuyu",
  "structures.farm": "Tarla",
  "structures.warehouse": "Depo",
  "structures.market": "Pazar",
  "structures.lumberCamp": "Kereste kampı",
  "structures.quarry": "Taş ocağı",
  "structures.mine": "Maden",
  "structures.workshop": "Atölye",
  "structures.clinic": "Klinik",
  "structures.barracks": "Kışla",
  "structures.watchtower": "Gözetleme kulesi",
  "structures.wall": "Duvar",
  "structures.gate": "Kapı",

  "metrics.title": "Benchmark metrikleri",
  "metrics.aria": "Benchmark metrik karşılaştırması",
  "metrics.empty": "Run report henüz hazır değil.",
  "metrics.empty2": "Ham run report mevcut değil.",
  "metrics.generation": "nesil {n}",
  "metrics.provenance.simulationRaw": "Simülasyonun kendisi ölçtü.",
  "metrics.provenance.serverMeasured": "Sunucu ölçtü.",
  "metrics.provenance.adapterReported": "Ajanın kendi adaptörü bildirdi (özbildirim).",
  "metrics.provenance.unavailable": "Hesaplanmadı — motor bunun için ham eksen bildirmiyor.",
  "metrics.survival": "Hayatta kalma",
  "metrics.growth": "Büyüme · nüfus seyri",
  "metrics.prosperity": "Refah · ham kaynaklar",
  "metrics.diplomacy": "Diplomasi · ticaret / saldırganlık",
  "metrics.resilience": "Dayanıklılık",
  "metrics.actionValidity": "Eylem geçerliliği · geçersiz eylemler",
  "metrics.timeouts": "Zaman aşımları / yeniden bağlanmalar",
  "metrics.mcpCalls": "MCP çağrıları",
  "metrics.tokens": "Tokenler / birikimli gecikme",

  "metrics.name.inputTokens": "Giriş tokenleri",
  "metrics.name.outputTokens": "Çıkış tokenleri",
  "metrics.name.latency": "Gecikme",
  "metrics.name.mcpCalls": "MCP çağrıları",
  "metrics.name.timeouts": "Zaman aşımları",
  "metrics.name.reconnects": "Yeniden bağlanmalar",
  "metrics.name.turns": "Turlar",
  "metrics.name.population": "Nüfus",
  "metrics.name.initialPopulation": "Başlangıç nüfusu",
  "metrics.name.peakPopulation": "Zirve nüfus",
  "metrics.name.housing": "Konut",
  "metrics.name.trade": "Ticaret",
  "metrics.name.aggression": "Saldırganlık",
  "metrics.name.invalidActions": "Geçersiz eylemler",

  "events.title": "Yerel bildirimler",
  "events.clear": "Temizle",
  "events.empty": "Karşılaşma başlamadı.",

  "footer.waiting": "Sanitized operations snapshot bekleniyor.",
  "footer.note": "Deterministik · tekrar oynatılabilir · seed kontrollü",

  "roster.title": "Ajan kadrosu",
  "roster.empty": "Henüz sanitized controller snapshot yok.",
  "roster.baseline": "Baseline",
  "roster.human": "İnsan operatör",
  "roster.external": "Harici ajan",
  "roster.latencyAria": "Adaptör bildirimli birikimli gecikme {value}",

  "state.unassigned": "Atanmamış",
  "state.ready": "Hazır",
  "state.pairing": "Eşleşiyor",
  "state.connected": "Bağlı",
  "state.thinking": "Düşünüyor",
  "state.submitted": "Gönderildi",
  "state.timedOut": "Zaman aşımı",
  "state.disconnected": "Bağlantısı koptu",
  "state.takenOver": "Devralındı",

  "event.turnOpened": "Tur açıldı",
  "event.controllerSubmitted": "Karar gönderildi",
  "event.turnResolved": "Tur çözüldü",
  "event.metricUpdated": "Metrikler güncellendi",
  "event.presenceChanged": "Varlık değişti",
  "event.controllerConnected": "Kontrolcü bağlandı",
  "event.controllerDisconnected": "Kontrolcü bağlantısı koptu",
  "event.controllerReady": "Kontrolcü hazır",
  "event.controllerTimedOut": "Kontrolcü zaman aşımına uğradı",
  "event.controllerReplaced": "Kontrolcü değiştirildi",
  "event.controllerClaimed": "Kontrolcü talep edildi",
  "event.heartbeatRejected": "Heartbeat reddedildi",
  "event.pairingRejected": "Eşleşme reddedildi",
  "event.matchCompleted": "Karşılaşma tamamlandı",

  "tab.decision": "Karar",
  "tab.resources": "Kaynaklar",
  "tab.diplomacy": "Diplomasi",
  "tab.cost": "Maliyet",

  "timeline.title": "Servis günlüğü",
  "timeline.aria": "Sıralı servis olayları",
  "timeline.tenure": "Görev",
  "timeline.turn": "Tur {turn}",
  "timeline.empty": "Henüz sıralı servis olayı yok.",

  "decisions.title": "Karar akışı",
  "decisions.aria": "Çözülen gönderilmiş eylemler",
  "decisions.accepted": "kabul edildi",
  "decisions.rejected": "reddedildi · {detail}",
  "decisions.empty": "Henüz çözülmüş karar yok.",

  "inspector.none": "Ajan seçilmedi",
  "inspector.turn": "Tur",
  "inspector.state": "Durum",
  "inspector.controller": "Kontrolcü",
  "inspector.source": "Kaynak",
  "inspector.sourceValue": "Otoriter koloni gözlemi",
  "inspector.detail": "Ayrıntı",
  "inspector.detailValue": "Görünür bir dünya hücresi seç veya bir replay karesi yükle.",
  "inspector.rawAxes": "Ham eksenler",
  "inspector.rawAxesValue": "Ticaret ve saldırganlık",
  "inspector.composite": "Bileşik skor",
  "inspector.compositeValue": "Yok — çıkarım yapılmadı",
  "inspector.provider": "Sağlayıcı",
  "inspector.model": "Model",
  "inspector.latency": "Gecikme",
  "inspector.attribution": "Atıf",
  "inspector.attributionValue": "Sunucu ölçümü işaretlenmedikçe ajan bildirimi",

  "lobby.title": "Agent lobby · {scenario}",
  "lobby.controller": "Kontrolcü",
  "lobby.baseline": "Baseline",
  "lobby.apply": "Atamayı uygula",
  "lobby.pair": "Eşleşme kodu üret",
  "lobby.takeOver": "İnsan olarak devral",
  "lobby.baselineFallback": "Baseline yedeğini kullan",
  "lobby.rotateExternal": "Harici eşleşmeyi yenile",
  "lobby.colony": "Koloni {id}",
  "lobby.fallbackAria": "{id} için yedek veya değiştirme",
  "lobby.allReady": "Tüm slotlar hazır — hazır olduğunda açıkça başlat",
  "lobby.oneWaiting": "{count} slot bekliyor",
  "lobby.manyWaiting": "{count} slot bekliyor",
  "lobby.start": "Karşılaşmayı başlat",
  "lobby.running": "Karşılaşma sürüyor",
  "lobby.refresh": "Lobby durumunu yenile",
  "lobby.humanReady": "İnsan kontrolcü hazır",
  "lobby.baselineReady": "Baseline hazır — {kind}",
  "lobby.disconnected": "Bağlantı koptu — bir yedek seç veya yeniden eşle",
  "lobby.externalReady": "Harici ajan hazır",
  "lobby.claimed": "Talep edildi — hazır heartbeat bekleniyor",
  "lobby.expired": "Eşleşme süresi doldu",
  "lobby.pairingActive": "Eşleşme kodu aktif",
  "lobby.unassigned": "Harici ajan atanmadı",
  "lobby.human": "İnsan",
  "lobby.deterministicBaseline": "Deterministik baseline",
  "lobby.externalMCP": "Harici MCP ajanı",
  "lobby.policyOneHuman": "Bu tarayıcı yalnızca tek insan slotu yönetebilir",
  "lobby.startNotReady": "Başlamadan önce tüm lobby slotları hazır olmalı",
  "lobby.clipboardUnavailable": "Pano erişimi kullanılamıyor",
  "lobby.noSession": "Aktif lobby session yok",

  "pairing.title": "Harici ajanı eşle · {colony}",
  "pairing.expires": "Kalan süre {duration}",
  "pairing.provider": "Ajan sağlayıcısı",
  "pairing.copyCode": "Kodu kopyala",
  "pairing.copyEndpoint": "Endpoint'i kopyala",
  "pairing.copyConfig": "Sağlayıcı talimatlarını kopyala",
  "pairing.aria": "{colony} için eşleşme yetkisi",
  "pairing.step1": "Bu ajan çalışma zamanını yukarıdaki MCP endpoint'ine bağla.",
  "pairing.step2": "Şu komutla benchmark.claim_slot çağır:",
  "pairing.step3": "Dönen yetkiyi yalnızca ajan çalışma zamanı içinde tut.",
  "pairing.step4": "Operatör karşılaşmayı başlatmadan önce status ready ile benchmark.heartbeat çağır.",
  "pairing.step5": "Karşılaşma sırasında benchmark.observe, benchmark.submit_actions ve benchmark.record_usage kullan.",

  "ops.announcement.waiting": "Operasyon odası sanitized bir snapshot bekliyor.",
  "ops.announcement.loading": "Sanitized operations snapshot yükleniyor.",
  "ops.announcement.connecting": "Operasyon canlı akışı bağlanıyor.",
  "ops.announcement.connected": "Operasyon canlı akışı bağlandı.",
  "ops.announcement.disconnected": "Operasyon canlı akışı koptu; eldeki veriler görünmeye devam ediyor.",
  "ops.announcement.reconnectLimit": "Operasyon yeniden bağlanma limitine ulaşıldı; eldeki veriler görünmeye devam ediyor.",
  "ops.announcement.turn": "Tur {turn}. Operasyon kadrosunda {count} kontrolcü.",
  "ops.announcement.metricsUpdated": "Ham benchmark metrikleri güncellendi.",

  "ui.draftCreated": "Taslak session oluşturuldu. Her slotu yapılandır, harici ajanları eşle, sonra açıkça başlat.",
  "ui.devQuickPlay": "Geliştirme hızlı oyunu tek insan kolonisiyle başladı.",
  "ui.matchStarted": "Karşılaşma başladı. Baseline'lar ve tur süreleri sunucuya aittir.",
  "ui.spectatorNote": "İnsan slotu devredilmedi; bağlı ajanlar izleyici olarak izleniyor.",
  "ui.devNoOps": "Geliştirme hızlı oyunu session operasyon akışını sunmaz.",
  "ui.replayMode": "Replay modu içe aktarılan otoriter kareleri kullanır.",
  "ui.replayLoaded": "{count} replay turu yüklendi; görünüm her şeyi gösterir.",
  "ui.replayNoFrames": "Replay dosyasında tamamlanmış snapshot yok",
  "ui.replayNoColony": "Replay kolonisi bulunamadı",
  "ui.missingElement": "Eksik arayüz öğesi: {selector}",
  "ui.devCapabilityMissing": "Geliştirme hızlı oyunu insan yetkisi eksik",
  "ui.waitingFor": "Sunucu/kontrolcüler bekleniyor: {waiting}",
  "ui.matchComplete": "Karşılaşma tamamlandı: {reason}",
  "ui.noColonyInRange": "Diplomasi menzilinde başka koloni yok.",
  "ui.diplomacyMessage": "Açık hat kuruldu.",
  "ui.tradeMessage": "Oduna karşı erzak.",
  "ui.selectCellFirst": "Önce haritada bir hücre seç.",
  "ui.turnResolved": "Tur olaysız çözüldü.",

  "resources.food": "Erzak",
  "resources.water": "Su",
  "resources.wood": "Odun",
  "resources.stone": "Taş",
  "resources.ore": "Cevher",
  "resources.tools": "Alet",
  "resources.influence": "Nüfuz",

  "biome.grassland": "çayır",
  "biome.desert": "çöl",
  "biome.snow": "kar",

  "cell.water": "su",
  "cell.buildable": "inşa edilebilir",
  "cell.blocked": "kapalı",
  "cell.noResource": "kaynak yok",
  "cell.housing": "{housing} konut",

  "action.wait": "bekle",
  "action.gather": "topla ({x}, {y})",
  "action.build": "inşa {structure} ({x}, {y})",
  "action.diplomacy": "{op} {target}",
  "action.tradeOffer": "{target} bölgesine ticaret önerisi",
  "action.tradeRespond.accept": "kabul",
  "action.tradeRespond.decline": "red",
  "action.tradeRespond.offer": "teklif {id}",
  "action.raid": "{target} bölgesine baskın",
  "action.setPolicy": "politika {policy} = {value}",
  "action.scout": "keşif ({x}, {y})",
  "action.contact": "temas",
};

export const messages: Record<Lang, Record<TranslationKey, string>> = { en, tr };

const STORAGE_KEY = "castle-benchmark.language";

let current: Lang = "tr";

export function currentLanguage(): Lang {
  return current;
}

export function initLanguage(): Lang {
  try {
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "en" || stored === "tr") current = stored;
    }
  } catch {
    // storage unavailable — fall back to the default language
  }
  applyDocumentLanguage();
  return current;
}

export function setLanguage(lang: Lang): void {
  current = lang;
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // storage unavailable — the choice applies for this session only
  }
  applyDocumentLanguage();
}

export function applyDocumentLanguage(lang: Lang = current): void {
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

export function translate(
  key: TranslationKey,
  params?: Readonly<Record<string, string | number>>,
): string {
  let result: string = messages[current][key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      result = result.replaceAll(`{${name}}`, String(value));
    }
  }
  return result;
}

export function translateStatic(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>("[data-i18n]").forEach((element) => {
    const key = element.dataset.i18n;
    if (key && key in messages.en) element.textContent = translate(key as TranslationKey);
  });
  root.querySelectorAll<HTMLElement>("[data-i18n-aria-label]").forEach((element) => {
    const key = element.dataset.i18nAriaLabel;
    if (key && key in messages.en) {
      element.setAttribute("aria-label", translate(key as TranslationKey));
    }
  });
}

const RESOURCE_KEYS: Readonly<Record<string, TranslationKey>> = {
  food: "resources.food",
  water: "resources.water",
  wood: "resources.wood",
  stone: "resources.stone",
  ore: "resources.ore",
  tools: "resources.tools",
  influence: "resources.influence",
};

export function resourceName(name: string): string {
  const key = RESOURCE_KEYS[name];
  return key ? translate(key) : name;
}

const BIOME_KEYS: Readonly<Record<string, TranslationKey>> = {
  grassland: "biome.grassland",
  desert: "biome.desert",
  snow: "biome.snow",
};

export function biomeName(biome: string): string {
  const key = BIOME_KEYS[biome];
  return key ? translate(key) : biome;
}

const STRUCTURE_KEYS: Readonly<Record<string, TranslationKey>> = {
  headquarters: "structures.headquarters",
  house: "structures.house",
  well: "structures.well",
  farm: "structures.farm",
  warehouse: "structures.warehouse",
  market: "structures.market",
  lumber_camp: "structures.lumberCamp",
  quarry: "structures.quarry",
  mine: "structures.mine",
  workshop: "structures.workshop",
  clinic: "structures.clinic",
  barracks: "structures.barracks",
  watchtower: "structures.watchtower",
  wall: "structures.wall",
  gate: "structures.gate",
};

export function structureName(kind: string): string {
  const key = STRUCTURE_KEYS[kind];
  return key ? translate(key) : kind.replaceAll("_", " ");
}

const METRIC_KEYS: Readonly<Record<string, TranslationKey>> = {
  input_tokens: "metrics.name.inputTokens",
  output_tokens: "metrics.name.outputTokens",
  latency_ms: "metrics.name.latency",
  mcp_calls: "metrics.name.mcpCalls",
  timeouts: "metrics.name.timeouts",
  reconnects: "metrics.name.reconnects",
  turns: "metrics.name.turns",
  population: "metrics.name.population",
  initial_population: "metrics.name.initialPopulation",
  peak_population: "metrics.name.peakPopulation",
  housing: "metrics.name.housing",
  trade: "metrics.name.trade",
  aggression: "metrics.name.aggression",
  invalid_actions: "metrics.name.invalidActions",
};

export function metricName(metric: string): string {
  if (metric in RESOURCE_KEYS) return resourceName(metric);
  const key = METRIC_KEYS[metric];
  return key ? translate(key) : metric.replaceAll("_", " ");
}
