export type Side = 'p1' | 'p2';
export type AgentType = 'random' | 'manual' | 'human' | 'api';
export type ProviderKind = 'openai' | 'gemini' | 'anthropic' | 'deepseek' | 'openai-compatible' | 'fake';
export type AgentLifecycleState = 'idle' | 'waiting' | 'thinking' | 'retrying' | 'decided' | 'executing' | 'error' | 'finished';

export interface AgentConfiguration {
  timeout_seconds: number;
  max_retries: number;
  fallback: 'random' | 'manual' | 'forfeit';
  temperature: number | null;
  max_output_tokens: number;
  reasoning_effort: 'low' | 'medium' | 'high' | 'max' | null;
  base_url: string | null;
  maximum_cost: number | null;
  fake_scenario?: string;
}

export interface ProviderStatus {
  id: ProviderKind;
  label: string;
  default_model: string;
  known_models: string[];
  default_base_url: string | null;
  requires_api_key: boolean;
  environment_variable: string | null;
  configured: boolean;
  source: 'runtime' | 'environment' | 'custom-url' | 'none';
  capabilities: {
    structured_output: boolean;
    model_listing: boolean;
    temperature: boolean;
    reasoning_control: boolean;
    usage_reporting: boolean;
  };
}

export interface BattleAction {
  id: string;
  type: 'move' | 'switch';
  name: string;
  slot: number;
  terastallize: boolean;
  // Public metadata attached by the engine. Absent on archives recorded before this pass.
  move_type?: string | null;
  category?: 'physical' | 'special' | 'status' | null;
  power?: number | null;
  accuracy?: number | null;
  current_pp?: number | null;
  max_pp?: number | null;
  priority?: number | null;
  species?: string | null;
  hp_fraction?: number | null;
  status?: string | null;
}

export type GameType = 'singles' | 'doubles' | 'triples' | 'multi' | 'freeforall';

export interface FormatMechanics {
  items: boolean;
  abilities: boolean;
  physical_special_split: boolean;
  mega_evolution: boolean;
  z_moves: boolean;
  dynamax: boolean;
  terastallization: boolean;
  hidden_power_types: boolean;
  natures: boolean;
  held_item_switching: boolean;
}

export interface FormatDescriptor {
  id: string;
  name: string;
  display_name: string;
  generation: number;
  banter_enabled?: boolean;
  mod: string;
  section: string;
  game_type: GameType;
  player_count: number;
  team_source: string;
  random_team: boolean;
  custom_team_required: boolean;
  challenge_visible: boolean;
  tournament_visible: boolean;
  search_visible: boolean;
  rated: boolean;
  best_of_default: boolean | null;
  mechanics: FormatMechanics;
  supported: boolean;
  unsupported_reason: string | null;
}

export interface FormatGroup {
  generation: number;
  label: string;
  formats: FormatDescriptor[];
}

export interface FormatCatalog {
  schema_version: string;
  source: 'showdown-live' | 'showdown-snapshot';
  showdown_version: string;
  format_count: number;
  supported_count: number;
  supported_game_types: GameType[];
  formats: FormatDescriptor[];
}

export interface MoveState {
  id: string;
  name: string;
  type: string | null;
  category?: 'physical' | 'special' | 'status' | null;
  power: number | null;
  accuracy: number | null;
  current_pp: number | null;
  max_pp: number | null;
  priority?: number | null;
  disabled: boolean;
}

export interface PokemonState {
  id: string;
  name: string;
  species: string;
  level?: number | null;
  hp_fraction: number;
  current_hp?: number | null;
  max_hp?: number | null;
  status: string | null;
  types: string[];
  item?: string | null;
  ability?: string | null;
  tera_type?: string | null;
  terastallized?: boolean;
  boosts?: Record<string, number>;
  effects?: string[];
  moves?: MoveState[];
  active: boolean;
  fainted: boolean;
}

export interface BattleSide {
  side: Side;
  display_name: string;
  active: PokemonState | null;
  team: PokemonState[];
  side_conditions?: string[];
  can_terastallize?: boolean;
  terastallization_used?: boolean;
}

