-- ============================================================
-- Semana epidemiológica (DataSUS / MMWR, Sunday-anchored)
-- Equivalente ao fn semana_epidemiologica() do Python
-- ============================================================

-- Domingo da semana (âncora)
CREATE OR REPLACE FUNCTION fn_week_sunday(dt date)
RETURNS date LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT (dt - EXTRACT(DOW FROM dt)::int)::date;
$$;

-- Ano epidemiológico: determinado pela quarta-feira da semana
-- (quarta-feira = 4º dia Sun–Sat; se cai no novo ano, a semana pertence ao novo ano)
CREATE OR REPLACE FUNCTION fn_epi_year(dt date)
RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT EXTRACT(YEAR FROM fn_week_sunday(dt) + 3)::int;
$$;

-- Domingo da semana 1 de um dado ano epidemiológico
-- Regra: a semana 1 contém o dia 4 de janeiro (sempre na semana 1)
CREATE OR REPLACE FUNCTION fn_week1_sunday(yr int)
RETURNS date LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT (make_date(yr, 1, 4) - EXTRACT(DOW FROM make_date(yr, 1, 4))::int)::date;
$$;

-- Número da semana epidemiológica
CREATE OR REPLACE FUNCTION fn_epi_week(dt date)
RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT (fn_week_sunday(dt) - fn_week1_sunday(fn_epi_year(dt))) / 7 + 1;
$$;

-- ============================================================
-- MV pré-agregada por semana epidemiológica
-- Reduz 1.1M linhas (por dia+município) para ~500 (por semana)
-- ============================================================
DROP MATERIALIZED VIEW IF EXISTS mv_curva_epidemica_semana;

CREATE MATERIALIZED VIEW mv_curva_epidemica_semana AS
SELECT
    agravo,
    sigla_uf,
    epi_year                    AS ano_epidemiologico,
    epi_week                    AS semana_epidemiologica,
    SUM(total_notificacoes)     AS total_notificacoes,
    -- Soma da população de cada município distinto na semana
    -- (MAX por município evita dupla contagem entre dias da mesma semana)
    SUM(pop_municipio)          AS total_populacao
FROM (
    SELECT
        agravo,
        sigla_uf,
        dim_local_id,
        fn_epi_year(dt_notific)  AS epi_year,
        fn_epi_week(dt_notific)  AS epi_week,
        SUM(total_notificacoes)  AS total_notificacoes,
        MAX(populacao)           AS pop_municipio
    FROM mv_curva_epidemica
    WHERE dt_notific IS NOT NULL
    GROUP BY agravo, sigla_uf, dim_local_id,
             fn_epi_year(dt_notific), fn_epi_week(dt_notific)
) t
GROUP BY agravo, sigla_uf, epi_year, epi_week
WITH DATA;

-- Índice principal: cobre todos os filtros do endpoint
CREATE INDEX idx_mv_curva_semana_lookup
    ON mv_curva_epidemica_semana (agravo, sigla_uf, ano_epidemiologico, semana_epidemiologica);

-- Índice para consultas nacionais (sem filtro de UF)
CREATE INDEX idx_mv_curva_semana_agravo
    ON mv_curva_epidemica_semana (agravo, ano_epidemiologico, semana_epidemiologica);
