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

export interface PokemonState {
  id: string;
  name: string;
  species: string;
  hp_fraction: number;
  status: string | null;
  types: string[];
  active: boolean;
  fainted: boolean;
}

export interface BattleSide {
  side: Side;
  display_name: string;
  active: PokemonState | null;
  team: PokemonState[];
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
  prompt_schema_version: string;
  prompt_template_version: string;
  information_profile: 'standard';
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
