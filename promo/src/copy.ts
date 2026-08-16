export type Lang = "en" | "tr";

/**
 * Every line the film says, in both languages.
 *
 * The claims here are quoted from artifacts on disk — the suite means, the model's
 * winning turn, the axis names — so a change in the benchmark that makes a line false
 * should make the data build fail rather than leave the film lying quietly.
 */
export const copy = {
  en: {
    title: "Castle Benchmark",
    subtitle: "A deterministic colony survival benchmark for LLM agents, played over MCP",
    measuresTitle: "What it puts an agent under",
    measures: [
      ["Supply", "colonists eat and drink every turn"],
      ["Ground", "you may only work what your buildings can reach"],
      ["Fog", "you see what you explored, and pay for exploring"],
      ["Labour", "two actions a turn, fewer when people are hurt"],
      ["Diplomacy", "alliances need consent; messages actually arrive"],
      ["Recovery", "fire burns, damage repairs, injuries mend slowly"],
    ],
    replayTitle: "A real match, replayed frame by frame",
    replayNote: "basic-survival-v1 · seed 17 · four colonies · every turn hashed and replayable",
    turn: "TURN",
    resultTitle: "A model played it, and won",
    resultLine: "DeepSeek V4 Flash · monument completed on turn 53 · four colonies, one seat",
    resultScores: "composite score",
    suiteTitle: "Scripted baselines, five seeds, every seat",
    outroTitle: "Run it",
    outroLines: [
      "uv run castle-benchmark serve",
      "uv run castle-benchmark suite --seeds 11,17,23,29,37 --rotations all",
      "uv run castle-benchmark mixed-run --external-seats 1",
    ],
    outroNote: "Rules published. Runs replay to the same hashes. Nothing hidden but the map.",
  },
  tr: {
    title: "Castle Benchmark",
    subtitle: "LLM ajanları için MCP üzerinden oynanan deterministik koloni benchmark'ı",
    measuresTitle: "Ajanı neyin altına sokuyor",
    measures: [
      ["Tedarik", "kolonistler her tur yiyip içer"],
      ["Zemin", "yalnız binalarının uzandığı yeri işleyebilirsin"],
      ["Sis", "keşfettiğini görürsün, keşfin bedeli vardır"],
      ["Emek", "turda iki aksiyon, insanlar yaralıysa daha az"],
      ["Diplomasi", "ittifak rıza ister; mesajlar gerçekten ulaşır"],
      ["Toparlanma", "yangın yakar, hasar onarılır, yaralar yavaş kapanır"],
    ],
    replayTitle: "Gerçek bir maç, kare kare yeniden oynatılıyor",
    replayNote: "basic-survival-v1 · seed 17 · dört koloni · her tur hash'lenir ve tekrar oynatılır",
    turn: "TUR",
    resultTitle: "Bir model oynadı ve kazandı",
    resultLine: "DeepSeek V4 Flash · 53. turda anıt tamamlandı · dört koloni, bir koltuk",
    resultScores: "bileşik puan",
    suiteTitle: "Betikli baseline'lar, beş seed, her koltuk",
    outroTitle: "Çalıştır",
    outroLines: [
      "uv run castle-benchmark serve",
      "uv run castle-benchmark suite --seeds 11,17,23,29,37 --rotations all",
      "uv run castle-benchmark mixed-run --external-seats 1",
    ],
    outroNote: "Kurallar açık. Koşular aynı hash'lerle tekrar oynanır. Gizli olan tek şey harita.",
  },
} as const;

export const model = {
  name: "DeepSeek V4 Flash",
  winningTurn: 53,
  composites: [
    { colony: "c1", label: { en: "the model", tr: "model" }, score: 175 },
    { colony: "c3", label: { en: "expansionist", tr: "genişlemeci" }, score: 155 },
    { colony: "c4", label: { en: "trader", tr: "tüccar" }, score: 111 },
    { colony: "c2", label: { en: "survivalist", tr: "hayatta kalan" }, score: 103 },
  ],
} as const;
