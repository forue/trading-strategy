-- 修复 PostgreSQL 管理员密码（匹配 .env 中的 DB_PASSWORD）
-- 仅在首次密码配置错误时执行
ALTER USER admin WITH PASSWORD 'secret';