export interface KnownPokemon {
  id: string;
  species: string;
  display_name: string;
  hp_fraction: number | null;
  status: string | null;
  active: boolean;
  fainted: boolean;
  revealed_moves: MoveState[];
  revealed_item: string | null;
  revealed_ability: string | null;
  revealed_tera_type: string | null;
  types: string[];
}

export interface PlayerKnowledgeState {
  schema_version: string;
  match_id: string;
  side: Side;
  turn: number;
  own_side: BattleSide;
  opponent_active: KnownPokemon | null;
  known_opponent: KnownPokemon[];
  weather: string[];
  fields: string[];
}

export interface ContextMetrics {
  rendered_characters: number;
  estimated_tokens: number;
  estimate_method: string;
  history_event_count: number;
  knowledge_entries: number;
  context_profile_version: string;
  history_policy_version: string;
}

export interface AgentContextSnapshot {
  schema_version: string;
  match_id: string;
  format: string;
  generation: number;
  turn: number;
  side: Side;
  knowledge: PlayerKnowledgeState;
  recent_events: string[];
  strategy_memory: string | null;
  legal_actions: BattleAction[];
  prompt_profile_id: 'standard-competitive' | 'benchmark-fair';
  prompt_profile_version: string;
  context_profile_id: 'pokemon-standard' | 'pokemon-compact';
  context_profile_version: string;
  history_policy_version: string;
  memory_policy: 'disabled' | 'strategy-note';
  memory_policy_version: string;
  banter_enabled?: boolean;
  output_schema_version: string;
}

export interface BattleState {
  match_id: string;
  format?: string;
  generation?: number;
  turn: number;
  perspective: Side;
  player: BattleSide;
  opponent: BattleSide;
  weather: string[];
  fields: string[];
  last_action: string | null;
  public_history: string[];
  result: { winner: Side | null; winner_name: string | null; turns: number } | null;
}

export interface BattleEvent {
  id: number;
  match_id: string;
  sequence: number;
  turn: number;
  event_type: string;
  logical_offset_ms: number;
  payload: Record<string, unknown>;
}

export interface AssetCategoryStatus {
  directory: string;
  files: number;
  installed: boolean;
}

export interface AssetScanReport {
  root: string;
  valid: boolean;
  pokemon_species: number;
  categories: Record<string, AssetCategoryStatus>;
  invalid_files: string[];
  unresolved_species: string[];
}

export interface AssetResolution {
  species_id: string;
  perspective: 'front' | 'back';
  animated: boolean;
  kind: 'sprite' | 'icon';
  found: boolean;
  relative_path: string | null;
  resolved_path: string | null;
}

export interface AgentRequest {
  request_id: string;
  match_id: string;
  side: Side;
  turn: number;
  state: BattleState;
  legal_actions: BattleAction[];
  prompt: string;
  system_prompt?: string | null;
  user_prompt?: string | null;
  knowledge: PlayerKnowledgeState | null;
  context: AgentContextSnapshot | null;
  context_metrics: ContextMetrics | null;
  prompt_profile_id: 'standard-competitive' | 'benchmark-fair';
  prompt_profile_version: string;
  context_schema_version: string;
  knowledge_schema_version: string;
  history_policy_version: string;
  memory_policy: 'disabled' | 'strategy-note';
  memory_policy_version: string;
  prompt_schema_version: string;
  prompt_template_version: string;
  information_profile: 'standard';
  banter_enabled?: boolean;
}

export interface TeamValidationResult {
  format: string;
  valid: boolean;
  errors: string[];
  normalized_export: string | null;
  packed_team: string | null;
  structured_team: Array<Record<string, unknown>>;
}

export interface TeamSnapshot {
  id: string;
  name: string;
  format: string;
  source: 'imported' | 'agent-generated' | 'preset';
  submitted_text: string;
  normalized_export: string;
  packed_team: string;
  structured_team: Array<Record<string, unknown>>;
  generation_audit: Record<string, unknown> | null;
  created_at: string;
}

