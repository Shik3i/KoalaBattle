export type Side = 'p1' | 'p2';
export type AgentType = 'random' | 'manual' | 'api';
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
  configured: boolean;
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
  disabled: boolean;
}

export interface PokemonState {
  id: string;
  name: string;
  species: string;
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
  output_schema_version: string;
}

export interface BattleState {
  match_id: string;
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
}

export interface TeamValidationResult {
  format: 'gen9ou';
  valid: boolean;
  errors: string[];
  normalized_export: string | null;
  packed_team: string | null;
  structured_team: Array<Record<string, unknown>>;
}

export interface TeamSnapshot {
  id: string;
  name: string;
  format: 'gen9ou';
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
  events: BattleEvent[];
  decisions: Array<{
    id: number;
    decision: {
      side: Side;
      turn: number;
      action: string;
      commentary: string;
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

export type ProductionTrack = 'visual' | 'commentary' | 'voice' | 'captions' | 'sfx' | 'music' | 'director';
export type DirectorState = 'pre-show' | 'match-intro' | 'team-reveal' | 'battle' | 'between-games' | 'result' | 'champion' | 'paused' | 'ended';

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
  event_gap_ms: number;
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
  payload: Record<string, unknown>;
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
  provider: 'system' | 'openai' | 'openai-compatible' | 'fake';
  voice: string;
  model: string | null;
  language: string | null;
  speed: number;
  instructions: string | null;
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
  encoder_information: string | null;
  video_duration_ms: number | null;
  render_duration_ms: number | null;
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
