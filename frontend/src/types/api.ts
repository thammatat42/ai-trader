// ---- Common ----
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  redis: string;
}

// ---- Auth ----
export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: "admin" | "trader" | "viewer";
  is_active: boolean;
  ban_reason: string | null;
  banned_at: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface UserDetail extends User {
  banned_by: string | null;
  failed_login_count: number;
  locked_until: string | null;
  updated_at: string;
}

export interface LoginActivity {
  id: string;
  user_id: string | null;
  email: string;
  ip_address: string | null;
  user_agent: string | null;
  country: string | null;
  city: string | null;
  success: boolean;
  failure_reason: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  full_key: string;
}

// ---- Trading ----
export interface Trade {
  id: string;
  platform_id: string;
  order_id: string;
  symbol: string;
  action: "buy" | "sell";
  lot_size: number;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  profit: number | null;
  status: "open" | "closed" | "cancelled" | "error";
  ai_provider_id: string | null;
  created_at: string;
  closed_at: string | null;
}

// ---- AI ----
export interface AiProvider {
  id: string;
  name: string;
  provider_type: "openrouter" | "nvidia_nim";
  model: string;
  is_active: boolean;
  created_at: string;
}

export interface AiAnalysis {
  id: string;
  ai_provider_id: string;
  platform_id: string;
  sentiment: "bullish" | "bearish" | "neutral";
  confidence: number;
  reasoning: string;
  recommendation: string;
  latency_ms: number;
  created_at: string;
}

// ---- Platform ----
export interface TradingPlatform {
  id: string;
  name: string;
  platform_type: "mt5_bridge" | "bitkub" | "binance";
  is_active: boolean;
  created_at: string;
}

// ---- Bot ----
export interface BotSettings {
  id: string;
  platform_id: string;
  is_running: boolean;
  analysis_interval_seconds: number;
  lot_size: number;
  max_daily_trades: number;
  stop_loss_pips: number;
  take_profit_pips: number;
}