export interface TeamBuildAudit {
  id: string;
  participant: string;
  provider: string;
  model: string;
  rendered_prompt: string;
  raw_responses: string[];
  validation_errors: string[][];
  repair_attempts: number;
  success: boolean;
  team_snapshot_id: string | null;
  latency_ms: number;
}

export interface MatchArchive {
  id: string;
  created_at: string;
  updated_at: string;
  status: MatchStatus;
  config: {
    name?: string | null;
    format: string;
    generation: number;
    banter_enabled?: boolean;
    players: Array<{
      side: Side;
      display_name: string;
      agent_type: AgentType;
      provider?: string | null;
      model?: string | null;
      configuration?: AgentConfiguration;
      team_source?: 'showdown-random' | 'imported' | 'agent-generated' | 'preset';
      team_snapshot_id?: string | null;
      team_export?: string | null;
      team_packed?: string | null;
    }>;
  };
  winner: Side | null;
  turns: number;
  error: string | null;
  tournament_id: string | null;
  series_id: string | null;
  queue_position: number | null;
  challenge_run_id: string | null;
  challenge_stage_id: string | null;
  events: BattleEvent[];
  decisions: Array<{
    id: number;
    decision: {
      side: Side;
      turn: number;
      action: string;
      commentary: string;
      banter?: string;
      strategy_memory?: string | null;
      latency_ms?: number | null;
      provider?: string | null;
      model?: string | null;
      usage?: { input_tokens?: number | null; output_tokens?: number | null; total_tokens?: number | null } | null;
      estimated_cost?: { amount: number | null; currency: string; pricing_version: string | null; available: boolean };
      validation_attempts?: number;
      validation_errors?: string[];
      retry_attempts?: Array<{ attempt: number; category: string; detail: string }>;
      fallback?: { policy: string; reason: string; used: boolean } | null;
      error_category?: string | null;
    };
    request?: AgentRequest;
    generated_prompt?: string;
    raw_response?: string | null;
    parsed_response?: Record<string, unknown> | null;
  }>;
}

export type ChallengeStatus = 'drafting' | 'training' | 'team_review' | 'ready' | 'battle_queued' | 'battling' | 'stage_result' | 'completed' | 'failed' | 'cancelled' | 'abandoned';

export interface DraftCandidate {
  entry_id: string;
  species: string;
  showdown_id: string;
  base_species_id: string;
  national_dex_number: number;
  introduction_generation: number;
  types: string[];
  base_stat_total: number | null;
  points: number;
}

export interface EvSpread {
  hp: number;
  atk: number;
  def: number;
  spa: number;
  spd: number;
  spe: number;
}

export interface ChallengeRunView {
  run: {
    id: string;
    name: string;
    status: ChallengeStatus;
    revision: number;
    seed: number;
    definition: {
      id: string;
      version: string;
      name: string;
      description: string;
      format: string;
      draft_rules: { roster_size: number; starting_credits: number; rerolls: number; choice_count: number; species_clause: boolean };
      training_rules: { global_ev_budget: number; per_pokemon_max: number; per_stat_max: number };
    };
    pricing: { schema_version: string; parser_version: string; board_name: string; context: string; catalog_hash: string; source_sha256: string; imported_at: string; mechanics_assumptions: string[] };
    draft_controller: { kind: 'human' | 'agent' | 'random'; provider?: ProviderKind | null; model?: string | null };
    draft_controller_history: Array<{ kind: 'human' | 'agent' | 'random'; provider?: ProviderKind | null; model?: string | null }>;
    battle_controller: { agent_type: AgentType; provider?: ProviderKind | null; model?: string | null };
    opponent_controller: { agent_type: AgentType; provider?: ProviderKind | null; model?: string | null };
    credits_remaining: number;
    rerolls_remaining: number;
    current_offer: { round: number; nonce: number; generation: number; type: string; options: DraftCandidate[]; fingerprint: string } | null;
    picks: Array<{ round: number; candidate: DraftCandidate; selected_by: 'human' | 'agent' | 'random'; created_at: string }>;
    ev_allocations: Record<string, EvSpread>;
    team_snapshot_id: string | null;
    current_stage_index: number;
    active_match_id: string | null;
    stage_results: Array<{ stage_id: string; stage_index: number; match_id: string; status: 'won' | 'lost' | 'draw' | 'failed' | 'cancelled' | 'interrupted'; winner: string | null; turns: number; duration_seconds: number; estimated_cost: number; average_decision_latency_ms: number | null; decision_count: number; started_at: string; completed_at: string }>;
    error: string | null;
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  };
  stages: Array<{ id: string; name: string; title: string; theme: string; level: number }>;
  current_stage: { id: string; name: string; title: string; theme: string; level: number } | null;
  statistics: { stages_cleared: number; wins: number; losses: number; draws: number; total_battles: number; technical_failures: number; total_turns: number; duration_seconds: number; estimated_cost: number; average_decision_latency_ms: number | null; credits_spent: number; credits_remaining: number; rerolls_used: number; ev_used: number };
  team_export_scaffold: string | null;
  minimum_completion_cost: number;
}

