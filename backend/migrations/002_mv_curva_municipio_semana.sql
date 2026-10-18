-- ============================================================
-- MV pré-agregada por município + semana epidemiológica
-- Substitui o slow path que varria 1.1M rows de mv_curva_epidemica
-- ============================================================
DROP MATERIALIZED VIEW IF EXISTS mv_curva_epidemica_municipio_semana;

CREATE MATERIALIZED VIEW mv_curva_epidemica_municipio_semana AS
SELECT
    agravo,
    sigla_uf,
    dim_local_id,
    fn_epi_year(dt_notific)  AS ano_epidemiologico,
    fn_epi_week(dt_notific)  AS semana_epidemiologica,
    SUM(total_notificacoes)  AS total_notificacoes,
    MAX(populacao)           AS total_populacao
FROM mv_curva_epidemica
WHERE dt_notific IS NOT NULL
GROUP BY agravo, sigla_uf, dim_local_id,
         fn_epi_year(dt_notific), fn_epi_week(dt_notific)
WITH DATA;

CREATE INDEX idx_mv_curva_mun_semana_lookup
    ON mv_curva_epidemica_municipio_semana (agravo, dim_local_id, ano_epidemiologico, semana_epidemiologica);

CREATE INDEX idx_mv_curva_mun_semana_agravo_uf
    ON mv_curva_epidemica_municipio_semana (agravo, sigla_uf, ano_epidemiologico, semana_epidemiologica);
