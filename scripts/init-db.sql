-- =============================================
-- A股轮动策略交易系统 - 数据库初始化脚本
-- =============================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(100),
    phone VARCHAR(20),
    role VARCHAR(20) NOT NULL DEFAULT 'USER',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 策略配置表
CREATE TABLE IF NOT EXISTS strategy_configs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    strategy_type VARCHAR(20) NOT NULL,  -- AGGRESSIVE / MODERATE / CONSERVATIVE
    name VARCHAR(100) NOT NULL,
    params JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 交易信号表
CREATE TABLE IF NOT EXISTS trade_signals (
    id BIGSERIAL PRIMARY KEY,
    signal_date DATE NOT NULL,
    strategy_type VARCHAR(20) NOT NULL,
    sector_code VARCHAR(20) NOT NULL,
    sector_name VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL,  -- BUY / SELL
    position_ratio DECIMAL(5,4) NOT NULL,  -- 建议仓位比例
    score DECIMAL(10,4),  -- 评分
    reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, strategy_type, sector_code, direction)
);

-- 持仓记录表
CREATE TABLE IF NOT EXISTS positions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    strategy_type VARCHAR(20) NOT NULL,
    sector_code VARCHAR(20) NOT NULL,
    sector_name VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL DEFAULT 'BUY',
    quantity DECIMAL(15,4) NOT NULL,
    avg_price DECIMAL(10,4) NOT NULL,
    current_price DECIMAL(10,4),
    position_ratio DECIMAL(5,4) NOT NULL,
    opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'  -- OPEN / CLOSED
);

-- 交易记录表
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    strategy_type VARCHAR(20) NOT NULL,
    sector_code VARCHAR(20) NOT NULL,
    sector_name VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL,  -- BUY / SELL
    quantity DECIMAL(15,4) NOT NULL,
    price DECIMAL(10,4) NOT NULL,
    amount DECIMAL(15,4) NOT NULL,
    commission DECIMAL(10,4) NOT NULL DEFAULT 0,
    slippage DECIMAL(10,4) NOT NULL DEFAULT 0,
    signal_date DATE NOT NULL,
    traded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 账户净值表
CREATE TABLE IF NOT EXISTS account_nav (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    nav_date DATE NOT NULL,
    total_assets DECIMAL(15,4) NOT NULL,
    cash DECIMAL(15,4) NOT NULL,
    market_value DECIMAL(15,4) NOT NULL,
    daily_return DECIMAL(8,6),
    cumulative_return DECIMAL(8,6),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, nav_date)
);

-- 银证转账表
CREATE TABLE IF NOT EXISTS bank_transfers (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    transfer_date DATE NOT NULL,
    direction VARCHAR(10) NOT NULL,
    amount DECIMAL(15,4) NOT NULL,
    remark VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 板块基础信息表
CREATE TABLE IF NOT EXISTS sectors (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(20) NOT NULL UNIQUE,
    sector_name VARCHAR(50) NOT NULL,
    industry_level VARCHAR(10) NOT NULL DEFAULT 'L1',  -- 申万行业级别
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 初始化管理员账号 (username: admin, password: admin123)
INSERT INTO users (username, password, email, role, status) VALUES
('admin', '$2a$10$rd4NHszixtQYCsFQHYL3PO/MXcUYRyFkcc0l8/ev6L7J3Y01bpJqm', 'admin@rotation.com', 'ADMIN', 'ACTIVE')
ON CONFLICT (username) DO NOTHING;

-- 初始化申万一级行业板块
INSERT INTO sectors (sector_code, sector_name) VALUES
('SW801010', '农林牧渔'), ('SW801020', '采掘'), ('SW801030', '化工'),
('SW801040', '钢铁'), ('SW801050', '有色金属'), ('SW801080', '电子'),
('SW801110', '家用电器'), ('SW801120', '食品饮料'), ('SW801130', '纺织服装'),
('SW801140', '轻工制造'), ('SW801150', '医药生物'), ('SW801160', '公用事业'),
('SW801170', '交通运输'), ('SW801180', '房地产'), ('SW801200', '商业贸易'),
('SW801210', '休闲服务'), ('SW801230', '综合'), ('SW801710', '建筑材料'),
('SW801720', '建筑装饰'), ('SW801730', '电气设备'), ('SW801740', '国防军工'),
('SW801750', '计算机'), ('SW801760', '传媒'), ('SW801770', '通信'),
('SW801780', '银行'), ('SW801790', '非银金融'), ('SW801880', '汽车'),
('SW801890', '机械设备')
ON CONFLICT (sector_code) DO NOTHING;

-- 初始化默认策略配置
INSERT INTO strategy_configs (user_id, strategy_type, name, params) VALUES
(1, 'AGGRESSIVE', '激进轮动策略', '{"top_n": 2, "max_position": 1.0, "hold_days": 3, "capital_pct": 0.5, "stop_loss": 0.05}'),
(1, 'MODERATE', '稳健轮动策略', '{"top_n": 3, "max_position": 0.5, "hold_days": 5, "capital_pct": 0.3, "stop_loss": 0.03}'),
(1, 'CONSERVATIVE', '保守轮动策略', '{"top_n": 5, "max_position": 0.3, "hold_days": 10, "capital_pct": 0.2, "stop_loss": 0.02, "valuation_pct_max": 50}')
ON CONFLICT DO NOTHING;

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_trade_signals_date ON trade_signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_trade_signals_strategy ON trade_signals(strategy_type);
CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_trades_user_date ON trades(user_id, traded_at);
CREATE INDEX IF NOT EXISTS idx_account_nav_user_date ON account_nav(user_id, nav_date);
CREATE INDEX IF NOT EXISTS idx_bank_transfers_user_date ON bank_transfers(user_id, transfer_date);