export interface ChallengeRunSummary {
  id: string;
  name: string;
  definition_name: string;
  definition_version: string;
  status: ChallengeStatus;
  current_stage_index: number;
  stage_count: number;
  stages_cleared: number;
  created_at: string;
  updated_at: string;
}

export interface PricingStatus {
  available: boolean;
  ready: boolean;
  path: string;
  catalog_hash: string | null;
  board_name: string | null;
  context: string | null;
  imported_at: string | null;
  parsed_entries: number;
  eligible_entries: number;
  priced_entries: number;
  banned_entries: number;
  missing_entries: number;
  unsupported_entries: number;
  source_verified: boolean;
  verification_detail: string;
  excluded_entries: Array<{ species: string; state: string; reason: string }>;
  errors: string[];
}

export type ProductionTrack = 'visual' | 'commentary' | 'voice' | 'captions' | 'sfx' | 'music' | 'director';
export type DirectorState = 'pre-show' | 'match-intro' | 'team-reveal' | 'battle' | 'between-games' | 'result' | 'champion' | 'paused' | 'ended';
export type NarratorMode = 'off' | 'highlights' | 'broadcast' | 'full';

export interface NarratorSettings {
  enabled: boolean;
  profile_id: string;
  mode: NarratorMode;
  voice_preset_id: string;
  cooldown_ms: number;
  max_lines_per_turn: number;
  max_lines_per_match: number;
  minimum_priority: number;
  repeat_window_ms: number;
  overlap_policy: 'duck' | 'queue' | 'suppress';
  captions_enabled: boolean;
  include_pokemon_names: boolean;
  include_move_names: boolean;
  language: string;
}

export interface NarratorProfile {
  id: string;
  display_name: string;
  description: string;
  recommended_mode: NarratorMode;
  recommended_cooldown_ms: number;
  recommended_max_lines_per_match: number;
}

export interface ProductionProfile {
  id: string;
  display_name: string;
  version: string;
  intro_enabled: boolean;
  speech_enabled: boolean;
  captions_enabled: boolean;
  sfx_enabled: boolean;
  music_enabled: boolean;
  wait_for_speech: boolean;
  commentary_max_characters: number;
  caption_max_characters: number;
  turn_target_ms: number;
  event_gap_ms: number;
  turn_gap_ms: number | null;
  intro_duration_ms: number;
  result_duration_ms: number;
  outro_duration_ms: number;
  aspect_ratio: '16:9' | '9:16';
  interruption_policy: 'finish-current' | 'interrupt';
  ducking_db: number;
}

export interface ProductionCue {
  id: string;
  track: ProductionTrack;
  kind: string;
  start_ms: number;
  duration_ms: number;
  event_sequence: number | null;
  turn: number | null;
  side: Side | null;
  speaker: 'p1' | 'p2' | 'narrator' | null;
  payload: Record<string, unknown>;
}

export type Intensity = 'off' | 'minimal' | 'standard' | 'dramatic';
export type FontFamilyId = 'system' | 'geometric' | 'grotesk' | 'serif' | 'mono' | 'pixel' | 'custom';

