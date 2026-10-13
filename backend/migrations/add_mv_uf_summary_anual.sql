CREATE MATERIALIZED VIEW IF NOT EXISTS mv_uf_summary_anual AS
SELECT
    agravo,
    sigla_uf,
    ano_epidemiologico                AS ano,
    SUM(total_notificacoes)           AS total_notificacoes,
    SUM(max_populacao)                AS total_populacao
FROM (
    SELECT
        agravo, sigla_uf, dim_local_id, ano_epidemiologico,
        SUM(total_notificacoes) AS total_notificacoes,
        MAX(total_populacao)    AS max_populacao
    FROM mv_curva_epidemica_municipio_semana
    GROUP BY agravo, sigla_uf, dim_local_id, ano_epidemiologico
) muni_annual
GROUP BY agravo, sigla_uf, ano_epidemiologico;

CREATE INDEX IF NOT EXISTS idx_mv_uf_summary_anual
    ON mv_uf_summary_anual (agravo, sigla_uf, ano);
