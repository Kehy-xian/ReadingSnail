-- 책 읽는 달팽이 — 로컬 SQLite 스키마 v1
--
-- 요구: SQLite 3.34+ (FTS5 trigram 토크나이저). Python 3.12 동봉 버전은 충족한다.
-- 미달이면 아래 CREATE VIRTUAL TABLE 에서 즉시 실패한다. 조용히 넘어가지 않는다.
--
-- 설계 원칙
--   1. 기록은 절대 덮어쓰지 않는다. 책 1 : 기록 N.
--   2. 진화·성장·영양 관련 테이블은 존재하지 않는다.
--   3. 임베딩은 기록 저장 시점에 한 번만 계산해 여기 넣는다.
--      평소에는 추론이 돌지 않는다.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;


-- ── 책 ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS books (
    book_id      TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT '',
    publisher    TEXT,
    isbn13       TEXT,
    cover_path   TEXT,                      -- 로컬 파일 경로. 외부 URL을 저장하지 않는다.
    spine_style  INTEGER NOT NULL DEFAULT 0,-- 책등 템플릿 번호
    spine_tint   TEXT,                      -- '#RRGGBB'. 표지에서 추출하거나 사용자 지정
    status       TEXT NOT NULL DEFAULT 'reading'
                 CHECK (status IN ('reading', 'completed', 'wishlist', 'paused')),
    source       TEXT NOT NULL DEFAULT 'manual',  -- 'nl' | 'manual'
    added_at     TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
CREATE INDEX IF NOT EXISTS idx_books_finished ON books(finished_at);


-- ── 기록 ──────────────────────────────────────────────
-- kind:
--   'quote'  필사한 책 문장
--   'note'   내 생각·감상
CREATE TABLE IF NOT EXISTS entries (
    entry_id      TEXT PRIMARY KEY,
    book_id       TEXT REFERENCES books(book_id) ON DELETE SET NULL,
    kind          TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('quote', 'note')),
    body          TEXT NOT NULL,
    page          TEXT,
    created_at    TEXT NOT NULL,
    -- 384차원 float32 리틀엔디언 raw bytes. NULL이면 아직 인코딩 안 됨.
    embedding     BLOB,
    embed_model   TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_book ON entries(book_id, created_at);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
CREATE INDEX IF NOT EXISTS idx_entries_pending ON entries(embedding) WHERE embedding IS NULL;


-- ── 전문 검색 ─────────────────────────────────────────
-- 토크나이저는 trigram 이다. unicode61 을 쓰면 안 된다.
--   unicode61 은 한글을 어절 단위로만 자른다. '독서는'으로 저장된 문장이
--   '독서'로 검색되지 않는다. 조사가 붙는 한국어에서는 사실상 못 쓴다.
--   trigram 은 세 글자씩 겹쳐 색인하므로 부분 일치가 된다.
--
-- 대신 trigram 은 세 글자 미만 질의를 원리상 매칭하지 못한다.
-- '독서'(2자) 같은 흔한 검색어가 통째로 죽으므로, 질의 라우팅은
-- storage/search.py 를 반드시 거칠 것. 거기서 2자 이하는 LIKE 로 보낸다.
-- (LIKE 도 이 trigram 인덱스를 탄다. 전체 스캔이 아니다.)
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    body,
    content = 'entries',
    content_rowid = 'rowid',
    tokenize = 'trigram'
);

CREATE TRIGGER IF NOT EXISTS entries_fts_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, body) VALUES (new.rowid, new.body);
END;

CREATE TRIGGER IF NOT EXISTS entries_fts_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
END;

CREATE TRIGGER IF NOT EXISTS entries_fts_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
    INSERT INTO entries_fts(rowid, body) VALUES (new.rowid, new.body);
END;


-- ── 독서 명언 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quotes (
    quote_id  TEXT PRIMARY KEY,
    body      TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT '',  -- 출처 표기는 비워두지 않는다
    origin    TEXT NOT NULL DEFAULT 'seed'
              CHECK (origin IN ('seed', 'user'))
);

-- 시드로 한 번이라도 넣은 명언의 id 를 남긴다.
-- 사용자가 지운 명언이 다음 실행에서 되살아나지 않게 하는 장치다.
-- 시드 파일에 명언을 추가하면(새 id) 다음 실행에서 그것만 들어온다.
CREATE TABLE IF NOT EXISTS quote_seed_log (
    quote_id    TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);


-- ── 발화 이력 (같은 말 반복 방지) ─────────────────────
CREATE TABLE IF NOT EXISTS utterance_log (
    said_at   TEXT NOT NULL,
    channel   TEXT NOT NULL,   -- dialogue.Channel 값
    ref_id    TEXT NOT NULL    -- entry_id / book_id / quote_id
);

CREATE INDEX IF NOT EXISTS idx_utterance_recent ON utterance_log(said_at DESC);


-- ── 작성 중 임시저장 ──────────────────────────────────
CREATE TABLE IF NOT EXISTS drafts (
    draft_key  TEXT PRIMARY KEY,
    book_id    TEXT,
    kind       TEXT NOT NULL DEFAULT 'note',
    body       TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);


-- ── 설정 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', '1');