export interface BackgroundStyle {
  kind: 'arena' | 'solid' | 'gradient' | 'image';
  color: string;
  secondary_color: string;
  asset_id: string | null;
  fit: 'cover' | 'contain';
  position: 'center' | 'top' | 'bottom' | 'left' | 'right';
  brightness: number;
  contrast: number;
  blur: number;
  overlay_opacity: number;
  vignette: number;
}

export interface StageStyle {
  background: BackgroundStyle;
  arena: 'none' | 'stadium' | 'platform' | 'minimal-floor' | 'grid';
  floor_visible: boolean;
  ground_shadow: boolean;
  stage_lighting: number;
  ambient_intensity: number;
  background_motion: boolean;
  accent: string;
}

export interface HudStyle {
  preset: 'broadcast' | 'fighting' | 'minimal' | 'esports' | 'retro';
  hp_shape: 'slash' | 'rounded' | 'square' | 'pill';
  hp_thickness: number;
  damage_ghost: boolean;
  show_hp_percent: boolean;
  show_hp_exact: boolean;
  show_level: boolean;
  show_types: boolean;
  show_status: boolean;
  show_player_name: boolean;
  show_provider: boolean;
  show_logo: boolean;
  show_player_slot: boolean;
  team_indicators: 'full' | 'revealed' | 'fainted-only' | 'hidden';
  show_turn: boolean;
  show_weather: boolean;
}

export interface TypographyStyle {
  display: FontFamilyId;
  body: FontFamilyId;
  mono: FontFamilyId;
  display_asset_id: string | null;
  body_asset_id: string | null;
  scale: number;
  display_weight: number;
  letter_spacing: number;
  uppercase: boolean;
  outline: boolean;
  shadow: boolean;
}

export interface MoveCalloutStyle {
  layout: 'banner' | 'impact' | 'minimal' | 'lower-third' | 'centered' | 'off';
  show_type: boolean;
  show_archetype: boolean;
  duration_scale: number;
}

export interface DamageStyle {
  show_damage: boolean;
  show_healing: boolean;
  show_effectiveness: boolean;
  show_critical: boolean;
  show_miss: boolean;
  show_immune: boolean;
  intensity: Intensity;
}

export interface CommentaryStyle {
  layout: 'fighter-card' | 'side-panel' | 'lower-third' | 'bubble' | 'caption' | 'off';
  show_agent_name: boolean;
  show_logo: boolean;
  show_label: boolean;
  animation: 'fade' | 'slide' | 'punch' | 'minimal' | 'none';
}

export interface CaptionStyle {
  preset: 'broadcast' | 'minimal' | 'high-contrast' | 'vertical' | 'off';
  show_speaker: boolean;
  background_opacity: number;
  outline: boolean;
  size_scale: number;
  position: 'bottom' | 'center' | 'top';
}

export interface EffectStyle {
  intensity: Intensity;
  camera: 'static' | 'subtle' | 'dynamic';
  idle_motion: 'full' | 'subtle' | 'off';
  pacing: 'cinematic' | 'standard' | 'fast';
  impact_flash: boolean;
  trails: boolean;
}

export interface IntroStyle {
  enabled: boolean;
  length: 'quick' | 'standard' | 'dramatic';
  show_player_logos: boolean;
  show_player_names: boolean;
  show_format: boolean;
  show_generation: boolean;
  show_game_number: boolean;
  show_series_score: boolean;
  show_tournament_round: boolean;
}

export interface ResultStyle {
  enabled: boolean;
  show_winner: boolean;
  show_logos: boolean;
  show_final_score: boolean;
  show_format: boolean;
  show_series: boolean;
  duration_ms: number;
}

export interface WatermarkStyle {
  enabled: boolean;
  asset_id: string | null;
  text: string | null;
  position: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
  opacity: number;
  size: number;
}

export interface ParticipantBranding {
  display_name: string | null;
  short_name: string | null;
  logo_asset_id: string | null;
  logo_mark: string | null;
  accent: string | null;
  secondary_accent: string | null;
}

export interface SeriesDisplay {
  tournament_name: string | null;
  round_name: string | null;
  game_number: number | null;
  best_of: number | null;
  score_p1: number | null;
  score_p2: number | null;
}

