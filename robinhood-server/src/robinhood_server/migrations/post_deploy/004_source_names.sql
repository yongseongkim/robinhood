-- 기존 API가 참조하는 표시용 컬럼은 새 API·worker 교체 후 제거한다.
ALTER TABLE subjects DROP COLUMN display_name;
ALTER TABLE merchants DROP COLUMN display_name, DROP COLUMN display_aliases;
DELETE FROM metadata WHERE key = 'people_aliases';
