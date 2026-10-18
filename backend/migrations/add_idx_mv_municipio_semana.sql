-- Migration: índice de performance no mv_curva_epidemica_municipio_semana
-- Necessário para municipio-summary endpoint (<100ms com filtro agravo+uf)
CREATE INDEX IF NOT EXISTS idx_mv_mun_semana_agravo_uf
    ON mv_curva_epidemica_municipio_semana (agravo, sigla_uf, dim_local_id, ano_epidemiologico);