export interface ProductionStyle {
  schema_version: string;
  id: string;
  display_name: string;
  version: string;
  builtin: boolean;
  title: string | null;
  show_format: boolean;
  show_generation: boolean;
  show_koala_branding: boolean;
  stage: StageStyle;
  hud: HudStyle;
  typography: TypographyStyle;
  move: MoveCalloutStyle;
  damage: DamageStyle;
  commentary: CommentaryStyle;
  caption: CaptionStyle;
  effect: EffectStyle;
  intro: IntroStyle;
  result: ResultStyle;
  watermark: WatermarkStyle;
  players: Record<string, ParticipantBranding>;
  series: SeriesDisplay;
}

export interface StylePreset {
  id: string;
  display_name: string;
  description: string;
  builtin: boolean;
  style: ProductionStyle;
  created_at: string | null;
  updated_at: string | null;
}

export type BrandAssetKind = 'logo' | 'background' | 'watermark' | 'font';

export interface BrandAsset {
  schema_version: string;
  id: string;
  kind: BrandAssetKind;
  display_name: string;
  media_type: string;
  relative_path: string;
  byte_size: number;
  width: number | null;
  height: number | null;
  content_sha256: string;
  created_at: string;
}

export interface BrandAssetLibrary {
  schema_version: string;
  root: string;
  assets: BrandAsset[];
  marks: string[];
}

export interface ProductionTimeline {
  id: string;
  match_id: string;
  profile: ProductionProfile;
  timeline_version: string;
  revision: number;
  status: 'draft' | 'live' | 'finalizing' | 'finalized' | 'preparing' | 'ready' | 'partial' | 'failed';
  director_state: DirectorState;
  cues: ProductionCue[];
  voice_assignments: Record<string, string>;
  voice_pool_id: string | null;
  voice_selection_mode: 'explicit' | 'random' | 'balanced-random';
  voice_selection_seed: number | null;
  narrator: NarratorSettings;
  style: ProductionStyle;
  title: string | null;
  overrides: Record<string, unknown>;
  authoritative_client_id: string | null;
  duration_ms: number;
  finalized_at: string | null;
  content_sha256: string | null;
  created_at: string;
  updated_at: string;
}

export interface VoicePreset {
  id: string;
  display_name: string;
  provider: 'system' | 'qwen-local' | 'openai' | 'openai-compatible' | 'fake';
  voice: string;
  model: string | null;
  language: string | null;
  speed: number;
  instructions: string | null;
  tags: string[];
  voice_mode: 'system' | 'reference-clone' | 'custom-voice' | 'voice-design';
  persona_id: string | null;
  delivery_profile: string | null;
  disclosure_label: string | null;
  reference_audio_path: string | null;
  reference_text: string | null;
  x_vector_only_mode: boolean;
  enabled: boolean;
}

export interface VoicePersona {
  id: string;
  display_name: string;
  description: string;
  delivery_profile: string;
  instructions: string;
  disclosure_label: string;
  recommended_voice_mode: 'system' | 'reference-clone' | 'custom-voice' | 'voice-design';
}

export interface VoicePool {
  id: string;
  display_name: string;
  description: string;
  voice_ids: string[];
  enabled: boolean;
}

export interface SpeechProviderStatus {
  id: VoicePreset['provider'];
  configured: boolean;
  available: boolean;
  paid: boolean;
  detail: string;
  supports_timestamps: boolean;
  voices: string[];
}

export type ExportBackend = 'offline' | 'obs';
export type RenderEngine = 'native' | 'legacy';
export type ExportStatus = 'queued' | 'preparing' | 'rendering' | 'encoding' | 'finalizing' | 'completed' | 'cancelled' | 'failed';

export interface VideoExportPreset {
  id: string;
  display_name: string;
  version: string;
  width: number;
  height: number;
  fps: number;
  codec: 'h264' | 'hevc' | 'av1';
  quality: 'fast' | 'balanced' | 'high';
  pacing_profile: string;
  layout: '16:9' | '9:16';
}

export interface VideoExportJob {
  id: string;
  production_id: string;
  match_id: string;
  backend: ExportBackend;
  preset: VideoExportPreset;
  output_name: string;
  priority: number;
  start_ms: number;
  end_ms: number;
  status: ExportStatus;
  stage: string;
  progress: number;
  cancel_requested: boolean;
  attempt: number;
  encoder: string;
  render_engine: RenderEngine;
  encoder_information: string | null;
  video_duration_ms: number | null;
  render_duration_ms: number | null;
  output_frame_count: number | null;
  unique_rendered_frames: number | null;
  static_held_frames: number | null;
  animated_frames: number | null;
  renderer_transport: string | null;
  selected_encoder: string | null;
  output_file_size: number | null;
  error_category: string | null;
  error_detail: string | null;
  created_at: string;
}

export interface RendererCapabilities {
  offline_available: boolean;
  obs_configured: boolean;
  ffmpeg_available: boolean;
  ffmpeg_version: string | null;
  ffprobe_available: boolean;
  chromium_available: boolean;
  chromium_version: string | null;
  playwright_available: boolean;
  native_compositor_available: boolean;
  webcodecs_available: boolean;
  webcodecs_h264: boolean;
  webcodecs_vp9: boolean;
  raw_frame_available: boolean;
  legacy_renderer_available: boolean;
  default_render_engine: RenderEngine;
  compositor_backend: string;
  encoders: string[];
  output_writable: boolean;
  output_root: string;
  free_bytes: number;
  storage_bytes: number;
  concurrency: number;
  obs_host: string;
  obs_port: number;
  obs_scene: string;
  detail: string[];
}

export interface ExportPreflight {
  ready: boolean;
  checks: Record<string, string>;
  missing_speech: string[];
  warnings: string[];
}

export type MatchSummary = Omit<MatchArchive, 'events' | 'decisions'> & {
  estimated_cost: number;
};

export type MatchStatus =
  | 'created'
  | 'queued'
  | 'starting'
  | 'running'
  | 'waiting'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

export type TournamentStatus =
  | 'draft'
  | 'ready'
  | 'running'
  | 'paused'
  | 'completed'
  | 'cancelled'
  | 'failed';

export interface TournamentParticipant {
  id: string;
  display_name: string;
  seed: number;
  agent: {
    agent_type: AgentType;
    provider: string | null;
    model: string | null;
  };
}

export interface TournamentSeries {
  id: string;
  round_number: number;
  bracket_position: number;
  queue_order: number;
  status: 'blocked' | 'ready' | 'queued' | 'running' | 'completed' | 'cancelled' | 'failed';
  participant_a_id: string | null;
  participant_b_id: string | null;
  dependency_a_id: string | null;
  dependency_b_id: string | null;
  best_of: number;
  wins_a: number;
  wins_b: number;
  draws: number;
  games_played: number;
  max_games: number;
  winner_participant_id: string | null;
  match_ids: string[];
}

export interface TournamentStanding {
  participant_id: string;
  display_name: string;
  seed: number;
  played: number;
  wins: number;
  losses: number;
  draws: number;
  points: number;
}

export interface TournamentArchive {
  id: string;
  name: string;
  format: 'single_elimination' | 'round_robin';
  status: TournamentStatus;
  best_of: number;
  max_concurrent_matches: number;
  maximum_total_cost: number | null;
  max_draw_replays: number;
  manual_scheduling: boolean;
  current_round: number;
  winner_participant_id: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  participants: TournamentParticipant[];
  series: TournamentSeries[];
  standings: TournamentStanding[];
  statistics: {
    matches_played: number;
    series_played: number;
    total_turns: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost: number;
    average_decision_latency_ms: number | null;
  };
}

export interface TournamentSummary {
  id: string;
  name: string;
  format: TournamentArchive['format'];
  status: TournamentStatus;
  participant_count: number;
  series_count: number;
  completed_series: number;
  current_round: number;
  created_at: string;
  updated_at: string;
}

export interface AdminOverview {
  active_matches: number;
  queued_matches: number;
  concurrency_limit: number;
  active_tournaments: number;
  provider_failures: number;
  showdown: { status: 'healthy' | 'unavailable'; url: string };
  backend: { status: string; version: string };
}
